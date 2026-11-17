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

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
