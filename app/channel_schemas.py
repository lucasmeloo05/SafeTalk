from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints, model_validator

from app.schemas import MessageResponse


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, Field(max_length=255)]
Position = Annotated[StrictInt, Field(ge=0)]
RoleId = Annotated[StrictInt, Field(gt=0)]
ChannelType = Literal["TEXT", "VOICE"]


class ChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Description | None = None
    position: Position = 0
    channel_type: ChannelType = "TEXT"
    is_read_only: StrictBool = False
    is_private: StrictBool = False
    authorized_role_ids: set[RoleId] = Field(default_factory=set)


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    description: Description | None = None
    position: Position | None = None
    channel_type: ChannelType | None = None
    is_read_only: StrictBool | None = None
    is_private: StrictBool | None = None
    authorized_role_ids: set[RoleId] | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set - {"description"}
        ):
            raise ValueError("Informe campos válidos para atualizar o canal.")
        return self


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    server_id: int
    name: str
    description: str | None
    position: int
    channel_type: ChannelType
    is_read_only: bool
    is_private: bool
    created_at: datetime


class ChannelHistoryPage(BaseModel):
    items: list[MessageResponse]
    has_more: bool
    updates_revision: int
    can_publish: bool


class ChannelEvent(BaseModel):
    event_revision: int
    message_state_revision: int
    event_type: Literal["CREATED", "UPDATED", "DELETED"]
    message: MessageResponse


class ChannelUpdatesPage(BaseModel):
    items: list[ChannelEvent]
    has_more: bool
    updates_revision: int
    next_cursor: int
    can_publish: bool


class ChannelReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
