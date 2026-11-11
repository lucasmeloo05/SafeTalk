
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"

    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'MEMBER')",
            name="ck_conversation_participants_valid_role",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'LEFT')",
            name="ck_conversation_participants_valid_status",
        ),
        CheckConstraint(
            """
            (status = 'ACTIVE' AND left_at IS NULL)
            OR
            (status = 'LEFT' AND left_at IS NOT NULL)
            """,
            name="ck_conversation_participants_status_left_at",
        ),
        Index(
            "uq_conversation_participants_active",
            "conversation_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(10),
        default="MEMBER",
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(10),
        default="ACTIVE",
        nullable=False,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
