from app.server_age_dependency import require_server_age
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.channel_schemas import ChannelCreate, ChannelResponse, ChannelUpdate
from app.channel_schemas import ChannelHistoryPage, ChannelReportRequest, ChannelUpdatesPage
from app.schemas import MessageEditRequest, MessageMutationResponse, ModerationReportResponse
from app.services import channel_message_service as chat
from app.database import get_db
from app.models import User
from app.services import server_channel_service as service

router = APIRouter(prefix="/servers/{server_id}/channels", tags=["Canais"], dependencies=[Depends(require_server_age)])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]
ID = Annotated[int, Path(gt=0)]


@router.get("", response_model=list[ChannelResponse])
def list_channels(server_id: ID, db: DB, actor: Actor, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  offset: Annotated[int, Query(ge=0)] = 0):
    return service.list_channels(db, server_id, actor.id, limit, offset)


@router.post("", response_model=ChannelResponse, status_code=201)
def create_channel(server_id: ID, payload: ChannelCreate, db: DB, actor: Actor):
    return service.create_channel(db, server_id, actor.id, payload)


@router.get("/{channel_id}", response_model=ChannelResponse)
def get_channel(server_id: ID, channel_id: ID, db: DB, actor: Actor):
    return service.get_channel(db, server_id, channel_id, actor.id)


@router.get("/{channel_id}/authorized-roles", response_model=list[int])
def list_authorized_roles(server_id: ID, channel_id: ID, db: DB, actor: Actor):
    return service.list_authorized_roles(db, server_id, channel_id, actor.id)


@router.put("/{channel_id}/roles/{role_id}", status_code=204)
def grant_access(server_id: ID, channel_id: ID, role_id: ID, db: DB, actor: Actor):
    service.change_role_access(db, server_id, channel_id, actor.id, role_id, grant=True)
    return Response(status_code=204)


@router.delete("/{channel_id}/roles/{role_id}", status_code=204)
def revoke_access(server_id: ID, channel_id: ID, role_id: ID, db: DB, actor: Actor):
    service.change_role_access(db, server_id, channel_id, actor.id, role_id, grant=False)
    return Response(status_code=204)


@router.patch("/{channel_id}", response_model=ChannelResponse)
def update_channel(
    server_id: ID, channel_id: ID, payload: ChannelUpdate, db: DB, actor: Actor,
    expected_grants: Annotated[str | None, Header(
        alias="X-Expected-Channel-Grants",
        description="Lista JSON de IDs observados antes de substituir grants ou publicar um canal privado.",
    )] = None,
):
    return service.update_channel(db, server_id, channel_id, actor.id, payload, expected_grants)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(server_id: ID, channel_id: ID, db: DB, actor: Actor):
    service.delete_channel(db, server_id, channel_id, actor.id)
    return Response(status_code=204)


PageLimit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[int | None, Query(gt=0)]


@router.get("/{channel_id}/messages", response_model=ChannelHistoryPage)
def channel_history(server_id: ID, channel_id: ID, db: DB, actor: Actor, limit: PageLimit = 50,
                    before_id: Cursor = None, after_id: Cursor = None):
    return chat.history(db, server_id, channel_id, actor.id, limit, before_id, after_id)


@router.get("/{channel_id}/message-updates", response_model=ChannelUpdatesPage)
def channel_updates(server_id: ID, channel_id: ID, db: DB, actor: Actor,
                    after_revision: Annotated[int, Query(ge=0)] = 0, limit: PageLimit = 50):
    return chat.updates(db, server_id, channel_id, actor.id, after_revision, limit)


@router.post("/{channel_id}/messages", response_model=MessageMutationResponse, status_code=201)
def send_message(server_id: ID, channel_id: ID, data: MessageEditRequest, db: DB, actor: Actor):
    return chat.send(db, server_id, channel_id, actor.id, data.content)


@router.patch("/{channel_id}/messages/{message_id}", response_model=MessageMutationResponse)
def edit_message(server_id: ID, channel_id: ID, message_id: ID, data: MessageEditRequest, db: DB, actor: Actor):
    return chat.edit(db, server_id, channel_id, actor.id, message_id, data.content)


@router.delete("/{channel_id}/messages/{message_id}", response_model=MessageMutationResponse)
def delete_message(server_id: ID, channel_id: ID, message_id: ID, db: DB, actor: Actor):
    return chat.delete(db, server_id, channel_id, actor.id, message_id)


@router.post("/{channel_id}/messages/{message_id}/reports", response_model=ModerationReportResponse, status_code=201)
def report_message(server_id: ID, channel_id: ID, message_id: ID, data: ChannelReportRequest, db: DB, actor: Actor):
    return chat.report(db, server_id, channel_id, actor.id, message_id, data.reason)
