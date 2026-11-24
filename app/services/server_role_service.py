import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerConfigHistory,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.models.server_channel import ServerChannelRole
from app.schemas import ServerRoleCreate, ServerRoleResponse, ServerRoleUpdate
from app.server_permissions import SERVER_PERMISSION_KEYS, check_expected_permissions
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


def _role_snapshot(role: ServerRole) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "position": role.position,
        "permissions": dict(role.permissions),
        "is_default": role.is_default,
        "is_system_role": role.is_system_role,
        "created_at": role.created_at.isoformat(),
    }


def create_server_role(
    db: Session,
    server_id: int,
    actor_user_id: int,
    role_data: ServerRoleCreate,
) -> ServerRoleResponse:
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
        db.add(ServerConfigHistory(
            server_id=server.id,
            changed_by=actor_user_id,
            setting_name=f"server_role:{role.id}",
            old_value=json.dumps(None),
            new_value=json.dumps(_role_snapshot(role), ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":")),
        ))
        db.flush()
        response = ServerRoleResponse.model_validate(role)
        db.commit()
        return response
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


def _granted_permissions(value: object) -> set[str]:
    if not isinstance(value, dict):
        return set()
    return {
        key
        for key, granted in value.items()
        if key in SERVER_PERMISSION_KEYS and granted is True
    }


def _is_server_member_role_duplicate(error: IntegrityError) -> bool:
    original_error = getattr(error, "orig", None)
    diagnostic = getattr(original_error, "diag", None)
    return (
        getattr(diagnostic, "constraint_name", None)
        == "uq_server_member_roles_member_role"
    )


def _lock_role_assignment_context(
    db: Session,
    server_id: int,
    actor_user_id: int,
    target_user_id: int,
    role_id: int,
):
    """Lock and validate the shared authorization context for role changes.

    Lock order is server, actor membership, role, target membership, then the
    association. It matches the existing role mutation order after the server
    lock, so role assignment is serialized with role edits/deletion and member
    departure.
    """
    server = db.scalar(
        select(Server).where(Server.id == server_id).with_for_update()
    )
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )

    actor_membership = db.scalar(
        select(ServerMember)
        .where(
            ServerMember.server_id == server_id,
            ServerMember.user_id == actor_user_id,
        )
        .with_for_update()
    )
    if actor_membership is None or actor_membership.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )

    role = db.scalar(
        select(ServerRole)
        .where(
            ServerRole.id == role_id,
            ServerRole.server_id == server_id,
        )
        .with_for_update()
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cargo não encontrado.",
        )

    if role.is_system_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Cargos reservados ao sistema não podem ser atribuídos "
                "ou removidos."
            ),
        )

    if target_user_id == actor_user_id:
        target_membership = actor_membership
    else:
        target_membership = db.scalar(
            select(ServerMember)
            .where(
                ServerMember.server_id == server_id,
                ServerMember.user_id == target_user_id,
            )
            .with_for_update()
        )
    if target_membership is None or target_membership.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membro não encontrado.",
        )

    actor_permissions = resolve_server_permissions(
        db, server_id, actor_user_id
    )
    is_owner = server.owner_id == actor_user_id
    actor_level: int | None = None
    if not is_owner:
        if target_user_id == server.owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Membros comuns não podem alterar cargos do proprietário.",
            )
        if not has_server_permission(actor_permissions, "manage_roles"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não pode gerenciar cargos neste servidor.",
            )

        actor_level = get_member_hierarchy_level(
            db, server_id, actor_user_id
        )
        if role.position >= actor_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Você não pode gerenciar um cargo de hierarquia igual "
                    "ou superior."
                ),
            )

        if target_user_id != actor_user_id:
            target_level = get_member_hierarchy_level(
                db, server_id, target_user_id
            )
            if target_level >= actor_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Você não pode alterar cargos de membro com "
                        "hierarquia igual ou superior."
                    ),
                )

    return (
        server,
        actor_membership,
        role,
        target_membership,
        actor_permissions,
        is_owner,
        actor_level,
    )


def _role_assignment_snapshot(
    assignment: ServerMemberRole,
) -> dict[str, object]:
    return {
        "server_id": assignment.server_id,
        "member_id": assignment.member_id,
        "role_id": assignment.role_id,
        "assigned_at": assignment.assigned_at.isoformat(),
        "assigned_by": assignment.assigned_by,
    }


