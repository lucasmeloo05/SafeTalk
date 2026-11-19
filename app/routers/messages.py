
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    MessageCreate,
    MessageEditRequest,
    MessageEditResponse,
    MessageMutationResponse,
    MessageResponse,
    MessageUpdateEventPage,
)
from app.services.message_service import (
    list_messages,
    send_message,
    list_message_update_events,
    load_latest_messages_with_revision,
    edit_message,
    delete_message_for_everyone,
)


router = APIRouter(
    prefix="/conversations",
    tags=["Mensagens"],
)


@router.get("/{conversation_id}/messages/sync")
def read_latest_messages_with_revision(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
):
    return load_latest_messages_with_revision(db, current_user, conversation_id, limit)


@router.get("/{conversation_id}/message-updates", response_model=MessageUpdateEventPage)
def read_message_updates(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    after_revision: Annotated[int, Query(ge=0)] = 0,
    limit: int = Query(default=50, ge=1, le=100),
):
    return list_message_update_events(db, current_user, conversation_id, after_revision, limit)


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


@router.patch(
    "/{conversation_id}/messages/{message_id}",
    response_model=MessageEditResponse,
)
def update_message(
    conversation_id: int,
    message_id: int,
    message_data: MessageEditRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return edit_message(
        db=db,
        current_user=current_user,
        conversation_id=conversation_id,
        message_id=message_id,
        content=message_data.content,
    )


@router.delete(
    "/{conversation_id}/messages/{message_id}",
    response_model=MessageMutationResponse,
)
def delete_message(
    conversation_id: int,
    message_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return delete_message_for_everyone(
        db=db,
        current_user=current_user,
        conversation_id=conversation_id,
        message_id=message_id,
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
