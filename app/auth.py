
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.platform_staff import PlatformStaff
from app.settings import settings
from app.services.moderation_sanction_service import (
    account_restriction_exception,
    get_active_account_restriction,
)

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=["HS256"],
        )

        subject = payload.get("sub")

        if not isinstance(subject, str) or not subject.isdigit():
            raise credentials_exception

        user_id = int(subject)

    except InvalidTokenError:
        raise credentials_exception

    user = db.get(User, user_id)

    if user is None or not user.is_active:
        raise credentials_exception

    from app.models.two_factor import TwoFactor
    factor = db.get(TwoFactor, user.id)
    if factor and factor.session_version and payload.get("tfv") != factor.session_version:
        raise credentials_exception

    restriction = get_active_account_restriction(db, user.id)
    if restriction is not None:
        raise account_restriction_exception(restriction)

    return user


def resolve_current_platform_staff(
    db: Session,
    current_user: User,
) -> PlatformStaff:
    staff = db.get(PlatformStaff, current_user.id)
    if (
        staff is None
        or staff.status != "ACTIVE"
        or staff.revoked_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à equipe oficial da plataforma.",
        )
    return staff


def get_current_platform_staff(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlatformStaff:
    """Resolve an active official staff member from the authenticated user."""
    return resolve_current_platform_staff(db, current_user)


def require_platform_staff_roles(*allowed_roles: str):
    """Create a dependency restricted to active staff with the given roles."""
    valid_roles = {"ADMIN", "MODERATOR"}
    if any(role not in valid_roles for role in allowed_roles):
        raise ValueError("Papel oficial de plataforma inválido.")

    def dependency(
        staff: Annotated[
            PlatformStaff,
            Depends(get_current_platform_staff),
        ],
    ) -> PlatformStaff:
        if allowed_roles and staff.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu papel não permite esta operação.",
            )
        return staff

    return dependency
