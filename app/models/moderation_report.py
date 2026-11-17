from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModerationReport(Base):
    __tablename__ = "moderation_reports"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_moderation_reports"),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_moderation_reports_reason_not_empty",
        ),
        UniqueConstraint(
            "reporter_id",
            "message_id",
            name="uq_moderation_reports_reporter_message",
        ),
        UniqueConstraint(
            "id",
            "message_id",
            name="uq_moderation_reports_id_message",
        ),
        Index(
            "ix_moderation_reports_status_created_at",
            "status",
            "created_at",
        ),
        Index(
            "ix_moderation_reports_reporter_created_at",
            "reporter_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_moderation_reports_reporter_users"),
        nullable=False,
    )

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", name="fk_moderation_reports_message_messages"),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        server_default="PENDING",
        nullable=False,
    )

    triage_status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        server_default="PENDING",
        nullable=False,
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
