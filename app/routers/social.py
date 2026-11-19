from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    BlockedUser,
    FriendRequestCreate,
    FriendshipActionResponse,
    SocialUserPage,
)
from app.services import social_service


router = APIRouter(prefix="/social", tags=["Social"])


@router.get("/blocks", response_model=list[BlockedUser])
def list_blocks(current_user: Annotated[User, Depends(get_current_user)],
                db: Annotated[Session, Depends(get_db)],
                limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return social_service.list_blocks(db, current_user.id, limit, offset)


@router.put("/blocks/{user_id}", status_code=204)
def block_user(user_id: int, current_user: Annotated[User, Depends(get_current_user)],
               db: Annotated[Session, Depends(get_db)]):
    social_service.block_user(db, current_user.id, user_id)


@router.delete("/blocks/{user_id}", status_code=204)
def unblock_user(user_id: int, current_user: Annotated[User, Depends(get_current_user)],
                 db: Annotated[Session, Depends(get_db)]):
    social_service.unblock_user(db, current_user.id, user_id)


@router.get("/friends", response_model=SocialUserPage)
def list_friends(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return social_service.list_relationships(db, current_user.id, "friends", limit, offset)


@router.get("/requests/received", response_model=SocialUserPage)
def list_received_requests(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return social_service.list_relationships(db, current_user.id, "received", limit, offset)


@router.get("/requests/sent", response_model=SocialUserPage)
def list_sent_requests(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return social_service.list_relationships(db, current_user.id, "sent", limit, offset)


@router.post("/requests", response_model=FriendshipActionResponse, status_code=status.HTTP_201_CREATED)
def send_friend_request(
    payload: FriendRequestCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return social_service.create_friend_request(db, current_user.id, payload.recipient_id)


@router.post("/requests/{friendship_id}/accept", response_model=FriendshipActionResponse)
def accept_friend_request(
    friendship_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return social_service.respond_friend_request(db, current_user.id, friendship_id, "accept")


@router.post("/requests/{friendship_id}/reject", response_model=FriendshipActionResponse)
def reject_friend_request(
    friendship_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return social_service.respond_friend_request(db, current_user.id, friendship_id, "reject")


@router.delete("/requests/{friendship_id}", response_model=FriendshipActionResponse)
def cancel_friend_request(
    friendship_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return social_service.cancel_friend_request(db, current_user.id, friendship_id)


@router.delete("/friends/{user_id}", response_model=FriendshipActionResponse)
def remove_friend(
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return social_service.remove_friend(db, current_user.id, user_id)
