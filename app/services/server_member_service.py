from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Server, ServerMember, ServerMemberRole, ServerRole, User
from app.schemas import ServerMemberResponse, ServerMemberRoleSummary
from app.services.server_authorization_service import (
    require_active_server_membership,
)


def list_active_server_members(
    db: Session,
    current_user: User,
    server_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[ServerMemberResponse]:
    require_active_server_membership(db, server_id, current_user.id)

    rows = list(db.execute(
        select(
            ServerMember.id.label("member_id"),
            ServerMember.user_id.label("user_id"),
            User.username.label("username"),
            ServerMember.joined_at.label("joined_at"),
        )
        .join(User, User.id == ServerMember.user_id)
        .where(
            ServerMember.server_id == server_id,
            ServerMember.status == "ACTIVE",
        )
        .order_by(ServerMember.joined_at.desc(), ServerMember.user_id.asc())
        .limit(limit)
        .offset(offset)
    ).mappings().all())

    roles_by_member = _load_member_role_summaries(
        db,
        server_id,
        [row["member_id"] for row in rows],
    )

    return [
        ServerMemberResponse.model_validate({
            "user_id": row["user_id"],
            "username": row["username"],
            "joined_at": row["joined_at"],
            "roles": roles_by_member.get(row["member_id"], []),
        })
        for row in rows
    ]


def _load_member_role_summaries(
    db: Session,
    server_id: int,
    membership_ids: list[int],
) -> dict[int, list[ServerMemberRoleSummary]]:
    """Load assignments for a page of members with one bounded query."""
    if not membership_ids:
        return {}

    rows = db.execute(
        select(
            ServerMemberRole.member_id,
            ServerRole.id.label("id"),
            ServerRole.name,
            ServerRole.position,
        )
        .join(
            ServerRole,
            (ServerRole.id == ServerMemberRole.role_id)
            & (ServerRole.server_id == ServerMemberRole.server_id),
        )
        .where(
            ServerMemberRole.server_id == server_id,
            ServerMemberRole.member_id.in_(membership_ids),
            ServerRole.server_id == server_id,
        )
        .order_by(
            ServerMemberRole.member_id.asc(),
            ServerRole.position.desc(),
            ServerRole.id.asc(),
        )
    ).all()

    roles_by_member: dict[int, list[ServerMemberRoleSummary]] = {}
    for member_id, role_id, name, position in rows:
        roles_by_member.setdefault(member_id, []).append(
            ServerMemberRoleSummary(
                id=role_id,
                name=name,
                position=position,
            )
        )
    return roles_by_member


def get_active_server_member(
    db: Session,
    current_user: User,
    server_id: int,
    user_id: int,
) -> ServerMemberResponse:
    require_active_server_membership(db, server_id, current_user.id)

    row = db.execute(
        select(
            ServerMember.id.label("member_id"),
            ServerMember.user_id.label("user_id"),
            User.username.label("username"),
            ServerMember.joined_at.label("joined_at"),
        )
        .join(User, User.id == ServerMember.user_id)
        .where(
            ServerMember.server_id == server_id,
            ServerMember.user_id == user_id,
            ServerMember.status == "ACTIVE",
        )
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membro não encontrado.",
        )
    return ServerMemberResponse.model_validate({
        "user_id": row["user_id"],
        "username": row["username"],
        "joined_at": row["joined_at"],
        "roles": _load_member_role_summaries(
            db,
            server_id,
            [row["member_id"]],
        ).get(row["member_id"], []),
    })


def _remove_member_role_assignments(
    db: Session,
    server_id: int,
    member_id: int,
) -> None:
    db.execute(
        delete(ServerMemberRole).where(
            ServerMemberRole.server_id == server_id,
            ServerMemberRole.member_id == member_id,
        )
    )


def leave_server(
    db: Session,
    current_user: User,
    server_id: int,
) -> None:
    try:
        # All server membership mutations acquire locks in this order:
        # server, participation, then role assignments.
        server = db.scalar(
            select(Server)
            .where(Server.id == server_id)
            .with_for_update()
        )
        if server is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Servidor não encontrado.",
            )

        membership = db.scalar(
            select(ServerMember)
            .where(
                ServerMember.server_id == server_id,
                ServerMember.user_id == current_user.id,
            )
            .with_for_update()
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Servidor não encontrado.",
            )

        if membership.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A participação já foi encerrada.",
            )

        if server.owner_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Transfira a propriedade do servidor antes de sair."
                ),
            )

        _remove_member_role_assignments(db, server_id, membership.id)
        membership.status = "LEFT"
        membership.left_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível encerrar a participação.",
        ) from exc
    except Exception:
        db.rollback()
        raise
