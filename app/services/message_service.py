
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.models import (
    Block,
    Conversation,
    ConversationParticipant,
    Message,
    MessageEditHistory,
    MessageUserDeletion,
    MessageUpdateEvent,
    User,
)


DELETED_MESSAGE_PLACEHOLDER = "Esta mensagem foi excluída"


def lock_conversation_for_message_update(db: Session, conversation_id: int) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if conversation is None or conversation.type == "CHANNEL":
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return conversation


def lock_direct_conversation_users(db: Session, conversation_id: int) -> Conversation:
    """Serialize direct-message access with blocks using a stable lock order.

    Social block mutations take ``User FOR UPDATE`` in ascending ID order.
    Message operations take compatible ``User FOR KEY SHARE`` locks in that
    same order before any conversation/message lock. A committed block is
    therefore observed by later message operations, while an already-running
    operation completes before the block commits. Group conversations have no
    pairwise block rule and do not acquire user locks.
    """
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .execution_options(populate_existing=True)
    )
    if conversation is None or conversation.type == "CHANNEL":
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    if conversation.type == "DIRECT":
        if conversation.user_a_id is None or conversation.user_b_id is None:
            raise HTTPException(status_code=404, detail="Conversa não encontrada.")
        user_ids = sorted({conversation.user_a_id, conversation.user_b_id})
        locked_user_ids = db.scalars(
            select(User.id)
            .where(User.id.in_(user_ids))
            .order_by(User.id)
            .with_for_update(read=True, key_share=True)
        ).all()
        if len(locked_user_ids) != len(user_ids):
            raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    return conversation


def record_message_update_event(
    db: Session, conversation: Conversation, message: Message, event_type: str
) -> int:
    """Increment and persist the per-conversation event revision transactionally.

    Call only while holding the conversation row lock and in the same
    transaction as the associated message mutation.
    """
    if event_type not in {"UPDATED", "DELETED", "CREATED"}:
        raise ValueError("Tipo de evento de mensagem inválido.")
    conversation.messages_revision += 1
    event = MessageUpdateEvent(
        conversation_id=conversation.id,
        revision=conversation.messages_revision,
        message_id=message.id,
        event_type=event_type,
    )
    db.add(event)
    db.flush()
    return event.revision


def get_active_participant(
    db: Session,
    conversation_id: int,
    user_id: int,
) -> ConversationParticipant:
    participant = db.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
            ConversationParticipant.status == "ACTIVE",
        )
    )

    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não participa desta conversa.",
        )

    return participant


def check_direct_conversation_block(
    db: Session,
    conversation: Conversation,
    user_id: int,
) -> None:
    if conversation.type != "DIRECT":
        return

    other_user_id = (
        conversation.user_b_id
        if conversation.user_a_id == user_id
        else conversation.user_a_id
    )

    blocked = db.scalar(
        select(Block.id).where(
            or_(
                and_(
                    Block.blocker_id == user_id,
                    Block.blocked_id == other_user_id,
                ),
                and_(
                    Block.blocker_id == other_user_id,
                    Block.blocked_id == user_id,
                ),
            )
        )
    )

    if blocked is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Não é possível enviar mensagens nesta conversa.",
        )


def create_locked_message(db: Session, conversation: Conversation, sender_id: int, content: str) -> Message:
    conversation_id = conversation.id
    latest_created_at = db.scalar(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conversation_id
        )
    )
    created_at = db.scalar(select(func.clock_timestamp()))
    if created_at is None:
        raise RuntimeError("Não foi possível obter o horário do banco.")
    latest_activity_at = max(
        timestamp
        for timestamp in (
            conversation.created_at,
            conversation.updated_at,
            latest_created_at,
        )
        if timestamp is not None
    )
    if created_at <= latest_activity_at:
        created_at = latest_activity_at + timedelta(microseconds=1)

    message = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=content,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(message)
    db.flush()

    conversation.updated_at = message.created_at
    return message


def send_message(
    db: Session,
    current_user: User,
    conversation_id: int,
    content: str,
) -> dict[str, Any]:
    try:
        # Lock direct-conversation users before conversation/message rows,
        # matching the social block service's ascending user-ID order.
        conversation = lock_direct_conversation_users(db, conversation_id)
        conversation = lock_conversation_for_message_update(db, conversation_id)
        get_active_participant(db, conversation_id, current_user.id)
        check_direct_conversation_block(db, conversation, current_user.id)

        message = create_locked_message(db, conversation, current_user.id, content)
        db.commit()
    except Exception:
        db.rollback()
        raise

    # The conversation lock is released by commit. A concurrent DELETE may
    # finish before this read; serialize the row's refreshed persisted state so
    # this POST cannot return deleted content as an active message.
    db.refresh(message)
    return message_response_data(message)


