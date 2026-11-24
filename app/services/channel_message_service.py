"""Channel membership is resolved for each request, never copied to private participants."""
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Conversation, Message, Server
from app.schemas import ModerationReportResponse
from app.services import message_service as messages
from app.services.moderation_report_service import _is_duplicate_report, stage_message_report
from app.services.server_channel_service import get_channel


@contextmanager
def channel_access(db: Session, server_id: int, channel_id: int, actor: int, *, mutate=False, publish=False):
    try:
        # Role, membership, ownership and channel administration take Server FOR UPDATE.
        owner_id = db.scalar(select(Server.owner_id).where(Server.id == server_id).with_for_update(read=True))
        channel = get_channel(db, server_id, channel_id, actor)
        can_publish = actor == owner_id or (channel.channel_type == "TEXT" and not channel.is_read_only)
        if publish and not can_publish:
            raise HTTPException(403, "Você pode consultar este canal, mas não publicar nele.")
        thread = db.scalars(select(Conversation).where(Conversation.channel_id == channel.id)
                            .with_for_update(read=not mutate).execution_options(populate_existing=True)).one()
        yield thread, can_publish
        if mutate:
            db.commit()
    except Exception:
        db.rollback()
        raise


def history(db, server_id, channel_id, actor, limit, before, after):
    with channel_access(db, server_id, channel_id, actor) as (thread, can_publish):
        query = select(Message).where(Message.conversation_id == thread.id)
        if before is not None and after is not None:
            raise HTTPException(422, "Use somente um cursor de histórico.")
        cursor = before if before is not None else after
        if cursor is not None and not db.scalar(query.with_only_columns(Message.id).where(Message.id == cursor)):
            raise HTTPException(404, "Cursor não encontrado neste canal.")
        if before is not None:
            query = query.where(Message.id < before)
        if after is not None:
            query = query.where(Message.id > after)
        order = Message.id.asc() if after is not None else Message.id.desc()
        rows = db.scalars(query.order_by(order).limit(limit + 1)).all()
        items = rows[:limit]
        if after is None:
            items.reverse()
        return dict(items=[messages.message_response_data(m) for m in items], has_more=len(rows) > limit,
                    updates_revision=thread.messages_revision, can_publish=can_publish)


def updates(db, server_id, channel_id, actor, after_revision, limit):
    with channel_access(db, server_id, channel_id, actor) as (thread, can_publish):
        return {**messages.read_update_events(db, thread.id, after_revision, limit), "can_publish": can_publish}


def send(db, server_id, channel_id, actor, content):
    with channel_access(db, server_id, channel_id, actor, mutate=True, publish=True) as (thread, _):
        message = messages.create_locked_message(db, thread, actor, content)
        revision = messages.record_message_update_event(db, thread, message, "CREATED")
        return dict(message=messages.message_response_data(message), message_state_revision=revision)


def edit(db, server_id, channel_id, actor, message_id, content):
    with channel_access(db, server_id, channel_id, actor, mutate=True, publish=True) as (thread, _):
        return messages.edit_locked_message(db, thread, actor, message_id, content)


def delete(db, server_id, channel_id, actor, message_id):
    with channel_access(db, server_id, channel_id, actor, mutate=True) as (thread, _):
        return messages.delete_locked_message(db, thread, actor, message_id)


def report(db, server_id, channel_id, actor, message_id, reason):
    try:
        with channel_access(db, server_id, channel_id, actor, mutate=True) as (thread, _):
            message = db.scalar(select(Message).where(Message.conversation_id == thread.id, Message.id == message_id))
            if message is None or message.deleted_for_everyone_at is not None:
                raise HTTPException(404, "Mensagem não disponível neste canal.")
            result = stage_message_report(db, message, actor, reason, server_id=server_id, channel_id=channel_id)
            db.flush()
            return ModerationReportResponse.model_validate(result)
    except IntegrityError as exc:
        if _is_duplicate_report(exc):
            raise HTTPException(409, "Você já denunciou esta mensagem.") from exc
        raise
