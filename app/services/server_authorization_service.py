from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.server_permissions import SERVER_PERMISSION_KEYS
from app.schemas import ServerAuthorizationContextResponse


# Only permission keys explicitly named in the approved project documents are
# recognized here. Unknown JSONB keys must never become effective grants.
@dataclass(frozen=True)
class ResolvedServerPermissions:
    """Effective explicit grants for one active member in one server.

    Ownership is exposed separately because owner authority is operation-
    specific and must not be represented as JSONB role grants.
    """

    server_id: int
    user_id: int
    membership_id: int
    is_owner: bool
    permissions: frozenset[str]


def _granted_permissions(value: object) -> set[str]:
    """Return known keys whose JSONB value is the boolean true."""
    if not isinstance(value, dict):
        return set()
    return {
        key
        for key, granted in value.items()
        if key in SERVER_PERMISSION_KEYS and granted is True
    }


def require_active_server_membership(
    db: Session,
    server_id: int,
    user_id: int,
) -> ServerMember:
    from app.age_policy import is_adult
    row = db.execute(
        select(ServerMember, Server.is_adult, User.birth_date)
        .join(Server, Server.id == ServerMember.server_id)
        .join(User, User.id == ServerMember.user_id)
        .where(
            ServerMember.server_id == server_id,
            ServerMember.user_id == user_id,
            ServerMember.status == "ACTIVE",
        )
    ).one_or_none()
    if row is None or (row[1] and not is_adult(row[2])):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )
    return row[0]


def get_member_hierarchy_level(
    db: Session,
    server_id: int,
    user_id: int,
) -> int:
    """Return the maximum position of an active member's individual roles.

    The supplied ``user_id`` must identify the authenticated actor or a target
    whose use has already been authorized by the caller; it must not be taken
    as proof of the actor's identity from an untrusted request field. Ownership
    authority remains separate and is not converted into a hierarchy level.
    ``@everyone`` is not represented in these individual role assignments.
    """
    hierarchy = db.execute(
        select(ServerMember.id, func.max(ServerRole.position))
        .select_from(ServerMember)
        .outerjoin(
            ServerMemberRole,
            and_(
                ServerMemberRole.member_id == ServerMember.id,
                ServerMemberRole.server_id == ServerMember.server_id,
            ),
        )
        .outerjoin(
            ServerRole,
            and_(
                ServerRole.id == ServerMemberRole.role_id,
                ServerRole.server_id == ServerMemberRole.server_id,
            ),
        )
        .where(
            ServerMember.server_id == server_id,
            ServerMember.user_id == user_id,
            ServerMember.status == "ACTIVE",
        )
        .group_by(ServerMember.id)
    ).one_or_none()

    if hierarchy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )

    highest_position = hierarchy[1]
    return highest_position if highest_position is not None else 0


def is_hierarchy_comparison_approved(
    db: Session,
    server_id: int,
    actor_user_id: int,
    target_user_id: int,
) -> bool:
    """Check only whether the hierarchy gate permits actor to target.

    The actor ID must come from the authenticated principal, never from an
    untrusted client field. Both users must have ACTIVE membership in this
    server. A ``True`` result does not grant the operation's functional
    permission; callers must check that independently. Ownership is an
    operation-specific hierarchical exception, not a role position.
    """
    actor_level = get_member_hierarchy_level(db, server_id, actor_user_id)

    if actor_user_id == target_user_id:
        return False

    target_level = get_member_hierarchy_level(db, server_id, target_user_id)
    owner_id = db.scalar(
        select(Server.owner_id).where(Server.id == server_id)
    )

    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )

    if actor_user_id == owner_id:
        return True

    if target_user_id == owner_id:
        return False

    return actor_level > target_level


def resolve_server_permissions(
    db: Session,
    server_id: int,
    user_id: int,
) -> ResolvedServerPermissions:
    """Resolve explicit grants for an authenticated user's active membership.

    ``user_id`` must come from the authenticated principal (for example,
    ``current_user.id``), never from an untrusted request field. Hierarchy and
    channel-private access are deliberately outside this resolver.
    """
    server_and_membership = db.execute(
        select(Server, ServerMember).join(
            ServerMember,
            ServerMember.server_id == Server.id,
        ).where(
            Server.id == server_id,
            ServerMember.user_id == user_id,
            ServerMember.status == "ACTIVE",
        )
    ).one_or_none()

    if server_and_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado.",
        )

    server, membership = server_and_membership
    effective_permissions = _granted_permissions(server.everyone_permissions)

    role_permission_values = db.scalars(
        select(ServerRole.permissions)
        .join(
            ServerMemberRole,
            (ServerMemberRole.role_id == ServerRole.id)
            & (ServerMemberRole.server_id == ServerRole.server_id),
        )
        .where(
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.server_id == server.id,
            ServerRole.server_id == server.id,
        )
    ).all()

    for role_permissions in role_permission_values:
        effective_permissions.update(_granted_permissions(role_permissions))

    return ResolvedServerPermissions(
        server_id=server.id,
        user_id=user_id,
        membership_id=membership.id,
        is_owner=server.owner_id == user_id,
        permissions=frozenset(effective_permissions),
    )


def get_effective_server_permissions(
    db: Session,
    server_id: int,
    user_id: int,
) -> frozenset[str]:
    """Return the union of documented explicit grants for an active member."""
    return resolve_server_permissions(db, server_id, user_id).permissions


def get_server_authorization_context(
    db: Session,
    server_id: int,
    user_id: int,
) -> ServerAuthorizationContextResponse:
    """Expose the existing authorization resolution to the authenticated actor.

    Identity must come from the JWT principal. The result keeps ownership
    separate from role grants and reports the same maximum individual-role
    position used by hierarchy checks.
    """
    resolved = resolve_server_permissions(db, server_id, user_id)
    highest_position = get_member_hierarchy_level(db, server_id, user_id)
    return ServerAuthorizationContextResponse(
        server_id=resolved.server_id,
        user_id=resolved.user_id,
        is_owner=resolved.is_owner,
        highest_role_position=highest_position,
        effective_permissions=sorted(resolved.permissions),
        has_manage_roles_permission=has_server_permission(
            resolved, "manage_roles"
        ),
    )


def has_server_permission(
    resolved: ResolvedServerPermissions,
    permission: str,
) -> bool:
    """Check a known explicit grant; unknown permission names fail closed.

    Callers must apply operation-specific owner exceptions separately via
    ``resolved.is_owner``. This avoids turning ownership into a blanket grant.
    """
    return (
        permission in SERVER_PERMISSION_KEYS
        and permission in resolved.permissions
    )
