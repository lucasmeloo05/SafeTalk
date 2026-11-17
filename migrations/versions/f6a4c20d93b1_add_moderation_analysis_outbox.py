"""add durable moderation analysis outbox

Revision ID: f6a4c20d93b1
Revises: e3810d7bc42a
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a4c20d93b1"
down_revision: Union[str, Sequence[str], None] = "e3810d7bc42a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "moderation_analysis_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING_TRIAGE",
            nullable=False,
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=True),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "category_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "category_applied_input_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("provider_response_id", sa.String(length=100), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_TRIAGE', 'PENDING', 'PROCESSING', "
            "'COMPLETED', 'FAILED', 'MANUAL_REVIEW')",
            name="ck_moderation_analysis_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_moderation_analysis_jobs_attempt_count",
        ),
        sa.CheckConstraint(
            "(status = 'PROCESSING' AND claimed_at IS NOT NULL "
            "AND claim_token IS NOT NULL) OR "
            "(status <> 'PROCESSING' AND claimed_at IS NULL "
            "AND claim_token IS NULL)",
            name="ck_moderation_analysis_jobs_claim_consistency",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND model IS NOT NULL AND flagged IS NOT NULL "
            "AND categories IS NOT NULL AND category_scores IS NOT NULL "
            "AND analyzed_at IS NOT NULL) OR "
            "(status <> 'COMPLETED' AND model IS NULL AND flagged IS NULL "
            "AND categories IS NULL AND category_scores IS NULL "
            "AND analyzed_at IS NULL)",
            name="ck_moderation_analysis_jobs_result_consistency",
        ),
        sa.CheckConstraint(
            "categories IS NULL OR jsonb_typeof(categories) = 'object'",
            name="ck_moderation_analysis_jobs_categories_object",
        ),
        sa.CheckConstraint(
            "category_scores IS NULL OR jsonb_typeof(category_scores) = 'object'",
            name="ck_moderation_analysis_jobs_scores_object",
        ),
        sa.CheckConstraint(
            "category_applied_input_types IS NULL OR "
            "jsonb_typeof(category_applied_input_types) = 'object'",
            name="ck_moderation_analysis_jobs_input_types_object",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["moderation_reports.id"],
            name="fk_moderation_analysis_jobs_report_reports",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_analysis_jobs"),
        sa.UniqueConstraint(
            "report_id", name="uq_moderation_analysis_jobs_report"
        ),
    )
    # Preserve existing reports by giving each one a durable manual-triage
    # outbox record. Existing evidence and report data remain untouched.
    op.execute(
        sa.text(
            """
            INSERT INTO moderation_analysis_jobs (report_id)
            SELECT id FROM moderation_reports
            ON CONFLICT (report_id) DO NOTHING
            """
        )
    )
    op.create_index(
        "ix_moderation_analysis_jobs_pending",
        "moderation_analysis_jobs",
        ["available_at", "created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_moderation_analysis_jobs_stale_processing",
        "moderation_analysis_jobs",
        ["claimed_at"],
        postgresql_where=sa.text("status = 'PROCESSING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_analysis_jobs_stale_processing",
        table_name="moderation_analysis_jobs",
    )
    op.drop_index(
        "ix_moderation_analysis_jobs_pending",
        table_name="moderation_analysis_jobs",
    )
    op.drop_table("moderation_analysis_jobs")
