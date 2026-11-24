from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerAuditLog,
    ServerBan,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)
from app.schemas import ServerBanResponse
from app.services.server_authorization_service import (
    get_member_hierarchy_level,
    has_server_permission,
    is_hierarchy_comparison_approved,
    resolve_server_permissions,
)


def _server_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Servidor não encontrado.",
    )


def _active_ban_conflict(error: IntegrityError) -> bool:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return (
        getattr(diagnostic, "constraint_name", None)
        == "uq_server_bans_one_active_per_user"
    )


def _lock_server(db: Session, server_id: int) -> Server:
    server = db.scalar(
        select(Server)
        .where(Server.id == server_id)
        .with_for_update()
    )
    if server is None:
        raise _server_not_found()
    return server


def _lock_memberships(
    db: Session,
    server_id: int,
    user_ids: set[int],
) -> dict[int, ServerMember]:
    """Lock participation rows in stable database-ID order after the server."""
    memberships = db.scalars(
        select(ServerMember)
        .where(
            ServerMember.server_id == server_id,
            ServerMember.user_id.in_(user_ids),
        )
        .order_by(ServerMember.id.asc())
        .with_for_update()
    ).all()
    return {membership.user_id: membership for membership in memberships}


def _require_active_actor(
    memberships: dict[int, ServerMember], actor_user_id: int
) -> ServerMember:
    actor = memberships.get(actor_user_id)
    if actor is None or actor.status != "ACTIVE":
        raise _server_not_found()
    return actor


def _require_active_target(
    memberships: dict[int, ServerMember], target_user_id: int
) -> ServerMember:
    target = memberships.get(target_user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membro não encontrado.",
        )
    if target.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A participação do membro já foi encerrada.",
        )
    return target


def _require_moderation_authority(
    db: Session,
    server: Server,
    actor_user_id: int,
    target_user_id: int,
    permission: str,
) -> None:
    resolved_actor = resolve_server_permissions(
        db, server.id, actor_user_id
    )
    if resolved_actor.is_owner:
        return

    if not has_server_permission(resolved_actor, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Você não possui a permissão {permission}.",
        )

    if not is_hierarchy_comparison_approved(
        db, server.id, actor_user_id, target_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sua hierarquia não permite esta ação sobre o membro.",
        )


def _validate_target_for_kick_or_ban(
    server: Server,
    actor_user_id: int,
    target_user_id: int,
    memberships: dict[int, ServerMember],
) -> ServerMember:
    _require_active_actor(memberships, actor_user_id)
    target = _require_active_target(memberships, target_user_id)

    if actor_user_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode executar esta ação contra si mesmo.",
        )
    if target_user_id == server.owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O proprietário não pode ser alvo desta ação.",
        )
    return target


def _lock_member_role_assignments(
    db: Session,
    server_id: int,
    member_id: int,
) -> list[tuple[ServerMemberRole, ServerRole]]:
    """Lock role assignment and role rows in deterministic order."""
    return list(
        db.execute(
            select(ServerMemberRole, ServerRole)
            .join(
                ServerRole,
                (ServerRole.id == ServerMemberRole.role_id)
                & (ServerRole.server_id == ServerMemberRole.server_id),
            )
            .where(
                ServerMemberRole.server_id == server_id,
                ServerMemberRole.member_id == member_id,
                ServerRole.server_id == server_id,
            )
            .order_by(ServerRole.id.asc(), ServerMemberRole.id.asc())
            .with_for_update(of=(ServerMemberRole, ServerRole))
        ).all()
    )


def _role_assignment_snapshot(
    assignments: list[tuple[ServerMemberRole, ServerRole]],
) -> list[dict[str, object]]:
    """Serialize role and assignment values before moderation cleanup."""
    snapshot: list[dict[str, object]] = []
    for assignment, role in assignments:
        snapshot.append(
            {
                "assignment": {
                    "id": assignment.id,
                    "server_id": assignment.server_id,
                    "member_id": assignment.member_id,
                    "role_id": assignment.role_id,
                    "assigned_at": assignment.assigned_at.isoformat(),
                    "assigned_by": assignment.assigned_by,
                },
                "role": {
                    "id": role.id,
                    "server_id": role.server_id,
                    "name": role.name,
                    "description": role.description,
                    "position": role.position,
                    "permissions": dict(role.permissions or {}),
                    "is_default": role.is_default,
                    "is_system_role": role.is_system_role,
                    "created_at": role.created_at.isoformat(),
                },
            }
        )
    return snapshot


