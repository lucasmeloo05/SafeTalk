from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import ServerMemberResponse
from app.services.server_member_service import (
    get_active_server_member,
    leave_server,
    list_active_server_members,
)


router = APIRouter(prefix="/servers", tags=["Membros de servidores"])


@router.get(
    "/{server_id}/members",
    response_model=list[ServerMemberResponse],
)
def list_server_members_route(
    server_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_active_server_members(
        db=db,
        current_user=current_user,
        server_id=server_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{server_id}/members/{user_id}",
    response_model=ServerMemberResponse,
)
def get_server_member_route(
    server_id: Annotated[int, Path(gt=0)],
    user_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return get_active_server_member(
        db=db,
        current_user=current_user,
        server_id=server_id,
        user_id=user_id,
    )


@router.post(
    "/{server_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
)
def leave_server_route(
    server_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    leave_server(db=db, current_user=current_user, server_id=server_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
