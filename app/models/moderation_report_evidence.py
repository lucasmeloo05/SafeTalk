from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModerationReportEvidence(Base):
    __tablename__ = "moderation_report_evidence"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_moderation_report_evidence"),
        UniqueConstraint("report_id", name="uq_moderation_report_evidence_report"),
        ForeignKeyConstraint(
            ["report_id", "message_id"],
            ["moderation_reports.id", "moderation_reports.message_id"],
            name="fk_moderation_report_evidence_report_message",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    report_id: Mapped[int] = mapped_column(Integer, nullable=False)

    message_id: Mapped[int] = mapped_column(Integer, nullable=False)

    message_author_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_moderation_report_evidence_author_users",
        ),
        nullable=False,
    )

    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)

    message_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    message_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    message_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
