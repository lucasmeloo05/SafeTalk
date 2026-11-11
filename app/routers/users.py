
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pwdlib import PasswordHash
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User, UserPrivacySettings
from app.schemas import TokenResponse, UserCreate, UserLogin, UserResponse
from app.settings import settings


router = APIRouter(prefix="/users", tags=["Usuários"])

password_hash = PasswordHash.recommended()


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
):
    existing_user = db.scalar(
        select(User).where(
            or_(
                User.username == user_data.username,
                User.email == str(user_data.email),
            )
        )
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username ou e-mail já cadastrado.",
        )

    user = User(
        username=user_data.username,
        email=str(user_data.email),
        password_hash=password_hash.hash(user_data.password),
        birth_date=user_data.birth_date,
    )

    try:
        db.add(user)
        db.flush()

        privacy_settings = UserPrivacySettings(
            user_id=user.id,
        )

        db.add(privacy_settings)

        db.commit()
        db.refresh(user)

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username ou e-mail já cadastrado.",
        )

    return user


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: UserLogin,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(
            or_(
                User.username == login_data.login,
                User.email == login_data.login,
            )
        )
    )

    if not user or not password_hash.verify(
        login_data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Esta conta está desativada.",
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)

    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": expires_at,
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )

    return {
        "access_token": token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserResponse)
def read_current_user(
    current_user: User = Depends(get_current_user),
):
    return current_user
