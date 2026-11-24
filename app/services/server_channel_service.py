import json
from contextlib import contextmanager

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channel_schemas import ChannelCreate, ChannelResponse, ChannelUpdate, RoleId
from app.models import Conversation, Message, ServerConfigHistory, Server, ServerAuditLog, ServerChannel, ServerMember, ServerMemberRole, ServerRole
from app.models.server_channel import ServerChannelRole
from app.services.server_authorization_service import require_active_server_membership


def accessible_channels(server_id: int, user_id: int):
    """Authorize and read against the same PostgreSQL statement snapshot."""
    grant = select(ServerChannelRole.role_id).join(
        ServerMemberRole,
        (ServerMemberRole.role_id == ServerChannelRole.role_id)
        & (ServerMemberRole.server_id == ServerChannelRole.server_id),
    ).where(
        ServerChannelRole.channel_id == ServerChannel.id,
        ServerChannelRole.server_id == ServerChannel.server_id,
        ServerMemberRole.member_id == ServerMember.id,
    ).correlate(ServerChannel, ServerMember).exists()
    return select(ServerChannel).join(Server, Server.id == ServerChannel.server_id).join(
        ServerMember, ServerMember.server_id == Server.id
    ).where(
        Server.id == server_id, ServerChannel.is_archived.is_(False), ServerMember.user_id == user_id, ServerMember.status == "ACTIVE",
        or_(Server.owner_id == user_id, ServerChannel.is_private.is_(False), grant),
    ).execution_options(populate_existing=True)


def list_channels(db, server_id, user_id, limit, offset):
    require_active_server_membership(db, server_id, user_id)
    return db.scalars(accessible_channels(server_id, user_id).order_by(
        ServerChannel.position, ServerChannel.id
    ).limit(limit).offset(offset)).all()


def get_channel(db, server_id, channel_id, user_id):
    from app.age_policy import require_age
    require_age(db, server_id, user_id)
    channel = db.scalar(accessible_channels(server_id, user_id).where(ServerChannel.id == channel_id))
    if channel is None:
        raise HTTPException(404, "Canal não encontrado.")
    return channel


@contextmanager
def owner_transaction(db: Session, server_id: int, user_id: int):
    try:
        owner = db.scalar(select(Server.owner_id).where(Server.id == server_id).with_for_update())
        require_active_server_membership(db, server_id, user_id)
        if owner != user_id:
            raise HTTPException(403, "Somente o proprietário pode administrar canais.")
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_server_channels_server_name":
            raise HTTPException(409, "Já existe um canal com esse nome.") from exc
        raise
    except Exception:
        db.rollback()
        raise


def audit(db, channel, actor, event_type, role_id=None):
    db.add(ServerAuditLog(server_id=channel.server_id, actor_user_id=actor,
                          channel_id=channel.id, role_id=role_id, event_type=event_type))


def role_ids(db, channel):
    return set(db.scalars(select(ServerChannelRole.role_id).where(
        ServerChannelRole.channel_id == channel.id
    )))


_expected_grants = TypeAdapter(set[RoleId])


def check_expected_grants(header: str | None, current: set[int]) -> None:
    if header is None:
        raise HTTPException(428, "Informe X-Expected-Channel-Grants.")
    try:
        expected = _expected_grants.validate_json(header)
    except ValidationError as exc:
        raise HTTPException(422, "X-Expected-Channel-Grants deve ser uma lista JSON de IDs inteiros positivos.") from exc
    if expected != current:
        raise HTTPException(409, detail={"code": "channel_grants_conflict"})


def replace_grants(db, channel, actor, current, requested):
    if requested and not channel.is_private:
        raise HTTPException(422, "Canais públicos não aceitam restrições por cargo.")
    added = requested - current
    if added and set(db.scalars(select(ServerRole.id).where(
        ServerRole.server_id == channel.server_id, ServerRole.id.in_(added)
    ))) != added:
        raise HTTPException(404, "Cargo não encontrado neste servidor.")
    for role in sorted(added):
        db.add(ServerChannelRole(server_id=channel.server_id, channel_id=channel.id, role_id=role))
        audit(db, channel, actor, "CHANNEL_ROLE_ACCESS_GRANTED", role)
    removed = current - requested
    if removed:
        db.execute(delete(ServerChannelRole).where(
            ServerChannelRole.channel_id == channel.id, ServerChannelRole.role_id.in_(removed)
        ))
        for role in sorted(removed):
            audit(db, channel, actor, "CHANNEL_ROLE_ACCESS_REVOKED", role)


def create_channel(db, server_id, actor, payload: ChannelCreate):
    with owner_transaction(db, server_id, actor):
        channel = ServerChannel(server_id=server_id, **payload.model_dump(exclude={"authorized_role_ids"}))
        db.add(channel)
        db.flush()
        db.add(Conversation(type="CHANNEL", channel_id=channel.id, created_by=actor))
        replace_grants(db, channel, actor, set(), payload.authorized_role_ids)
        response = ChannelResponse.model_validate(channel)
    return response


def update_channel(db, server_id, channel_id, actor, payload: ChannelUpdate, expected_grants: str | None = None):
    with owner_transaction(db, server_id, actor):
        channel = get_channel(db, server_id, channel_id, actor)
        old_private = channel.is_private
        changes = payload.model_dump(exclude_unset=True)
        roles = changes.pop("authorized_role_ids", None)
        publishing = old_private and changes.get("is_private") is False
        if publishing and roles is None:
            roles = set()
        if roles is not None:
            current = role_ids(db, channel)
            check_expected_grants(expected_grants, current)
        if "is_read_only" in changes and changes["is_read_only"] != channel.is_read_only:
            db.add(ServerConfigHistory(server_id=server_id, changed_by=actor,
                setting_name=f"channel.{channel.id}.is_read_only", old_value=json.dumps(channel.is_read_only),
                new_value=json.dumps(changes["is_read_only"])))
        for field, value in changes.items():
            setattr(channel, field, value)
        if channel.is_private != old_private:
            audit(db, channel, actor, "CHANNEL_BECAME_PRIVATE" if channel.is_private else "CHANNEL_BECAME_PUBLIC")
        if roles is not None:
            replace_grants(db, channel, actor, current, roles)
        db.flush()
        response = ChannelResponse.model_validate(channel)
    return response


def delete_channel(db, server_id, channel_id, actor):
    with owner_transaction(db, server_id, actor):
        channel = get_channel(db, server_id, channel_id, actor)
        replace_grants(db, channel, actor, role_ids(db, channel), set())
        has_messages = db.scalar(select(Message.id).join(Conversation, Conversation.id == Message.conversation_id)
                                 .where(Conversation.channel_id == channel.id).limit(1))
        if has_messages is None:
            db.delete(channel)
        else:
            channel.is_archived = True


def change_role_access(db, server_id, channel_id, actor, role_id, *, grant):
    with owner_transaction(db, server_id, actor):
        channel = get_channel(db, server_id, channel_id, actor)
        if not channel.is_private:
            raise HTTPException(409, "O canal é público.")
        roles = role_ids(db, channel)
        if not grant and role_id not in roles:
            raise HTTPException(404, "Cargo não autorizado neste canal.")
        requested = roles | {role_id} if grant else roles - {role_id}
        replace_grants(db, channel, actor, roles, requested)


def list_authorized_roles(db, server_id, channel_id, actor):
    with owner_transaction(db, server_id, actor):
        return sorted(role_ids(db, get_channel(db, server_id, channel_id, actor)))
