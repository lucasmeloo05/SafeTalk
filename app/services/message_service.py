
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
    MessageUserDeletion,
    User,
)


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


def send_message(
    db: Session,
    current_user: User,
    conversation_id: int,
    content: str,
) -> dict[str, Any]:
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada.",
        )

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

    try:
        # Every message writer must lock this conversation before assigning its
        # timestamp. This serializes sends only within the same conversation,
        # so a transaction that began earlier cannot commit behind an already
        # observed incremental cursor.
        conversation = db.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversa não encontrada.",
            )

        # Recheck authorization after taking the serialization lock because a
        # participant or block may have changed while this send was waiting.
        get_active_participant(db, conversation_id, current_user.id)
        check_direct_conversation_block(db, conversation, current_user.id)

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
            sender_id=current_user.id,
            content=content,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(message)
        db.flush()

        conversation.updated_at = message.created_at

        db.commit()
        db.refresh(message)

    except Exception:
        db.rollback()
        raise

    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "content": message.content,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "edited_at": message.edited_at,
        "is_deleted_for_everyone": False,
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
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada.",
        )

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
                "[Mensagem excluída]"
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
