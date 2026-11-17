import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerBan,
    ServerInvite,
    ServerMember,
    ServerMemberRole,
)
from app.services.server_authorization_service import (
    has_server_permission,
    resolve_server_permissions,
)


_INVITE_TOKEN_BYTES = 32


def hash_server_invite_token(token: str) -> str:
    """Return the SHA-256 digest used for persistence and future lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_server_invite_token(token: str, stored_hash: str) -> bool:
    """Compare a presented token with a stored digest in constant time."""
    candidate_hash = hash_server_invite_token(token)
    return hmac.compare_digest(candidate_hash, stored_hash)


def _validate_invite_options(
    expires_at: datetime | None,
    max_uses: int | None,
) -> None:
    if expires_at is not None:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A expiração deve incluir fuso horário.",
            )
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A expiração deve estar no futuro.",
            )
    if max_uses is not None and (
        type(max_uses) is not int or max_uses <= 0
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O limite de usos deve ser um inteiro positivo.",
        )


def _lock_invite_authority(
    db: Session,
    server_id: int,
    actor_user_id: int,
) -> Server:
    """Lock server then actor membership before resolving invite authority."""
    server = db.scalar(
        select(Server).where(Server.id == server_id).with_for_update()
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
    if not resolved.is_owner and not has_server_permission(
        resolved, "manage_invites"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode gerenciar convites deste servidor.",
        )
    return server


def create_server_invite(
    db: Session,
    server_id: int,
    actor_user_id: int,
    *,
    expires_at: datetime | None = None,
    max_uses: int | None = None,
) -> tuple[ServerInvite, str]:
    """Create an invite and return its raw token exactly once to the caller.

    ``actor_user_id`` must come from the authenticated principal. Only the
    SHA-256 digest is persisted; do not log the returned token.
    """
    _validate_invite_options(expires_at, max_uses)
    try:
        server = _lock_invite_authority(db, server_id, actor_user_id)
        token = secrets.token_urlsafe(_INVITE_TOKEN_BYTES)
        invite = ServerInvite(
            server_id=server.id,
            created_by=actor_user_id,
            token_hash=hash_server_invite_token(token),
            expires_at=expires_at,
            max_uses=max_uses,
            uses_count=0,
            revoked_at=None,
        )
        db.add(invite)
        db.flush()
        db.refresh(invite)
        db.commit()
        return invite, token
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o convite.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o convite.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def revoke_server_invite(
    db: Session,
    server_id: int,
    invite_id: int,
    actor_user_id: int,
) -> ServerInvite:
    """Revoke an invite belonging to the server in one transaction."""
    try:
        _lock_invite_authority(db, server_id, actor_user_id)
        invite = db.scalar(
            select(ServerInvite)
            .where(
                ServerInvite.id == invite_id,
                ServerInvite.server_id == server_id,
            )
            .with_for_update()
        )
        if invite is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Convite não encontrado.",
            )
        if invite.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O convite já foi revogado.",
            )

        invite.revoked_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
        return invite
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível revogar o convite.",
        ) from exc
    except Exception:
        db.rollback()
        raise


def list_server_invites(
    db: Session,
    server_id: int,
    actor_user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[ServerInvite]:
    """List invite metadata for an authorized active server member."""
    _lock_invite_authority(db, server_id, actor_user_id)
    return list(
        db.scalars(
            select(ServerInvite)
            .where(ServerInvite.server_id == server_id)
            .order_by(ServerInvite.created_at.desc(), ServerInvite.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )


def accept_server_invite(
    db: Session,
    server_id: int,
    token: str,
    user_id: int,
) -> ServerMember:
    """Consume a valid invite and create/reactivate membership atomically.

    ``user_id`` must come from the authenticated principal. The lock order is
    server, invite, membership, role assignments, then active ban cycle. This
    shares the server-first serialization point used by leave and moderation.
    """
    if not isinstance(token, str) or not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Convite não encontrado ou inválido.",
        )

    token_hash = hash_server_invite_token(token)
    try:
        server = db.scalar(
            select(Server).where(Server.id == server_id).with_for_update()
        )
        if server is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Servidor não encontrado.",
            )

        invite = db.scalar(
            select(ServerInvite)
            .where(
                ServerInvite.server_id == server_id,
                ServerInvite.token_hash == token_hash,
            )
            .with_for_update()
        )
        if invite is None or not verify_server_invite_token(
            token, invite.token_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Convite não encontrado ou inválido.",
            )

        now = datetime.now(timezone.utc)
        if invite.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O convite foi revogado.",
            )
        if invite.expires_at is not None and invite.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O convite expirou.",
            )
        if (
            invite.max_uses is not None
            and invite.uses_count >= invite.max_uses
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O convite esgotou o limite de usos.",
            )

        membership = db.scalar(
            select(ServerMember)
            .where(
                ServerMember.server_id == server_id,
                ServerMember.user_id == user_id,
            )
            .with_for_update()
        )
        if membership is not None and membership.status == "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O usuário já participa deste servidor.",
            )

        role_assignment_ids: list[int] = []
        if membership is not None:
            # Ordinarily leave/kick/ban already removed these rows. Lock and
            # clear any residual assignments so reactivation never restores
            # prior individual roles, even if legacy/inconsistent data exists.
            role_assignment_ids = list(
                db.scalars(
                    select(ServerMemberRole.id)
                    .where(
                        ServerMemberRole.server_id == server_id,
                        ServerMemberRole.member_id == membership.id,
                    )
                    .order_by(ServerMemberRole.id.asc())
                    .with_for_update()
                ).all()
            )

        # Ban service takes the same server lock first and locks its cycle
        # after participation/role rows. The server lock serializes this check
        # against a concurrent ban and avoids consuming a use after a ban.
        active_ban = db.scalar(
            select(ServerBan.id)
            .where(
                ServerBan.server_id == server_id,
                ServerBan.user_id == user_id,
                ServerBan.is_active.is_(True),
            )
            .with_for_update()
        )
        if active_ban is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Um banimento ativo impede a entrada neste servidor.",
            )

        if membership is None:
            membership = ServerMember(
                server_id=server_id,
                user_id=user_id,
                status="ACTIVE",
                joined_at=now,
                left_at=None,
            )
            db.add(membership)
        else:
            if role_assignment_ids:
                db.execute(
                    delete(ServerMemberRole).where(
                        ServerMemberRole.id.in_(role_assignment_ids)
                    )
                )
            membership.status = "ACTIVE"
            membership.left_at = None
            membership.joined_at = now

        # Flush membership/cleanup first; use consumption remains in the same
        # transaction and is rolled back if either write fails.
        db.flush()
        invite.uses_count += 1
        db.flush()
        db.refresh(membership)
        db.commit()
        return membership
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível aceitar o convite.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível aceitar o convite.",
        ) from exc
    except Exception:
        db.rollback()
        raise
