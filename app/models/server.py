
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Server(Base):
    __tablename__ = "servers"

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(everyone_permissions) = 'object'",
            name="ck_servers_everyone_permissions_object",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    is_adult: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    ai_moderation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    is_discoverable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    everyone_permissions: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
