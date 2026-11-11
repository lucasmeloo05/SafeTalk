
import re
from datetime import date

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=30,
    )
    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128,
    )
    birth_date: date

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_]+", value):
            raise ValueError(
                "O username pode conter apenas letras, números e _."
            )
        return value

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, value: date) -> date:
        today = date.today()

        if value > today:
            raise ValueError(
                "A data de nascimento não pode ser futura."
            )

        if value.year < 1900:
            raise ValueError(
                "A data de nascimento é inválida."
            )

        return value


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    birth_date: date | None = None
    is_active: bool
    is_verified: bool

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    login: str = Field(
        min_length=3,
        max_length=255,
    )
    password: str = Field(
        min_length=1,
        max_length=128,
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
