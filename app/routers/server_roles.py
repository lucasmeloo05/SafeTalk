from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import ServerRoleCreate, ServerRoleResponse, ServerRoleUpdate
from app.services.server_role_service import (
    assign_server_role_to_member,
    create_server_role,
    delete_server_role,
    get_server_role,
    list_server_roles,
    remove_server_role_from_member,
    update_server_role,
)


router = APIRouter(prefix="/servers", tags=["Cargos de servidores"])


@router.post(
    "/{server_id}/roles",
    response_model=ServerRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_server_role_route(
    server_id: Annotated[int, Path(gt=0)],
    role_data: ServerRoleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return create_server_role(
        db,
        server_id,
        current_user.id,
        role_data,
    )


@router.get(
    "/{server_id}/roles",
    response_model=list[ServerRoleResponse],
)
def list_server_roles_route(
    server_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return list_server_roles(db, current_user, server_id)


@router.get(
    "/{server_id}/roles/{role_id}",
    response_model=ServerRoleResponse,
)
def get_server_role_route(
    server_id: Annotated[int, Path(gt=0)],
    role_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return get_server_role(db, current_user, server_id, role_id)


@router.patch(
    "/{server_id}/roles/{role_id}",
    response_model=ServerRoleResponse,
    status_code=status.HTTP_200_OK,
)
def update_server_role_route(
    server_id: Annotated[int, Path(gt=0)],
    role_id: Annotated[int, Path(gt=0)],
    role_data: ServerRoleUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return update_server_role(
        db,
        server_id,
        role_id,
        current_user.id,
        role_data,
    )


@router.delete(
    "/{server_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_server_role_route(
    server_id: Annotated[int, Path(gt=0)],
    role_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_server_role(
        db,
        server_id,
        role_id,
        current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{server_id}/members/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def assign_server_role_to_member_route(
    server_id: Annotated[int, Path(gt=0)],
    user_id: Annotated[int, Path(gt=0)],
    role_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    assign_server_role_to_member(
        db,
        server_id,
        user_id,
        role_id,
        current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{server_id}/members/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_server_role_from_member_route(
    server_id: Annotated[int, Path(gt=0)],
    user_id: Annotated[int, Path(gt=0)],
    role_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    remove_server_role_from_member(
        db,
        server_id,
        user_id,
        role_id,
        current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