def edit_locked_message(db: Session, conversation: Conversation, actor_id: int, message_id: int, normalized_content: str) -> dict:
    conversation_id = conversation.id
    message = db.scalar(
        select(Message)
        .where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensagem não encontrada nesta conversa.",
        )
    if message.sender_id != actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o autor pode editar esta mensagem.",
        )
    if message.deleted_for_everyone_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mensagens apagadas para todos não podem ser editadas.",
        )

    database_now = db.scalar(select(func.clock_timestamp()))
    if database_now is None:
        raise RuntimeError("Não foi possível obter o horário do banco.")
    if database_now > message.created_at + timedelta(minutes=15):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O prazo de 15 minutos para editar esta mensagem expirou.",
        )

    if normalized_content == message.content:
        current_message_revision = db.scalar(
            select(func.max(MessageUpdateEvent.revision)).where(
                MessageUpdateEvent.conversation_id == conversation_id,
                MessageUpdateEvent.message_id == message_id,
            )
        ) or 0
        result = {
            "message": message_response_data(message),
            "message_state_revision": current_message_revision,
        }
        return result

    previous_content = message.content
    edited_at = database_now
    expected_revision = conversation.messages_revision + 1

    # Add the immutable version before mutating the current row. Its
    # deferred FK is checked at commit after the update event is inserted.
    db.add(
        MessageEditHistory(
            message_id=message.id,
            conversation_id=conversation.id,
            previous_content=previous_content,
            new_content=normalized_content,
            edited_by_id=actor_id,
            edited_at=edited_at,
            message_state_revision=expected_revision,
        )
    )
    message.content = normalized_content
    message.updated_at = edited_at
    message.edited_at = edited_at
    conversation.updated_at = edited_at

    revision = record_message_update_event(db, conversation, message, "UPDATED")
    if revision != expected_revision:
        raise RuntimeError("A revisão da edição divergiu do evento registrado.")

    # Build the response while the transaction is still open. Once commit
    # succeeds, no refresh or other fallible database operation should turn
    # a persisted edit into an apparent request failure.
    result = {
        "message": message_response_data(message),
        "message_state_revision": revision,
    }
    return result


def edit_message(
    db: Session,
    current_user: User,
    conversation_id: int,
    message_id: int,
    content: str,
) -> dict[str, Any]:
    """Edit one authored message and persist its audit/event atomically."""
    normalized_content = content.strip()
    if not normalized_content or len(normalized_content) > 5000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A mensagem deve conter de 1 a 5.000 caracteres após a normalização.",
        )

    try:
        # Stable lock order: direct-conversation users, conversation, message.
        # The user locks coordinate authorization with social block mutations;
        # the conversation lock serializes revisions before the message lock.
        lock_direct_conversation_users(db, conversation_id)
        conversation = lock_conversation_for_message_update(db, conversation_id)
        get_active_participant(db, conversation_id, current_user.id)
        check_direct_conversation_block(db, conversation, current_user.id)

        result = edit_locked_message(db, conversation, current_user.id, message_id, normalized_content)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def delete_locked_message(db: Session, conversation: Conversation, actor_id: int, message_id: int) -> dict:
    conversation_id = conversation.id
    message = db.scalar(
        select(Message)
        .where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensagem não encontrada nesta conversa.",
        )
    if message.sender_id != actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente o autor pode excluir esta mensagem.",
        )
    if message.deleted_for_everyone_at is not None:
        revision = db.scalar(
            select(func.max(MessageUpdateEvent.revision)).where(
                MessageUpdateEvent.conversation_id == conversation_id,
                MessageUpdateEvent.message_id == message_id,
            )
        ) or 0
        result = {
            "message": message_response_data(message),
            "message_state_revision": revision,
        }
        return result

    deleted_at = db.scalar(select(func.clock_timestamp()))
    if deleted_at is None:
        raise RuntimeError("Não foi possível obter o horário do banco.")
    message.deleted_for_everyone_at = deleted_at
    message.deleted_for_everyone_by_id = actor_id
    message.updated_at = deleted_at
    conversation.updated_at = deleted_at

    revision = record_message_update_event(db, conversation, message, "DELETED")
    result = {
        "message": message_response_data(message),
        "message_state_revision": revision,
    }
    return result


