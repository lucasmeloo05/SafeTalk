
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    CheckConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    __table_args__ = (
        CheckConstraint(
            """
            (
                type = 'DIRECT'
                AND user_a_id IS NOT NULL
                AND user_b_id IS NOT NULL
                AND user_a_id < user_b_id
                AND created_by IN (user_a_id, user_b_id)
            )
            OR
            (
                type IN ('GROUP', 'CHANNEL')
                AND user_a_id IS NULL
                AND user_b_id IS NULL
            )
            """,
            name="ck_conversations_valid_type_and_users",
        ),
        CheckConstraint(
            "type IN ('DIRECT', 'GROUP', 'CHANNEL')",
            name="ck_conversations_valid_type",
        ),
        CheckConstraint("(type = 'CHANNEL') = (channel_id IS NOT NULL)", name="ck_conversations_channel_scope"),
        UniqueConstraint("channel_id", name="uq_conversations_channel"),
        UniqueConstraint(
            "user_a_id",
            "user_b_id",
            name="uq_conversations_direct_pair",
        ),
        CheckConstraint("messages_revision >= 0", name="ck_conversations_messages_revision_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    channel_id: Mapped[int | None] = mapped_column(ForeignKey("server_channels.id", ondelete="CASCADE"))

    user_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    user_b_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    image_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
