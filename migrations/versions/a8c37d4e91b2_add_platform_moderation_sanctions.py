"""Add platform moderation sanctions and review history.

Revision ID: a8c37d4e91b2
Revises: d7af10e95bc2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c37d4e91b2"
down_revision: Union[str, None] = "d7af10e95bc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "moderation_actions",
        sa.Column("decision_code", sa.String(length=30), nullable=True),
    )
    op.create_check_constraint(
        "ck_moderation_actions_valid_decision_code",
        "moderation_actions",
        "decision_code IS NULL OR decision_code IN "
        "('NO_VIOLATION', 'REVIEWED_MANUALLY', 'WARNING', "
        "'TEMPORARY_SUSPENSION', 'PERMANENT_BAN')",
    )
    op.create_unique_constraint(
        "uq_moderation_report_evidence_report_author",
        "moderation_report_evidence",
        ["report_id", "message_author_id"],
    )

    op.create_table(
        "moderation_sanctions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("source_action_id", sa.Integer(), nullable=False),
        sa.Column("sanction_type", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Integer(), nullable=True),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        sa.Column("requires_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_sanctions"),
        sa.UniqueConstraint("id", "report_id", name="uq_moderation_sanctions_id_report"),
        sa.UniqueConstraint("source_action_id", "sanction_type", name="uq_moderation_sanctions_action_type"),
        sa.ForeignKeyConstraint(
            ["report_id"], ["moderation_reports.id"],
            name="fk_moderation_sanctions_report", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "target_user_id"],
            ["moderation_report_evidence.report_id", "moderation_report_evidence.message_author_id"],
            name="fk_moderation_sanctions_target_report_evidence", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"], ["users.id"],
            name="fk_moderation_sanctions_target_user", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["platform_staff.user_id"],
            name="fk_moderation_sanctions_actor_staff", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_action_id"], ["moderation_actions.id"],
            name="fk_moderation_sanctions_source_action", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversed_by"], ["platform_staff.user_id"],
            name="fk_moderation_sanctions_reversed_by", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "sanction_type IN ('WARNING', 'TEMPORARY_SUSPENSION', 'PERMANENT_BAN')",
            name="ck_moderation_sanctions_valid_type",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_moderation_sanctions_reason_not_empty",
        ),
        sa.CheckConstraint(
            "(sanction_type = 'TEMPORARY_SUSPENSION' AND expires_at IS NOT NULL AND expires_at > issued_at) OR "
            "(sanction_type IN ('WARNING', 'PERMANENT_BAN') AND expires_at IS NULL)",
            name="ck_moderation_sanctions_expiration_shape",
        ),
        sa.CheckConstraint(
            "(reversed_at IS NULL AND reversed_by IS NULL AND reversal_reason IS NULL) OR "
            "(reversed_at IS NOT NULL AND reversed_by IS NOT NULL AND reversal_reason IS NOT NULL AND length(trim(reversal_reason)) > 0)",
            name="ck_moderation_sanctions_reversal_shape",
        ),
    )
    op.create_index(
        "ix_moderation_sanctions_target_type_issued",
        "moderation_sanctions",
        ["target_user_id", "sanction_type", "issued_at"],
    )
    op.create_index(
        "ix_moderation_sanctions_report_issued",
        "moderation_sanctions",
        ["report_id", "issued_at"],
    )

    op.create_table(
        "moderation_sanction_basis",
        sa.Column("derived_sanction_id", sa.Integer(), nullable=False),
        sa.Column("warning_sanction_id", sa.Integer(), nullable=False),
        sa.Column("derived_report_id", sa.Integer(), nullable=False),
        sa.Column("warning_report_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "derived_sanction_id", "warning_sanction_id",
            name="pk_moderation_sanction_basis",
        ),
        sa.ForeignKeyConstraint(
            ["derived_sanction_id", "derived_report_id"],
            ["moderation_sanctions.id", "moderation_sanctions.report_id"],
            name="fk_moderation_sanction_basis_derived", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warning_sanction_id", "warning_report_id"],
            ["moderation_sanctions.id", "moderation_sanctions.report_id"],
            name="fk_moderation_sanction_basis_warning", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "derived_sanction_id <> warning_sanction_id",
            name="ck_moderation_sanction_basis_distinct",
        ),
    )
    op.create_index(
        "ix_moderation_sanction_basis_warning",
        "moderation_sanction_basis",
        ["warning_sanction_id"],
    )

    op.create_table(
        "moderation_sanction_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sanction_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_sanction_reviews"),
        sa.ForeignKeyConstraint(
            ["sanction_id"], ["moderation_sanctions.id"],
            name="fk_moderation_sanction_reviews_sanction", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["platform_staff.user_id"],
            name="fk_moderation_sanction_reviews_actor", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "review_type IN ('REVIEW_REQUIRED', 'UPHELD', 'REVERSED')",
            name="ck_moderation_sanction_reviews_valid_type",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_moderation_sanction_reviews_reason_not_empty",
        ),
    )
    op.create_index(
        "ix_moderation_sanction_reviews_sanction_created",
        "moderation_sanction_reviews",
        ["sanction_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_sanction_reviews_sanction_created",
        table_name="moderation_sanction_reviews",
    )
    op.drop_table("moderation_sanction_reviews")
    op.drop_index(
        "ix_moderation_sanction_basis_warning",
        table_name="moderation_sanction_basis",
    )
    op.drop_table("moderation_sanction_basis")
    op.drop_index(
        "ix_moderation_sanctions_report_issued",
        table_name="moderation_sanctions",
    )
    op.drop_index(
        "ix_moderation_sanctions_target_type_issued",
        table_name="moderation_sanctions",
    )
    op.drop_table("moderation_sanctions")
    op.drop_constraint(
        "uq_moderation_report_evidence_report_author",
        "moderation_report_evidence",
        type_="unique",
    )
    op.drop_constraint(
        "ck_moderation_actions_valid_decision_code",
        "moderation_actions",
        type_="check",
    )
    op.drop_column("moderation_actions", "decision_code")
