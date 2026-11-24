import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerAuditLog,
    ServerBan,
    ServerConfigHistory,
    ServerMember,
    User,
)
from app.age_policy import age_filter, is_adult, require_age
from app.server_permissions import SERVER_PERMISSION_KEYS, check_expected_permissions
from app.schemas import (
    ServerCreate,
    ServerEveryonePermissionsResponse,
    ServerResponse,
    ServerUpdate,
)


def create_server(
    db: Session,
    current_user: User,
    server_data: ServerCreate,
) -> ServerResponse:
    if server_data.is_adult and not is_adult(current_user.birth_date):
        raise HTTPException(403, "Servidores +18 exigem idade declarada de pelo menos 18 anos.")
    server = Server(
        is_adult=server_data.is_adult,
        owner_id=current_user.id,
        name=server_data.name,
        description=server_data.description,
    )

    try:
        db.add(server)
        db.flush()
        db.add(
            ServerMember(
                server_id=server.id,
                user_id=current_user.id,
                status="ACTIVE",
            )
        )
        db.flush()
        db.refresh(server)
        response = ServerResponse.model_validate(server)
        db.commit()
        return response
    except Exception as exc:
        db.rollback()
        if isinstance(exc, IntegrityError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Não foi possível criar o servidor.",
            ) from exc
        if isinstance(exc, SQLAlchemyError):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Não foi possível criar o servidor.",
            ) from exc
        raise


def list_active_servers(db: Session, current_user: User) -> list[Server]:
    return list(
        db.scalars(
            select(Server)
            .join(ServerMember, ServerMember.server_id == Server.id)
            .where(
                ServerMember.user_id == current_user.id,
                ServerMember.status == "ACTIVE",
                age_filter(current_user),
            )
            .order_by(Server.created_at.desc(), Server.id.desc())
        ).all()
    )


def get_server_for_active_member(
    db: Session,
    current_user: User,
    server_id: int,
) -> Server:
    require_age(db, server_id, current_user.id)
    server = db.scalar(
        select(Server)
        .join(ServerMember, ServerMember.server_id == Server.id)
        .where(
            Server.id == server_id,
            ServerMember.user_id == current_user.id,
            ServerMember.status == "ACTIVE",
        )
    )
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )
    return server


def update_server(
    db: Session,
    current_user: User,
    server_id: int,
    server_data: ServerUpdate,
) -> ServerResponse:
    try:
        server = db.scalar(
            select(Server)
            .join(ServerMember, ServerMember.server_id == Server.id)
            .where(Server.id == server_id, ServerMember.user_id == current_user.id,
                   ServerMember.status == "ACTIVE")
            .with_for_update(of=Server)
            .execution_options(populate_existing=True)
        )
        if server is None:
            raise HTTPException(404, "Servidor não encontrado.")
        if server.owner_id != current_user.id:
            raise HTTPException(403, "Somente o proprietário pode atualizar este servidor.")

        for field, value in server_data.model_dump(exclude_unset=True).items():
            previous = getattr(server, field)
            if previous == value:
                continue
            db.add(ServerConfigHistory(
                server_id=server.id, changed_by=current_user.id, setting_name=field,
                old_value=json.dumps(previous, ensure_ascii=False),
                new_value=json.dumps(value, ensure_ascii=False),
            ))
            setattr(server, field, value)

        db.flush()
        response = ServerResponse.model_validate(server)
        db.commit()
        return response
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atualizar o servidor.",
        ) from exc

    except Exception:
        db.rollback()
        raise


