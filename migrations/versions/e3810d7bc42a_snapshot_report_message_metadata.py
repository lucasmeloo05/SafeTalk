"""preserve author and timestamps in moderation evidence

Revision ID: e3810d7bc42a
Revises: a14c77b204fe
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3810d7bc42a"
down_revision: Union[str, Sequence[str], None] = "a14c77b204fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "moderation_report_evidence",
        sa.Column("message_author_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "moderation_report_evidence",
        sa.Column(
            "message_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "moderation_report_evidence",
        sa.Column(
            "message_edited_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Existing evidence rows are backfilled from their still-referenced source
    # messages. Existing content_snapshot and message_created_at are untouched.
    op.execute(
        sa.text(
            """
            UPDATE moderation_report_evidence AS evidence
            SET message_author_id = messages.sender_id,
                message_updated_at = messages.updated_at,
                message_edited_at = messages.edited_at
            FROM messages
            WHERE messages.id = evidence.message_id
            """
        )
    )

    op.alter_column(
        "moderation_report_evidence",
        "message_author_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "moderation_report_evidence",
        "message_updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_moderation_report_evidence_author_users",
        "moderation_report_evidence",
        "users",
        ["message_author_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_moderation_report_evidence_author_users",
        "moderation_report_evidence",
        type_="foreignkey",
    )
    op.drop_column("moderation_report_evidence", "message_edited_at")
    op.drop_column("moderation_report_evidence", "message_updated_at")
    op.drop_column("moderation_report_evidence", "message_author_id")
