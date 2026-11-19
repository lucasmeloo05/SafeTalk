
import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
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


class UserDiscoveryResponse(BaseModel):
    """Minimal profile fields safe to return in authenticated user search."""

    id: int
    username: str
    relationship_status: Literal[
        "NONE", "REQUEST_SENT", "REQUEST_RECEIVED", "FRIENDS"
    ]
    friendship_id: int | None = None


class UserDiscoveryPage(BaseModel):
    items: list[UserDiscoveryResponse]
    total: int
    limit: int
    offset: int


class BlockedUser(BaseModel):
    id: int
    username: str


class FriendRequestCreate(BaseModel):
    recipient_id: StrictInt = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class SocialUserItem(BaseModel):
    friendship_id: int
    user_id: int
    username: str
    created_at: datetime


class SocialUserPage(BaseModel):
    items: list[SocialUserItem]
    total: int
    limit: int
    offset: int


class FriendshipActionResponse(BaseModel):
    friendship_id: int
    user_id: int
    username: str
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "CANCELLED", "REMOVED"]
    created_at: datetime
    responded_at: datetime | None


class UserPrivacySettingsResponse(BaseModel):
    allow_messages_from_strangers: bool
    allow_friend_requests: bool


class UserPrivacySettingsUpdate(BaseModel):
    allow_messages_from_strangers: StrictBool | None = None
    allow_friend_requests: StrictBool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos uma configuração.")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError("As configurações não podem ser nulas.")
        return self


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


class MessageEditRequest(BaseModel):
    content: StrictStr = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A mensagem não pode ficar vazia.")
        if len(value) > 5000:
            raise ValueError("A mensagem não pode exceder 5.000 caracteres.")
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


class MessageUpdateEventItem(BaseModel):
    event_revision: int
    message_state_revision: int
    event_type: Literal["UPDATED", "DELETED"]
    message: MessageResponse


class MessageUpdateEventPage(BaseModel):
    items: list[MessageUpdateEventItem]
    updates_revision: int
    next_cursor: int
    has_more: bool


class MessageMutationResponse(BaseModel):
    message: MessageResponse
    message_state_revision: int


class MessageEditResponse(MessageMutationResponse):
    pass


class ModerationReportCreate(BaseModel):
    message_id: StrictInt = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O motivo da denúncia não pode estar vazio.")
        return value


class ModerationReportResponse(BaseModel):
    id: int
    message_id: int
    status: Literal["PENDING"]
    triage_status: Literal["PENDING"]
    analysis_status: Literal["PENDING_TRIAGE"] = "PENDING_TRIAGE"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModerationAnalysisSummary(BaseModel):
    status: str
    attempt_count: int
    model: str | None
    flagged: bool | None
    categories: dict[str, bool] | None
    category_scores: dict[str, float] | None
    category_applied_input_types: dict[str, list[str]] | None
    provider_response_id: str | None
    analyzed_at: datetime | None
    last_error_code: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModerationReportQueueItem(BaseModel):
    id: int
    message_id: int
    reason: str
    status: str
    triage_status: str
    analysis: ModerationAnalysisSummary
    created_at: datetime


class ModerationReportPage(BaseModel):
    items: list[ModerationReportQueueItem]
    page: int
    page_size: int
    total: int


class ModerationReportEvidenceResponse(BaseModel):
    message_id: int
    message_author_id: int
    content_snapshot: str
    message_created_at: datetime
    message_updated_at: datetime
    message_edited_at: datetime | None
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModerationActionResponse(BaseModel):
    id: int
    actor_user_id: int
    action_type: str
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModerationReportDetailResponse(BaseModel):
    id: int
    message_id: int
    reporter_id: int
    reason: str
    status: str
    triage_status: str
    created_at: datetime
    updated_at: datetime
    evidence: ModerationReportEvidenceResponse
    analysis: ModerationAnalysisSummary
    actions: list[ModerationActionResponse]


class ModerationReportTriage(BaseModel):
    """Human pre-submission gate; unsafe/suspected child exploitation stays manual.

    A positive value authorizes only the stored single-message snapshot for the
    moderation provider. It does not state that a model can reliably detect
    child sexual exploitation before sending.
    """

    external_analysis_eligible: StrictBool
    sensitive_content_suspected: StrictBool = False
    reason: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O motivo não pode estar vazio.")
        return value


class ModerationHumanDecision(BaseModel):
    decision: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("decision", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("O valor não pode estar vazio.")
        return value


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


class ServerInviteCreate(BaseModel):
    expires_at: datetime | None = None
    max_uses: StrictInt | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")


class ServerInviteAccept(BaseModel):
    token: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class ServerInviteCreatedResponse(BaseModel):
    id: int
    server_id: int
    created_at: datetime
    expires_at: datetime | None
    max_uses: int | None
    uses_count: int
    revoked_at: datetime | None
    token: str


class ServerInviteResponse(BaseModel):
    id: int
    server_id: int
    created_at: datetime
    expires_at: datetime | None
    max_uses: int | None
    uses_count: int
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ServerInviteMembershipResponse(BaseModel):
    server_id: int
    user_id: int
    status: Literal["ACTIVE", "LEFT"]
    joined_at: datetime
    left_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ServerModerationAction(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("O motivo não pode estar vazio.")
        return value


class ServerBanResponse(BaseModel):
    id: int
    server_id: int
    user_id: int
    banned_by: int
    banned_at: datetime
    reason: str | None
    is_active: bool
    revoked_at: datetime | None
    revoked_by: int | None

    model_config = ConfigDict(from_attributes=True)


class ServerAuditLogResponse(BaseModel):
    id: int
    server_id: int
    event_type: Literal[
        "MEMBER_KICKED", "MEMBER_BANNED", "MEMBER_UNBANNED"
    ]
    actor_user_id: int
    target_user_id: int
    occurred_at: datetime
    reason: str | None
    ban_id: int | None

    model_config = ConfigDict(from_attributes=True)


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


class ServerRoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    position: StrictInt | None = Field(default=None, ge=1)
    permissions: dict[ServerPermissionKey, StrictBool] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("O nome do cargo não pode estar vazio.")
        return value

    @model_validator(mode="after")
    def validate_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para atualização.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("O nome do cargo não pode ser nulo.")
        if "position" in self.model_fields_set and self.position is None:
            raise ValueError("A posição do cargo não pode ser nula.")
        if "permissions" in self.model_fields_set and self.permissions is None:
            raise ValueError("As permissões do cargo não podem ser nulas.")
        return self
