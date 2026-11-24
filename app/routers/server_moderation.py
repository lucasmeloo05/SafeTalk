from app.server_age_dependency import require_server_age
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    ServerAuditLogResponse,
    ServerBanResponse,
    ServerModerationAction,
)
from app.services.server_moderation_service import (
    ban_server_member,
    kick_server_member,
    list_server_audit_logs,
    list_server_bans,
    unban_server_member,
)


router = APIRouter(prefix="/servers", tags=["Moderação de servidores"], dependencies=[Depends(require_server_age)])


@router.post(
    "/{server_id}/members/{user_id}/kick",
    status_code=status.HTTP_204_NO_CONTENT,
)
def kick_server_member_route(
    server_id: Annotated[int, Path(gt=0)],
    user_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    action: ServerModerationAction | None = None,
) -> Response:
    kick_server_member(
        db,
        server_id,
        user_id,
        current_user.id,
        action.reason if action is not None else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{server_id}/members/{user_id}/ban",
    response_model=ServerBanResponse,
    status_code=status.HTTP_201_CREATED,
)
def ban_server_member_route(
    server_id: Annotated[int, Path(gt=0)],
    user_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    action: ServerModerationAction | None = None,
) -> ServerBanResponse:
    return ban_server_member(
        db,
        server_id,
        user_id,
        current_user.id,
        action.reason if action is not None else None,
    )


@router.get(
    "/{server_id}/bans",
    response_model=list[ServerBanResponse],
)
def list_server_bans_route(
    server_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return list_server_bans(
        db, server_id, current_user.id, limit=limit, offset=offset
    )


@router.post(
    "/{server_id}/bans/{ban_id}/unban",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unban_server_member_route(
    server_id: Annotated[int, Path(gt=0)],
    ban_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    action: ServerModerationAction | None = None,
) -> Response:
    unban_server_member(
        db,
        server_id,
        ban_id,
        current_user.id,
        action.reason if action is not None else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{server_id}/audit-logs",
    response_model=list[ServerAuditLogResponse],
)
def list_server_audit_logs_route(
    server_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_type: Literal[
        "MEMBER_KICKED",
        "MEMBER_BANNED",
        "MEMBER_UNBANNED",
        "OWNERSHIP_TRANSFERRED",
        "CHANNEL_ROLE_ACCESS_GRANTED",
        "CHANNEL_ROLE_ACCESS_REVOKED",
        "CHANNEL_BECAME_PRIVATE",
        "CHANNEL_BECAME_PUBLIC",
    ] | None = None,
    actor_user_id: Annotated[int | None, Query(gt=0)] = None,
    target_user_id: Annotated[int | None, Query(gt=0)] = None,
):
    return list_server_audit_logs(
        db,
        server_id,
        current_user.id,
        limit=limit,
        offset=offset,
        event_type=event_type,
        actor_user_id_filter=actor_user_id,
        target_user_id=target_user_id,
    )
