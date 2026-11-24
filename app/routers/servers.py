from app.server_age_dependency import require_server_age
from typing import Annotated

from fastapi import APIRouter, Header, Depends, Path, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    ServerCreate,
    ServerEveryonePermissionsResponse,
    ServerEveryonePermissionsUpdate,
    ServerOwnershipTransfer,
    ServerResponse,
    ServerUpdate,
)
from app.services.server_service import (
    create_server,
    get_server_for_active_member,
    list_active_servers,
    update_everyone_permissions,
    update_server,
    transfer_server_ownership,
)


router = APIRouter(prefix="/servers", tags=["Servidores"], dependencies=[Depends(require_server_age)])


@router.post(
    "/",
    response_model=ServerResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_server_route(
    server_data: ServerCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return create_server(db, current_user, server_data)


@router.get("/", response_model=list[ServerResponse])
def list_servers_route(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return list_active_servers(db, current_user)


@router.get("/{server_id}", response_model=ServerResponse)
def get_server_route(
    server_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return get_server_for_active_member(db, current_user, server_id)


@router.patch("/{server_id}", response_model=ServerResponse)
def update_server_route(
    server_id: int,
    server_data: ServerUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return update_server(db, current_user, server_id, server_data)


@router.post(
    "/{server_id}/transfer-ownership",
    response_model=ServerResponse,
    status_code=status.HTTP_200_OK,
)
def transfer_server_ownership_route(
    server_id: Annotated[int, Path(gt=0)],
    transfer_data: ServerOwnershipTransfer,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return transfer_server_ownership(
        db=db,
        server_id=server_id,
        actor_user_id=current_user.id,
        new_owner_id=transfer_data.new_owner_id,
    )


@router.patch(
    "/{server_id}/everyone-permissions",
    response_model=ServerEveryonePermissionsResponse,
)
def update_everyone_permissions_route(
    server_id: Annotated[int, Path(gt=0)],
    permissions_data: ServerEveryonePermissionsUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    expected_permissions: Annotated[str | None, Header(alias="X-Expected-Permissions")] = None,
):
    return update_everyone_permissions(
        db=db,
        current_user=current_user,
        server_id=server_id,
        permissions=permissions_data.root,
        expected_permissions=expected_permissions,
    )
