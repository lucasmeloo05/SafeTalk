
import re
from datetime import date, datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from app.server_permissions import ServerPermissionKey


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
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
            raise ValueError("A data de nascimento não pode ser futura.")

        if value.year < 1900:
            raise ValueError("A data de nascimento é inválida.")

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
    login: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DirectConversationCreate(BaseModel):
    recipient_id: int = Field(gt=0)


class ConversationResponse(BaseModel):
    id: int
    type: str
    user_a_id: int | None
    user_b_id: int | None
    name: str | None
    image_url: str | None
    created_by: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("A mensagem não pode estar vazia.")

        return value


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    content: str
    created_at: datetime
    updated_at: datetime
    edited_at: datetime | None
    is_deleted_for_everyone: bool = False

    model_config = ConfigDict(from_attributes=True)


class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O nome do servidor não pode estar vazio.")
        return value


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("O nome do servidor não pode estar vazio.")
        return value

    @model_validator(mode="after")
    def validate_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para atualização.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("O nome do servidor não pode ser nulo.")
        return self


class ServerEveryonePermissionsUpdate(
    RootModel[dict[ServerPermissionKey, StrictBool]]
):
    """Replacement configuration; only documented keys and JSON booleans."""


class ServerEveryonePermissionsResponse(BaseModel):
    server_id: int
    everyone_permissions: dict[ServerPermissionKey, StrictBool]


class ServerResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServerMemberResponse(BaseModel):
    user_id: int
    username: str
    joined_at: datetime


class ServerRoleResponse(BaseModel):
    id: int
    server_id: int
    name: str
    description: str | None
    permissions: dict[str, Any]
    position: int
    is_default: bool
    is_system_role: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServerRoleCreate(BaseModel):
    name: str = Field(max_length=50)
    description: str | None = Field(default=None, max_length=255)
    position: StrictInt = Field(ge=1)
    permissions: dict[ServerPermissionKey, StrictBool] = Field(
        default_factory=dict
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O nome do cargo não pode estar vazio.")
        return value
