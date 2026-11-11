
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPrivacySettings(Base):
    __tablename__ = "user_privacy_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        primary_key=True,
    )

    allow_messages_from_strangers: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    allow_friend_requests: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    show_online_status: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    allow_group_invites: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
