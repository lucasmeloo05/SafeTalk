from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Server, ServerMember, ServerMemberRole, User
from app.schemas import ServerMemberResponse
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

    rows = db.execute(
        select(
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
    ).mappings()

    return [ServerMemberResponse.model_validate(dict(row)) for row in rows]


def get_active_server_member(
    db: Session,
    current_user: User,
    server_id: int,
    user_id: int,
) -> ServerMemberResponse:
    require_active_server_membership(db, server_id, current_user.id)

    row = db.execute(
        select(
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
    return ServerMemberResponse.model_validate(dict(row))


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
