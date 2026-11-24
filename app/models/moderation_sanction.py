from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModerationSanction(Base):
    """Immutable sanction record with explicit reversible lifecycle metadata."""

    __tablename__ = "moderation_sanctions"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_moderation_sanctions"),
        UniqueConstraint(
            "id", "report_id", name="uq_moderation_sanctions_id_report"
        ),
        UniqueConstraint(
            "source_action_id",
            "sanction_type",
            name="uq_moderation_sanctions_action_type",
        ),
        ForeignKeyConstraint(
            ["report_id", "target_user_id"],
            ["moderation_report_evidence.report_id", "moderation_report_evidence.message_author_id"],
            name="fk_moderation_sanctions_target_report_evidence",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "sanction_type IN ('WARNING', 'TEMPORARY_SUSPENSION', 'PERMANENT_BAN')",
            name="ck_moderation_sanctions_valid_type",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_moderation_sanctions_reason_not_empty",
        ),
        CheckConstraint(
            "(sanction_type = 'TEMPORARY_SUSPENSION' AND expires_at IS NOT NULL AND expires_at > issued_at) OR "
            "(sanction_type IN ('WARNING', 'PERMANENT_BAN') AND expires_at IS NULL)",
            name="ck_moderation_sanctions_expiration_shape",
        ),
        CheckConstraint(
            "(reversed_at IS NULL AND reversed_by IS NULL AND reversal_reason IS NULL) OR "
            "(reversed_at IS NOT NULL AND reversed_by IS NOT NULL AND reversal_reason IS NOT NULL AND length(trim(reversal_reason)) > 0)",
            name="ck_moderation_sanctions_reversal_shape",
        ),
        Index(
            "ix_moderation_sanctions_target_type_issued",
            "target_user_id",
            "sanction_type",
            "issued_at",
        ),
        Index(
            "ix_moderation_sanctions_report_issued",
            "report_id",
            "issued_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("moderation_reports.id", name="fk_moderation_sanctions_report", ondelete="RESTRICT"),
        nullable=False,
    )
    target_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_moderation_sanctions_target_user", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("platform_staff.user_id", name="fk_moderation_sanctions_actor_staff", ondelete="RESTRICT"),
        nullable=False,
    )
    source_action_id: Mapped[int] = mapped_column(
        ForeignKey("moderation_actions.id", name="fk_moderation_sanctions_source_action", ondelete="RESTRICT"),
        nullable=False,
    )
    sanction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[int | None] = mapped_column(
        ForeignKey("platform_staff.user_id", name="fk_moderation_sanctions_reversed_by", ondelete="RESTRICT")
    )
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    requires_review: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )


class ModerationSanctionBasis(Base):
    """Warnings that caused a threshold suspension or permanent ban."""

    __tablename__ = "moderation_sanction_basis"
    __table_args__ = (
        PrimaryKeyConstraint(
            "derived_sanction_id", "warning_sanction_id",
            name="pk_moderation_sanction_basis",
        ),
        ForeignKeyConstraint(
            ["derived_sanction_id", "derived_report_id"],
            ["moderation_sanctions.id", "moderation_sanctions.report_id"],
            name="fk_moderation_sanction_basis_derived",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["warning_sanction_id", "warning_report_id"],
            ["moderation_sanctions.id", "moderation_sanctions.report_id"],
            name="fk_moderation_sanction_basis_warning",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "derived_sanction_id <> warning_sanction_id",
            name="ck_moderation_sanction_basis_distinct",
        ),
        Index("ix_moderation_sanction_basis_warning", "warning_sanction_id"),
    )

    derived_sanction_id: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_sanction_id: Mapped[int] = mapped_column(Integer, nullable=False)
    derived_report_id: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_report_id: Mapped[int] = mapped_column(Integer, nullable=False)


class ModerationSanctionReview(Base):
    """Append-only audit events for reversals and required derived-sanction review."""

    __tablename__ = "moderation_sanction_reviews"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_moderation_sanction_reviews"),
        CheckConstraint(
            "review_type IN ('REVIEW_REQUIRED', 'UPHELD', 'REVERSED')",
            name="ck_moderation_sanction_reviews_valid_type",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_moderation_sanction_reviews_reason_not_empty",
        ),
        Index(
            "ix_moderation_sanction_reviews_sanction_created",
            "sanction_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sanction_id: Mapped[int] = mapped_column(
        ForeignKey("moderation_sanctions.id", name="fk_moderation_sanction_reviews_sanction", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("platform_staff.user_id", name="fk_moderation_sanction_reviews_actor", ondelete="RESTRICT"),
        nullable=False,
    )
    review_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
