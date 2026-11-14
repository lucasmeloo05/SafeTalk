import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Server, ServerConfigHistory, ServerMember, User
from app.server_permissions import SERVER_PERMISSION_KEYS
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
    server = Server(
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
            )
            .order_by(Server.created_at.desc(), Server.id.desc())
        ).all()
    )


def get_server_for_active_member(
    db: Session,
    current_user: User,
    server_id: int,
) -> Server:
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
) -> Server:
    server = get_server_for_active_member(db, current_user, server_id)
    if server.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o proprietário pode atualizar este servidor.",
        )

    for field_name in server_data.model_fields_set:
        setattr(server, field_name, getattr(server_data, field_name))

    try:
        db.commit()
        db.refresh(server)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atualizar o servidor.",
        ) from exc

    return server


def update_everyone_permissions(
    db: Session,
    current_user: User,
    server_id: int,
    permissions: dict[str, bool],
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

        old_permissions = dict(server.everyone_permissions)
        new_permissions = dict(permissions)
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
            everyone_permissions=new_permissions,
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