def delete_message_for_everyone(
    db: Session,
    current_user: User,
    conversation_id: int,
    message_id: int,
) -> dict[str, Any]:
    """Soft-delete an authored message globally and publish one sync event."""
    try:
        # Keep the same user -> conversation -> message lock order as edits.
        # The conversation lock serializes delete/delete and edit/delete and
        # protects the per-conversation revision counter.
        lock_direct_conversation_users(db, conversation_id)
        conversation = lock_conversation_for_message_update(db, conversation_id)
        get_active_participant(db, conversation_id, current_user.id)
        check_direct_conversation_block(db, conversation, current_user.id)

        result = delete_locked_message(db, conversation, current_user.id, message_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def message_response_data(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "content": (
            DELETED_MESSAGE_PLACEHOLDER
            if message.deleted_for_everyone_at is not None
            else message.content
        ),
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "edited_at": message.edited_at,
        "is_deleted_for_everyone": message.deleted_for_everyone_at is not None,
    }


def list_messages(
    db: Session,
    current_user: User,
    conversation_id: int,
    limit: int = 50,
    offset: int = 0,
    *,
    latest: bool = False,
    after_created_at: datetime | None = None,
    after_id: int | None = None,
    before_created_at: datetime | None = None,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    conversation = lock_direct_conversation_users(db, conversation_id)

    get_active_participant(
        db,
        conversation_id,
        current_user.id,
    )

    check_direct_conversation_block(
        db,
        conversation,
        current_user.id,
    )

    has_after_cursor = after_created_at is not None or after_id is not None
    has_before_cursor = before_created_at is not None or before_id is not None
    if has_after_cursor and has_before_cursor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe somente um cursor de mensagens.",
        )
    if (has_after_cursor and (after_created_at is None or after_id is None)) or (
        has_before_cursor
        and (before_created_at is None or before_id is None)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O cursor exige data e ID da mensagem.",
        )
    if (has_after_cursor or has_before_cursor) and offset != 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Offset não pode ser combinado com cursor.",
        )
    if latest and (has_after_cursor or has_before_cursor or offset != 0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A janela recente não pode ser combinada com paginação.",
        )

    cursor_id = after_id if has_after_cursor else before_id
    if cursor_id == 0 and has_before_cursor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cursor de mensagens não encontrado nesta conversa.",
        )
    if cursor_id not in (None, 0):
        cursor_message_exists = db.scalar(
            select(Message.id).where(
                Message.id == cursor_id,
                Message.conversation_id == conversation_id,
            )
        )
        if cursor_message_exists is None:
            # Keep cursor errors indistinguishable from a cursor that does not
            # exist, and never use it to read rows outside this conversation.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cursor de mensagens não encontrado nesta conversa.",
            )

    deleted_by_user = (
        select(MessageUserDeletion.id)
        .where(
            MessageUserDeletion.message_id == Message.id,
            MessageUserDeletion.user_id == current_user.id,
        )
        .exists()
    )

    query = select(Message).where(
        Message.conversation_id == conversation_id,
        ~deleted_by_user,
    )

    if has_after_cursor:
        query = query.where(
            tuple_(Message.created_at, Message.id)
            > tuple_(after_created_at, after_id)
        ).order_by(Message.created_at.asc(), Message.id.asc())
        messages = db.scalars(query.limit(limit)).all()
    elif has_before_cursor:
        query = query.where(
            tuple_(Message.created_at, Message.id)
            < tuple_(before_created_at, before_id)
        ).order_by(Message.created_at.desc(), Message.id.desc())
        messages = list(reversed(db.scalars(query.limit(limit)).all()))
    elif latest:
        # Initial load: fetch the newest window, then return it in the same
        # chronological order as the legacy endpoint. The explicit flag keeps
        # the original offset behavior unchanged for existing clients.
        query = query.order_by(Message.created_at.desc(), Message.id.desc())
        messages = list(reversed(db.scalars(query.limit(limit)).all()))
    else:
        # Preserve the previous offset pagination contract for existing clients.
        query = query.order_by(Message.created_at.asc(), Message.id.asc())
        messages = db.scalars(query.limit(limit).offset(offset)).all()

    return [
        {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "sender_id": message.sender_id,
            "content": (
                DELETED_MESSAGE_PLACEHOLDER
                if message.deleted_for_everyone_at is not None
                else message.content
            ),
            "created_at": message.created_at,
            "updated_at": message.updated_at,
            "edited_at": message.edited_at,
            "is_deleted_for_everyone": (
                message.deleted_for_everyone_at is not None
            ),
        }
        for message in messages
    ]


