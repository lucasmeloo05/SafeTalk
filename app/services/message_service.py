
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
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

    message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=content,
    )

    db.add(message)

    try:
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

    deleted_by_user = (
        select(MessageUserDeletion.id)
        .where(
            MessageUserDeletion.message_id == Message.id,
            MessageUserDeletion.user_id == current_user.id,
        )
        .exists()
    )

    messages = db.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            ~deleted_by_user,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()

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
