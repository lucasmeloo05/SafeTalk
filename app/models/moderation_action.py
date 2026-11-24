from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModerationAction(Base):
    """Persisted human review decisions; this model does not apply sanctions."""

    __tablename__ = "moderation_actions"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_moderation_actions"),
        CheckConstraint(
            "length(trim(action_type)) > 0",
            name="ck_moderation_actions_action_type_not_empty",
        ),
        CheckConstraint(
            "decision_code IS NULL OR decision_code IN "
            "('NO_VIOLATION', 'REVIEWED_MANUALLY', 'WARNING', "
            "'TEMPORARY_SUSPENSION', 'PERMANENT_BAN')",
            name="ck_moderation_actions_valid_decision_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    report_id: Mapped[int] = mapped_column(
        ForeignKey(
            "moderation_reports.id",
            name="fk_moderation_actions_report_reports",
        ),
        nullable=False,
        index=True,
    )

    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "platform_staff.user_id",
            name="fk_moderation_actions_actor_platform_staff",
        ),
        nullable=False,
        index=True,
    )

    action_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Null for triage/reversal audit events and legacy generic decisions.
    decision_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
