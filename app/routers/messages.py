
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import MessageCreate, MessageResponse
from app.services.message_service import (
    list_messages,
    send_message,
)


router = APIRouter(
    prefix="/conversations",
    tags=["Mensagens"],
)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
)
def create_message(
    conversation_id: int,
    message_data: MessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return send_message(
        db=db,
        current_user=current_user,
        conversation_id=conversation_id,
        content=message_data.content,
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
def read_messages(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    latest: bool = Query(default=False),
    after_created_at: datetime | None = Query(default=None),
    after_id: Annotated[int | None, Query(ge=0)] = None,
    before_created_at: datetime | None = Query(default=None),
    before_id: Annotated[int | None, Query(ge=0)] = None,
):
    return list_messages(
        db=db,
        current_user=current_user,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
        latest=latest,
        after_created_at=after_created_at,
        after_id=after_id,
        before_created_at=before_created_at,
        before_id=before_id,
    )