def _end_membership_and_remove_roles(
    db: Session,
    server_id: int,
    membership: ServerMember,
) -> None:
    db.execute(
        delete(ServerMemberRole).where(
            ServerMemberRole.server_id == server_id,
            ServerMemberRole.member_id == membership.id,
        )
    )
    membership.status = "LEFT"
    membership.left_at = datetime.now(timezone.utc)


def _translate_moderation_error(
    db: Session,
    error: Exception,
    detail: str,
    *,
    active_ban_conflict: bool = False,
) -> None:
    db.rollback()
    if (
        active_ban_conflict
        and isinstance(error, IntegrityError)
        and _active_ban_conflict(error)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um banimento ativo para este membro.",
        ) from error
    if isinstance(error, HTTPException):
        raise error
    if isinstance(error, SQLAlchemyError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from error
    raise error


def kick_server_member(
    db: Session,
    server_id: int,
    target_user_id: int,
    actor_user_id: int,
    reason: str | None = None,
) -> ServerAuditLog:
    """Kick an active member and persist its audit event atomically."""
    try:
        server = _lock_server(db, server_id)
        user_ids = {actor_user_id, target_user_id}
        memberships = _lock_memberships(db, server_id, user_ids)
        target = _validate_target_for_kick_or_ban(
            server, actor_user_id, target_user_id, memberships
        )
        _require_moderation_authority(
            db, server, actor_user_id, target_user_id, "kick_members"
        )

        assignments = _lock_member_role_assignments(
            db, server_id, target.id
        )
        snapshot = _role_assignment_snapshot(assignments)

        _end_membership_and_remove_roles(db, server_id, target)
        audit = ServerAuditLog(
            server_id=server_id,
            event_type="MEMBER_KICKED",
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            reason=reason,
            ban_id=None,
            role_snapshot=snapshot,
        )
        db.add(audit)
        db.flush()
        db.commit()
        return audit
    except Exception as exc:
        _translate_moderation_error(
            db, exc, "Não foi possível expulsar o membro."
        )


def ban_server_member(
    db: Session,
    server_id: int,
    target_user_id: int,
    actor_user_id: int,
    reason: str | None = None,
) -> ServerBanResponse:
    """Ban an active member, snapshotting roles and auditing atomically."""
    try:
        server = _lock_server(db, server_id)
        user_ids = {actor_user_id, target_user_id}
        memberships = _lock_memberships(db, server_id, user_ids)
        target = _validate_target_for_kick_or_ban(
            server, actor_user_id, target_user_id, memberships
        )
        _require_moderation_authority(
            db, server, actor_user_id, target_user_id, "ban_members"
        )

        assignments = _lock_member_role_assignments(
            db, server_id, target.id
        )
        snapshot = _role_assignment_snapshot(assignments)
        target_highest_role_position = max(
            (role.position for _assignment, role in assignments),
            default=0,
        )

        # The ban cycle is the last row lock, after server, memberships, and
        # the target's assignments/roles. The partial unique index remains the
        # final defense against duplicate active cycles.
        existing_active_ban = db.scalar(
            select(ServerBan.id)
            .where(
                ServerBan.server_id == server_id,
                ServerBan.user_id == target_user_id,
                ServerBan.is_active.is_(True),
            )
            .with_for_update()
        )
        if existing_active_ban is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um banimento ativo para este membro.",
            )

        ban = ServerBan(
            server_id=server_id,
            user_id=target_user_id,
            banned_by=actor_user_id,
            reason=reason,
            is_active=True,
            target_highest_role_position=target_highest_role_position,
        )
        db.add(ban)
        db.flush()

        _end_membership_and_remove_roles(db, server_id, target)
        db.add(
            ServerAuditLog(
                server_id=server_id,
                event_type="MEMBER_BANNED",
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                reason=reason,
                ban_id=ban.id,
                role_snapshot=snapshot,
            )
        )
        db.flush()
        response = ServerBanResponse.model_validate(ban)
        db.commit()
        return response
    except Exception as exc:
        _translate_moderation_error(
            db,
            exc,
            "Não foi possível banir o membro.",
            active_ban_conflict=True,
        )


