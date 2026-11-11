
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


class ConversationInvitation(Base):
    __tablename__ = "conversation_invitations"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED')",
            name="ck_conversation_invitations_valid_status",
        ),
        CheckConstraint(
            "invited_by <> invited_user_id",
            name="ck_conversation_invitations_no_self_invite",
        ),
        CheckConstraint(
            """
            (status = 'PENDING' AND responded_at IS NULL)
            OR
            (status <> 'PENDING' AND responded_at IS NOT NULL)
            """,
            name="ck_conversation_invitations_response_consistency",
        ),
        Index(
            "uq_conversation_invitations_pending",
            "conversation_id",
            "invited_user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
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

    invited_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    invited_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(15),
        default="PENDING",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