def list_message_update_events(
    db: Session, current_user: User, conversation_id: int, after_revision: int, limit: int = 50
) -> dict[str, Any]:
    conversation = lock_direct_conversation_users(db, conversation_id)
    get_active_participant(db, conversation_id, current_user.id)
    check_direct_conversation_block(db, conversation, current_user.id)

    return read_update_events(db, conversation_id, after_revision, limit)


def read_update_events(db: Session, conversation_id: int, after_revision: int, limit: int) -> dict:
    event = MessageUpdateEvent
    state_revisions = (
        select(
            MessageUpdateEvent.conversation_id.label("conversation_id"),
            MessageUpdateEvent.message_id.label("message_id"),
            func.max(MessageUpdateEvent.revision).label("message_state_revision"),
        )
        .where(MessageUpdateEvent.conversation_id == conversation_id)
        .group_by(MessageUpdateEvent.conversation_id, MessageUpdateEvent.message_id)
        .subquery()
    )
    statement = (
        select(
            Conversation.messages_revision,
            event.revision,
            event.event_type,
            Message,
            state_revisions.c.message_state_revision,
        )
        .select_from(Conversation)
        .outerjoin(
            event,
            and_(
                event.conversation_id == Conversation.id,
                event.revision > after_revision,
            ),
        )
        .outerjoin(Message, and_(
            Message.id == event.message_id,
            Message.conversation_id == event.conversation_id,
        ))
        .outerjoin(state_revisions, and_(
            state_revisions.c.conversation_id == event.conversation_id,
            state_revisions.c.message_id == event.message_id,
        ))
        .where(Conversation.id == conversation_id)
        .order_by(event.revision.asc())
        .limit(limit + 1)
    )
    rows = db.execute(statement).all()
    watermark = rows[0][0]
    if after_revision > watermark:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O cursor de atualizações está acima da revisão da conversa.",
        )
    has_more = len(rows) > limit
    items = []
    for _, revision, event_type, message, state_revision in rows[:limit]:
        if revision is None or message is None:
            continue
        items.append({
            "event_revision": revision,
            "message_state_revision": state_revision,
            "event_type": event_type,
            "message": {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "sender_id": message.sender_id,
                "content": DELETED_MESSAGE_PLACEHOLDER if message.deleted_for_everyone_at else message.content,
                "created_at": message.created_at,
                "updated_at": message.updated_at,
                "edited_at": message.edited_at,
                "is_deleted_for_everyone": message.deleted_for_everyone_at is not None,
            },
        })
    next_cursor = items[-1]["event_revision"] if has_more else watermark
    return {
        "items": items,
        "updates_revision": watermark,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def load_latest_messages_with_revision(
    db: Session, current_user: User, conversation_id: int, limit: int = 50
) -> dict[str, Any]:
    conversation = lock_direct_conversation_users(db, conversation_id)
    get_active_participant(db, conversation_id, current_user.id)
    check_direct_conversation_block(db, conversation, current_user.id)
    deleted_by_user = select(MessageUserDeletion.id).where(
        MessageUserDeletion.message_id == Message.id,
        MessageUserDeletion.user_id == current_user.id,
    ).exists()
    latest = (
        select(Message)
        .where(Message.conversation_id == conversation_id, ~deleted_by_user)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .subquery()
    )
    statement = (
        select(
            Conversation.messages_revision,
            latest.c.id,
            latest.c.conversation_id,
            latest.c.sender_id,
            latest.c.content,
            latest.c.created_at,
            latest.c.updated_at,
            latest.c.edited_at,
            latest.c.deleted_for_everyone_at,
        )
        .select_from(Conversation)
        .outerjoin(latest, latest.c.conversation_id == Conversation.id)
        .where(Conversation.id == conversation_id)
        .order_by(latest.c.created_at.asc(), latest.c.id.asc())
    )
    rows = db.execute(statement).all()
    items = []
    for row in rows:
        if row.id is None:
            continue
        items.append({
            "id": row.id,
            "conversation_id": row.conversation_id,
            "sender_id": row.sender_id,
            "content": DELETED_MESSAGE_PLACEHOLDER if row.deleted_for_everyone_at else row.content,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "edited_at": row.edited_at,
            "is_deleted_for_everyone": row.deleted_for_everyone_at is not None,
        })
    return {"items": items, "updates_revision": rows[0][0]}
