from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModerationAnalysisJob(Base):
    """Durable outbox and latest idempotent moderation result for a report."""

    __tablename__ = "moderation_analysis_jobs"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_moderation_analysis_jobs"),
        UniqueConstraint("report_id", name="uq_moderation_analysis_jobs_report"),
        CheckConstraint(
            "status IN ('PENDING_TRIAGE', 'PENDING', 'PROCESSING', "
            "'COMPLETED', 'FAILED', 'MANUAL_REVIEW')",
            name="ck_moderation_analysis_jobs_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_moderation_analysis_jobs_attempt_count",
        ),
        CheckConstraint(
            "(status = 'PROCESSING' AND claimed_at IS NOT NULL "
            "AND claim_token IS NOT NULL) OR "
            "(status <> 'PROCESSING' AND claimed_at IS NULL "
            "AND claim_token IS NULL)",
            name="ck_moderation_analysis_jobs_claim_consistency",
        ),
        CheckConstraint(
            "(status = 'COMPLETED' AND model IS NOT NULL AND flagged IS NOT NULL "
            "AND categories IS NOT NULL AND category_scores IS NOT NULL "
            "AND analyzed_at IS NOT NULL) OR "
            "(status <> 'COMPLETED' AND model IS NULL AND flagged IS NULL "
            "AND categories IS NULL AND category_scores IS NULL "
            "AND analyzed_at IS NULL)",
            name="ck_moderation_analysis_jobs_result_consistency",
        ),
        CheckConstraint(
            "categories IS NULL OR jsonb_typeof(categories) = 'object'",
            name="ck_moderation_analysis_jobs_categories_object",
        ),
        CheckConstraint(
            "category_scores IS NULL OR jsonb_typeof(category_scores) = 'object'",
            name="ck_moderation_analysis_jobs_scores_object",
        ),
        CheckConstraint(
            "category_applied_input_types IS NULL OR "
            "jsonb_typeof(category_applied_input_types) = 'object'",
            name="ck_moderation_analysis_jobs_input_types_object",
        ),
        Index(
            "ix_moderation_analysis_jobs_pending",
            "available_at",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "ix_moderation_analysis_jobs_stale_processing",
            "claimed_at",
            postgresql_where=text("status = 'PROCESSING'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    report_id: Mapped[int] = mapped_column(
        ForeignKey(
            "moderation_reports.id",
            name="fk_moderation_analysis_jobs_report_reports",
        ),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING_TRIAGE",
        server_default="PENDING_TRIAGE",
        nullable=False,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    claim_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    flagged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    categories: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    category_scores: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    category_applied_input_types: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    provider_response_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_error_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