def transfer_server_ownership(
    db: Session,
    server_id: int,
    actor_user_id: int,
    new_owner_id: int,
) -> ServerResponse:
    """Transfer ownership and persist both audit records atomically.

    Lock order is server, active memberships ordered by membership ID, then
    the recipient's active ban row. This serializes transfers with leave,
    kick, ban, unban, and invite acceptance, which also lock the server first.
    Ownership remains separate from role permissions and hierarchy.
    """
    try:
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

        if server.owner_id != actor_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Somente o proprietário atual pode transferir o servidor.",
            )

        require_age(db, server_id, actor_user_id)
        require_age(db, server_id, new_owner_id)
        if new_owner_id == actor_user_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O novo proprietário deve ser outro membro.",
            )

        memberships = db.scalars(
            select(ServerMember)
            .where(
                ServerMember.server_id == server_id,
                ServerMember.user_id.in_({actor_user_id, new_owner_id}),
            )
            .order_by(ServerMember.id.asc())
            .with_for_update()
        ).all()
        members_by_user_id = {member.user_id: member for member in memberships}

        current_owner_membership = members_by_user_id.get(actor_user_id)
        if (
            current_owner_membership is None
            or current_owner_membership.status != "ACTIVE"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A participação do proprietário atual não está ativa.",
            )

        recipient_membership = members_by_user_id.get(new_owner_id)
        if recipient_membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="O destinatário não é membro deste servidor.",
            )
        if recipient_membership.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O destinatário não possui participação ativa.",
            )

        active_ban = db.scalar(
            select(ServerBan.id)
            .where(
                ServerBan.server_id == server_id,
                ServerBan.user_id == new_owner_id,
                ServerBan.is_active.is_(True),
            )
            .with_for_update()
        )
        if active_ban is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Um membro banido não pode receber a propriedade.",
            )

        previous_owner_id = server.owner_id
        server.owner_id = new_owner_id
        db.add(
            ServerConfigHistory(
                server_id=server.id,
                changed_by=actor_user_id,
                setting_name="owner_id",
                old_value=str(previous_owner_id),
                new_value=str(new_owner_id),
            )
        )
        db.add(
            ServerAuditLog(
                server_id=server.id,
                event_type="OWNERSHIP_TRANSFERRED",
                actor_user_id=actor_user_id,
                target_user_id=new_owner_id,
                ban_id=None,
                role_snapshot=None,
            )
        )
        db.flush()
        db.refresh(server)
        response = ServerResponse.model_validate(server)
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível transferir a propriedade do servidor.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def update_everyone_permissions(
    db: Session,
    current_user: User,
    server_id: int,
    permissions: dict[str, bool],
    expected_permissions: str | None = None,
) -> ServerEveryonePermissionsResponse:
    """Replace @everyone grants and audit the change atomically."""
    if not isinstance(permissions, dict) or any(
        key not in SERVER_PERMISSION_KEYS or type(value) is not bool
        for key, value in permissions.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A configuração contém permissões ou valores inválidos.",
        )

    try:
        server = db.scalar(
            select(Server)
            .where(Server.id == server_id)
            .execution_options(populate_existing=True)
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
                ServerMember.server_id == server.id,
                ServerMember.user_id == current_user.id,
                ServerMember.status == "ACTIVE",
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Servidor não encontrado.",
            )

        if server.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Somente o proprietário pode alterar estas permissões.",
            )

        check_expected_permissions(expected_permissions, server.everyone_permissions)
        old_permissions = dict(server.everyone_permissions)
        # Clients can only update the closed permission catalog. Preserve any
        # unknown legacy keys already stored instead of erasing them during a
        # replacement of the known grants.
        preserved_unknown_permissions = {
            key: value
            for key, value in old_permissions.items()
            if key not in SERVER_PERMISSION_KEYS
        }
        new_permissions = {
            **preserved_unknown_permissions,
            **dict(permissions),
        }
        old_value = json.dumps(
            old_permissions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        new_value = json.dumps(
            new_permissions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        server.everyone_permissions = new_permissions
        db.flush()
        db.add(
            ServerConfigHistory(
                server_id=server.id,
                changed_by=current_user.id,
                setting_name="everyone_permissions",
                old_value=old_value,
                new_value=new_value,
            )
        )
        db.flush()

        response = ServerEveryonePermissionsResponse(
            server_id=server.id,
            everyone_permissions={
                key: value
                for key, value in new_permissions.items()
                if key in SERVER_PERMISSION_KEYS and type(value) is bool
            },
        )
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atualizar as permissões do servidor.",
        ) from exc
    except Exception:
        db.rollback()
        raise
