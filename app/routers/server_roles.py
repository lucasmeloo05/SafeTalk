from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import ServerRoleResponse
from app.services.server_role_service import get_server_role, list_server_roles


router = APIRouter(prefix="/servers", tags=["Cargos de servidores"])


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
