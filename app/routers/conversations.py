
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Conversation, ConversationParticipant, User
from app.schemas import (
    ConversationResponse,
    DirectConversationCreate,
)
from app.services.conversation_service import (
    create_or_get_direct_conversation,
)


router = APIRouter(
    prefix="/conversations",
    tags=["Conversas"],
)


@router.post(
    "/direct",
    response_model=ConversationResponse,
)
def create_direct_conversation(
    conversation_data: DirectConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return create_or_get_direct_conversation(
        db=db,
        current_user=current_user,
        recipient_id=conversation_data.recipient_id,
    )


@router.get(
    "/",
    response_model=list[ConversationResponse],
)
def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    conversations = db.scalars(
        select(Conversation)
        .join(
            ConversationParticipant,
            ConversationParticipant.conversation_id == Conversation.id,
        )
        .where(
            Conversation.type != "CHANNEL",
            ConversationParticipant.user_id == current_user.id,
            ConversationParticipant.status == "ACTIVE",
        )
        .order_by(Conversation.updated_at.desc())
    ).all()

    return conversations
