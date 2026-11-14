from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    ServerCreate,
    ServerEveryonePermissionsResponse,
    ServerEveryonePermissionsUpdate,
    ServerResponse,
    ServerUpdate,
)
from app.services.server_service import (
    create_server,
    get_server_for_active_member,
    list_active_servers,
    update_everyone_permissions,
    update_server,
)


router = APIRouter(prefix="/servers", tags=["Servidores"])


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


@router.patch(
    "/{server_id}/everyone-permissions",
    response_model=ServerEveryonePermissionsResponse,
)
def update_everyone_permissions_route(
    server_id: Annotated[int, Path(gt=0)],
    permissions_data: ServerEveryonePermissionsUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return update_everyone_permissions(
        db=db,
        current_user=current_user,
        server_id=server_id,
        permissions=permissions_data.root,
    )
