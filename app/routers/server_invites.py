from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    ServerInviteAccept,
    ServerInviteCreate,
    ServerInviteCreatedResponse,
    ServerInviteMembershipResponse,
    ServerInviteResponse,
)
from app.services.server_invite_service import (
    accept_server_invite,
    create_server_invite,
    list_server_invites,
    revoke_server_invite,
)


router = APIRouter(prefix="/servers", tags=["Convites de servidores"])


@router.post(
    "/{server_id}/invites",
    response_model=ServerInviteCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_server_invite_route(
    server_id: Annotated[int, Path(gt=0)],
    invite_data: ServerInviteCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ServerInviteCreatedResponse:
    invite, token = create_server_invite(
        db,
        server_id,
        current_user.id,
        expires_at=invite_data.expires_at,
        max_uses=invite_data.max_uses,
    )
    return ServerInviteCreatedResponse(
        id=invite.id,
        server_id=invite.server_id,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        max_uses=invite.max_uses,
        uses_count=invite.uses_count,
        revoked_at=invite.revoked_at,
        token=token,
    )


@router.post(
    "/{server_id}/invites/accept",
    response_model=ServerInviteMembershipResponse,
    status_code=status.HTTP_200_OK,
)
def accept_server_invite_route(
    server_id: Annotated[int, Path(gt=0)],
    invite_data: ServerInviteAccept,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ServerInviteMembershipResponse:
    membership = accept_server_invite(
        db,
        server_id,
        invite_data.token,
        current_user.id,
    )
    return ServerInviteMembershipResponse.model_validate(membership)


@router.get(
    "/{server_id}/invites",
    response_model=list[ServerInviteResponse],
)
def list_server_invites_route(
    server_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ServerInviteResponse]:
    return list_server_invites(
        db,
        server_id,
        current_user.id,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/{server_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_server_invite_route(
    server_id: Annotated[int, Path(gt=0)],
    invite_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    revoke_server_invite(db, server_id, invite_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
