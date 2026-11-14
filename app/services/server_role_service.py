from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Server, ServerMember, ServerRole, User
from app.schemas import ServerRoleCreate
from app.services.server_authorization_service import (
    get_member_hierarchy_level,
    has_server_permission,
    require_active_server_membership,
    resolve_server_permissions,
)


def list_server_roles(
    db: Session,
    current_user: User,
    server_id: int,
) -> list[ServerRole]:
    require_active_server_membership(db, server_id, current_user.id)

    return list(
        db.scalars(
            select(ServerRole)
            .where(ServerRole.server_id == server_id)
            .order_by(ServerRole.position.asc(), ServerRole.id.asc())
        ).all()
    )


def get_server_role(
    db: Session,
    current_user: User,
    server_id: int,
    role_id: int,
) -> ServerRole:
    require_active_server_membership(db, server_id, current_user.id)

    role = db.scalar(
        select(ServerRole).where(
            ServerRole.id == role_id,
            ServerRole.server_id == server_id,
        )
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cargo não encontrado.",
        )
    return role


def _is_server_role_name_conflict(error: IntegrityError) -> bool:
    """Recognize only the constraint for exact per-server role names."""
    original_error = getattr(error, "orig", None)
    diagnostic = getattr(original_error, "diag", None)
    return (
        getattr(diagnostic, "constraint_name", None)
        == "uq_server_roles_server_name"
    )


def create_server_role(
    db: Session,
    server_id: int,
    actor_user_id: int,
    role_data: ServerRoleCreate,
) -> ServerRole:
    """Create a common role after authorization, in one server transaction.

    The authenticated principal must supply ``actor_user_id``. Future role
    editing and assignment operations must acquire this same server-row lock
    before reading authority or changing roles/assignments, so those checks
    serialize against each other.
    """
    try:
        # Keep the lock order consistent with membership mutations: server,
        # participation, then role assignments/role rows.
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
                ServerMember.user_id == actor_user_id,
            )
            .with_for_update()
        )
        if membership is None or membership.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Servidor não encontrado.",
            )

        resolved = resolve_server_permissions(db, server_id, actor_user_id)
        if not resolved.is_owner:
            if not has_server_permission(resolved, "manage_roles"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não pode criar cargos neste servidor.",
                )

            actor_level = get_member_hierarchy_level(
                db, server_id, actor_user_id
            )
            if actor_level <= role_data.position:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "A posição do novo cargo deve ser inferior à sua "
                        "hierarquia."
                    ),
                )

            requested_grants = {
                permission
                for permission, granted in role_data.permissions.items()
                if granted is True
            }
            if not requested_grants.issubset(resolved.permissions):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Você não pode conceder permissões que não possui."
                    ),
                )

        role = ServerRole(
            server_id=server.id,
            name=role_data.name,
            description=role_data.description,
            position=role_data.position,
            permissions=dict(role_data.permissions),
            is_default=False,
            is_system_role=False,
        )
        db.add(role)
        db.flush()
        db.refresh(role)
        db.commit()
        return role
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if _is_server_role_name_conflict(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um cargo com este nome no servidor.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o cargo.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o cargo.",
        ) from exc
    except Exception:
        db.rollback()
        raise