def unban_server_member(
    db: Session,
    server_id: int,
    ban_id: int,
    actor_user_id: int,
    reason: str | None = None,
) -> ServerBan:
    """Revoke one active ban without reactivating or restoring the member."""
    try:
        server = _lock_server(db, server_id)

        # Read the target ID without a row lock to establish the stable
        # participation lock set. The ban row itself is locked last below.
        ban_target_user_id = db.scalar(
            select(ServerBan.user_id).where(
                ServerBan.id == ban_id,
                ServerBan.server_id == server_id,
            )
        )
        if ban_target_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Banimento não encontrado.",
            )

        memberships = _lock_memberships(
            db, server_id, {actor_user_id, ban_target_user_id}
        )
        _require_active_actor(memberships, actor_user_id)
        if ban_target_user_id not in memberships:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membro do banimento não encontrado.",
            )

        # Preserve the common lock order even if inconsistent historical data
        # contains assignments for a banned (LEFT) member. They are not
        # restored or modified by unban.
        _lock_member_role_assignments(
            db, server_id, memberships[ban_target_user_id].id
        )

        ban = db.scalar(
            select(ServerBan)
            .where(
                ServerBan.id == ban_id,
                ServerBan.server_id == server_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if ban is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Banimento não encontrado.",
            )
        if not ban.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O banimento já foi revogado.",
            )

        resolved_actor = resolve_server_permissions(
            db, server_id, actor_user_id
        )
        if not resolved_actor.is_owner:
            if not has_server_permission(resolved_actor, "unban_members"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não possui a permissão unban_members.",
                )
            actor_level = get_member_hierarchy_level(
                db, server_id, actor_user_id
            )
            if actor_level <= ban.target_highest_role_position:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Sua hierarquia não é superior à registrada no "
                        "momento do banimento."
                    ),
                )

        revoked_at = datetime.now(timezone.utc)
        ban.is_active = False
        ban.revoked_at = revoked_at
        ban.revoked_by = actor_user_id
        db.add(
            ServerAuditLog(
                server_id=server_id,
                event_type="MEMBER_UNBANNED",
                actor_user_id=actor_user_id,
                target_user_id=ban.user_id,
                reason=reason,
                ban_id=ban.id,
                role_snapshot=None,
            )
        )
        db.flush()
        db.commit()
        return ban
    except Exception as exc:
        _translate_moderation_error(
            db, exc, "Não foi possível revogar o banimento."
        )


def list_server_bans(
    db: Session,
    server_id: int,
    actor_user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[ServerBan]:
    """List server ban cycles within the caller's approved visibility."""
    resolved_actor = resolve_server_permissions(db, server_id, actor_user_id)
    is_owner = resolved_actor.is_owner
    if not is_owner and not has_server_permission(
        resolved_actor, "unban_members"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode consultar os banimentos deste servidor.",
        )

    statement = select(ServerBan).where(ServerBan.server_id == server_id)
    if not is_owner:
        statement = statement.where(ServerBan.is_active.is_(True))
    return list(
        db.scalars(
            statement
            .order_by(ServerBan.banned_at.desc(), ServerBan.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )


def list_server_audit_logs(
    db: Session,
    server_id: int,
    actor_user_id: int,
    limit: int = 20,
    offset: int = 0,
    event_type: str | None = None,
    actor_user_id_filter: int | None = None,
    target_user_id: int | None = None,
) -> list[ServerAuditLog]:
    """List redacted audit events; full access is exclusive to the owner."""
    resolved_actor = resolve_server_permissions(db, server_id, actor_user_id)
    if not resolved_actor.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o proprietário pode consultar a auditoria.",
        )

    statement = select(ServerAuditLog).where(
        ServerAuditLog.server_id == server_id
    )
    if event_type is not None:
        statement = statement.where(ServerAuditLog.event_type == event_type)
    if actor_user_id_filter is not None:
        statement = statement.where(
            ServerAuditLog.actor_user_id == actor_user_id_filter
        )
    if target_user_id is not None:
        statement = statement.where(
            ServerAuditLog.target_user_id == target_user_id
        )
    return list(
        db.scalars(
            statement
            .order_by(
                ServerAuditLog.occurred_at.desc(),
                ServerAuditLog.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
