"""add private-message reports and official review records

Revision ID: a14c77b204fe
Revises: d8f4c2b19a70
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a14c77b204fe"
down_revision: Union[str, Sequence[str], None] = "d8f4c2b19a70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "moderation_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "triage_status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
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
            "length(trim(reason)) > 0",
            name="ck_moderation_reports_reason_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"], ["users.id"],
            name="fk_moderation_reports_reporter_users",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"],
            name="fk_moderation_reports_message_messages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_reports"),
        sa.UniqueConstraint(
            "reporter_id",
            "message_id",
            name="uq_moderation_reports_reporter_message",
        ),
        sa.UniqueConstraint(
            "id",
            "message_id",
            name="uq_moderation_reports_id_message",
        ),
    )
    op.create_index(
        "ix_moderation_reports_status_created_at",
        "moderation_reports",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_moderation_reports_reporter_created_at",
        "moderation_reports",
        ["reporter_id", "created_at"],
    )

    op.create_table(
        "moderation_report_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column("message_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "message_id"],
            ["moderation_reports.id", "moderation_reports.message_id"],
            name="fk_moderation_report_evidence_report_message",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_report_evidence"),
        sa.UniqueConstraint(
            "report_id",
            name="uq_moderation_report_evidence_report",
        ),
    )

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(action_type)) > 0",
            name="ck_moderation_actions_action_type_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["moderation_reports.id"],
            name="fk_moderation_actions_report_reports",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["platform_staff.user_id"],
            name="fk_moderation_actions_actor_platform_staff",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_actions"),
    )
    op.create_index(
        "ix_moderation_actions_report_id",
        "moderation_actions",
        ["report_id"],
    )
    op.create_index(
        "ix_moderation_actions_actor_user_id",
        "moderation_actions",
        ["actor_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_actions_actor_user_id",
        table_name="moderation_actions",
    )
    op.drop_index(
        "ix_moderation_actions_report_id",
        table_name="moderation_actions",
    )
    op.drop_table("moderation_actions")
    op.drop_table("moderation_report_evidence")
    op.drop_index(
        "ix_moderation_reports_reporter_created_at",
        table_name="moderation_reports",
    )
    op.drop_index(
        "ix_moderation_reports_status_created_at",
        table_name="moderation_reports",
    )
    op.drop_table("moderation_reports")