def assign_server_role_to_member(
    db: Session,
    server_id: int,
    target_user_id: int,
    role_id: int,
    actor_user_id: int,
) -> None:
    """Ensure a role assignment exists, enforcing authorization and audit.

    Every assignment mutation takes the server row lock first. Repeated PUTs
    are idempotent and do not produce duplicate association or audit rows.
    """
    try:
        (
            server,
            _actor_membership,
            role,
            target_membership,
            actor_permissions,
            is_owner,
            actor_level,
        ) = _lock_role_assignment_context(
            db, server_id, actor_user_id, target_user_id, role_id
        )

        if not is_owner:
            target_permissions = resolve_server_permissions(
                db, server_id, target_user_id
            ).permissions
            grants_after_assignment = set(target_permissions)
            grants_after_assignment.update(
                _granted_permissions(role.permissions)
            )
            newly_granted = grants_after_assignment.difference(
                target_permissions
            )
            if not newly_granted.issubset(actor_permissions.permissions):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "A atribuição concederia permissões efetivas que "
                        "você não possui."
                    ),
                )

        if not is_owner and target_user_id != actor_user_id:
            assert actor_level is not None
            target_level_after = max(
                get_member_hierarchy_level(db, server_id, target_user_id),
                role.position,
            )
            if target_level_after >= actor_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "A atribuição elevaria o membro à sua hierarquia "
                        "ou acima dela."
                    ),
                )

        assignment = db.scalar(
            select(ServerMemberRole)
            .where(
                ServerMemberRole.server_id == server_id,
                ServerMemberRole.member_id == target_membership.id,
                ServerMemberRole.role_id == role.id,
            )
            .with_for_update()
        )
        if assignment is not None:
            db.commit()
            return

        assignment = ServerMemberRole(
            server_id=server.id,
            member_id=target_membership.id,
            role_id=role.id,
            assigned_by=actor_user_id,
        )
        db.add(assignment)
        db.flush()
        db.refresh(assignment)

        db.add(
            ServerConfigHistory(
                server_id=server.id,
                changed_by=actor_user_id,
                setting_name=(
                    f"server_member_role:{target_membership.id}:{role.id}"
                ),
                old_value=json.dumps(
                    None,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                new_value=json.dumps(
                    _role_assignment_snapshot(assignment),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if _is_server_member_role_duplicate(exc):
            existing_assignment = db.scalar(
                select(ServerMemberRole.id).where(
                    ServerMemberRole.server_id == server_id,
                    ServerMemberRole.role_id == role_id,
                    ServerMemberRole.member_id.in_(
                        select(ServerMember.id).where(
                            ServerMember.server_id == server_id,
                            ServerMember.user_id == target_user_id,
                        )
                    ),
                )
            )
            if existing_assignment is not None:
                return
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atribuir o cargo ao membro.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atribuir o cargo ao membro.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def remove_server_role_from_member(
    db: Session,
    server_id: int,
    target_user_id: int,
    role_id: int,
    actor_user_id: int,
) -> None:
    """Ensure a role assignment is absent, enforcing authorization and audit.

    Repeated DELETEs are idempotent and do not produce duplicate audit rows.
    """
    try:
        (
            server,
            _actor_membership,
            role,
            target_membership,
            _actor_permissions,
            _is_owner,
            _actor_level,
        ) = _lock_role_assignment_context(
            db, server_id, actor_user_id, target_user_id, role_id
        )

        assignment = db.scalar(
            select(ServerMemberRole)
            .where(
                ServerMemberRole.server_id == server_id,
                ServerMemberRole.member_id == target_membership.id,
                ServerMemberRole.role_id == role.id,
            )
            .with_for_update()
        )
        if assignment is None:
            db.commit()
            return

        snapshot = _role_assignment_snapshot(assignment)
        db.delete(assignment)
        db.flush()
        db.add(
            ServerConfigHistory(
                server_id=server.id,
                changed_by=actor_user_id,
                setting_name=(
                    f"server_member_role:{target_membership.id}:{role.id}"
                ),
                old_value=json.dumps(
                    snapshot,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                new_value=json.dumps(
                    {"removed": True},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível remover o cargo do membro.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def _member_permission_changes_after_role_update(
    db: Session,
    server: Server,
    role: ServerRole,
    member_ids: list[int],
    new_role_permissions: dict,
) -> dict[int, tuple[set[str], set[str]]]:
    """Return each affected member's effective grants before and after edit."""
    if not member_ids:
        return {}

    everyone_grants = _granted_permissions(server.everyone_permissions)
    before = {member_id: set(everyone_grants) for member_id in member_ids}
    after = {member_id: set(everyone_grants) for member_id in member_ids}

    assignments = db.execute(
        select(
            ServerMemberRole.member_id,
            ServerRole.id,
            ServerRole.permissions,
        )
        .join(
            ServerRole,
            (ServerRole.id == ServerMemberRole.role_id)
            & (ServerRole.server_id == ServerMemberRole.server_id),
        )
        .where(
            ServerMemberRole.server_id == server.id,
            ServerRole.server_id == server.id,
            ServerMemberRole.member_id.in_(member_ids),
        )
    ).all()

    for member_id, assigned_role_id, assigned_permissions in assignments:
        before[member_id].update(_granted_permissions(assigned_permissions))
        after_permissions = (
            new_role_permissions
            if assigned_role_id == role.id
            else assigned_permissions
        )
        after[member_id].update(_granted_permissions(after_permissions))

    return {
        member_id: (before[member_id], after[member_id])
        for member_id in member_ids
    }


def update_server_role(
    db: Session,
    server_id: int,
    role_id: int,
    actor_user_id: int,
    role_data: ServerRoleUpdate,
    expected_permissions: str | None = None,
) -> ServerRoleResponse:
    """Update a common role, applying authorization and audit atomically.

    Mutations of roles and assignments must take the server row lock first;
    this serializes authority checks against other operations in that server.
    ServerConfigHistory records a JSON snapshot of only changed properties,
    keyed by ``server_role:<role_id>`` in ``setting_name``.
    """
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
                ServerMember.server_id == server_id,
                ServerMember.user_id == actor_user_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if membership is None or membership.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Servidor não encontrado.",
            )

        role = db.scalar(
            select(ServerRole)
            .where(
                ServerRole.id == role_id,
                ServerRole.server_id == server_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cargo não encontrado.",
            )

        if role.is_system_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cargos reservados ao sistema não podem ser alterados.",
            )

        resolved_actor = resolve_server_permissions(
            db, server_id, actor_user_id
        )
        is_owner = server.owner_id == actor_user_id
        actor_level: int | None = None
        if not is_owner:
            if not has_server_permission(resolved_actor, "manage_roles"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não pode editar cargos neste servidor.",
                )

            actor_level = get_member_hierarchy_level(
                db, server_id, actor_user_id
            )
            if role.position >= actor_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não pode editar um cargo de hierarquia igual ou superior.",
                )
            if (
                "position" in role_data.model_fields_set
                and role_data.position >= actor_level
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="A posição pretendida deve permanecer abaixo da sua hierarquia.",
                )

        affected_members = list(
            db.scalars(
                select(ServerMember)
                .join(
                    ServerMemberRole,
                    (ServerMemberRole.member_id == ServerMember.id)
                    & (ServerMemberRole.server_id == ServerMember.server_id),
                )
                .where(
                    ServerMember.server_id == server_id,
                    ServerMember.status == "ACTIVE",
                    ServerMemberRole.server_id == server_id,
                    ServerMemberRole.role_id == role.id,
                )
                .order_by(ServerMember.id.asc())
                .with_for_update(of=ServerMember)
            ).all()
        )

        if not is_owner:
            assert actor_level is not None
            for affected_member in affected_members:
                if affected_member.user_id == actor_user_id:
                    continue
                if affected_member.user_id == server.owner_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Você não pode editar cargo atribuído ao proprietário.",
                    )
                target_level = get_member_hierarchy_level(
                    db, server_id, affected_member.user_id
                )
                if target_level >= actor_level:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="O cargo está atribuído a membro de hierarquia igual ou superior.",
                    )

        if "permissions" in role_data.model_fields_set:
            check_expected_permissions(expected_permissions, role.permissions)
            proposed_permissions = {
                key: value for key, value in role.permissions.items()
                if key not in SERVER_PERMISSION_KEYS
            }
            proposed_permissions.update(role_data.permissions)
        if not is_owner and "permissions" in role_data.model_fields_set:
            old_role_grants = _granted_permissions(role.permissions)
            new_role_grants = _granted_permissions(proposed_permissions)
            if not new_role_grants.difference(old_role_grants).issubset(
                resolved_actor.permissions
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não pode conceder permissões que não possui.",
                )

            member_permission_changes = (
                _member_permission_changes_after_role_update(
                    db,
                    server,
                    role,
                    [item.id for item in affected_members],
                    proposed_permissions,
                )
            )
            for before_permissions, after_permissions in (
                member_permission_changes.values()
            ):
                if not after_permissions.difference(before_permissions).issubset(
                    resolved_actor.permissions
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="A alteração concederia ao membro permissões que você não possui.",
                    )

        old_values: dict[str, object] = {}
        new_values: dict[str, object] = {}
        for field_name in role_data.model_fields_set:
            new_value = getattr(role_data, field_name)
            if field_name == "permissions":
                new_value = proposed_permissions
            old_value = getattr(role, field_name)
            if old_value != new_value:
                old_values[field_name] = (
                    dict(old_value) if field_name == "permissions" else old_value
                )
                new_values[field_name] = new_value

        if old_values:
            for field_name, new_value in new_values.items():
                setattr(role, field_name, new_value)
            db.flush()
            db.add(
                ServerConfigHistory(
                    server_id=server.id,
                    changed_by=actor_user_id,
                    setting_name=f"server_role:{role.id}",
                    old_value=json.dumps(
                        old_values,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    new_value=json.dumps(
                        new_values,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
            db.flush()
            db.refresh(role)

        response = ServerRoleResponse.model_validate(role)
        db.commit()
        return response
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
            detail="Não foi possível atualizar o cargo.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atualizar o cargo.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def delete_server_role(
    db: Session,
    server_id: int,
    role_id: int,
    actor_user_id: int,
) -> None:
    """Delete an unassigned common role and preserve its audit snapshot.

    The actor ID must come from the authenticated principal. The server row is
    locked before authorization and role rows; future role-assignment services
    must use the same server-first lock protocol to serialize assignment with
    deletion.
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

        role = db.scalar(
            select(ServerRole)
            .where(
                ServerRole.id == role_id,
                ServerRole.server_id == server_id,
            )
            .with_for_update()
        )
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cargo não encontrado.",
            )

        if role.is_system_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cargos reservados ao sistema não podem ser excluídos.",
            )

        resolved_actor = resolve_server_permissions(
            db, server_id, actor_user_id
        )
        is_owner = server.owner_id == actor_user_id
        if not is_owner:
            if not has_server_permission(resolved_actor, "manage_roles"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não pode excluir cargos neste servidor.",
                )

            actor_level = get_member_hierarchy_level(
                db, server_id, actor_user_id
            )
            if actor_level <= role.position:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Você não pode excluir um cargo de hierarquia igual "
                        "ou superior."
                    ),
                )

        assignment_id = db.scalar(
            select(ServerMemberRole.id)
            .where(
                ServerMemberRole.server_id == server_id,
                ServerMemberRole.role_id == role.id,
            )
            .limit(1)
        )
        if assignment_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Não é possível excluir um cargo que possui membros atribuídos.",
            )

        if db.scalar(select(ServerChannelRole.channel_id).where(
            ServerChannelRole.server_id == server_id, ServerChannelRole.role_id == role.id
        ).limit(1)) is not None:
            raise HTTPException(409, "Revogue o acesso do cargo aos canais antes de excluí-lo.")

        old_value = _role_snapshot(role)
        db.add(
            ServerConfigHistory(
                server_id=server.id,
                changed_by=actor_user_id,
                setting_name=f"server_role:{role.id}",
                old_value=json.dumps(
                    old_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                new_value=json.dumps(
                    {"deleted": True},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        # Flush audit first, but keep it uncommitted until deletion succeeds.
        db.flush()
        db.delete(role)
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível excluir o cargo.",
        ) from exc
    except Exception:
        db.rollback()
        raise
