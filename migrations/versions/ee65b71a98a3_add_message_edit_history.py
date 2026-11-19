"""add internal message edit history

Revision ID: ee65b71a98a3
Revises: c7a91d52e604
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ee65b71a98a3"
down_revision: Union[str, Sequence[str], None] = "c7a91d52e604"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_edit_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("previous_content", sa.Text(), nullable=False),
        sa.Column("new_content", sa.Text(), nullable=False),
        sa.Column("edited_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "edited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("message_state_revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_message_edit_history"),
        sa.CheckConstraint(
            "message_state_revision >= 1",
            name="ck_message_edit_history_revision_positive",
        ),
        sa.CheckConstraint(
            "previous_content <> new_content",
            name="ck_message_edit_history_content_changed",
        ),
        sa.UniqueConstraint(
            "message_id",
            "message_state_revision",
            name="uq_message_edit_history_message_revision",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_message_edit_history_message_conversation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "message_state_revision"],
            ["message_update_events.conversation_id", "message_update_events.revision"],
            name="fk_message_edit_history_update_event",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_id"],
            ["users.id"],
            name="fk_message_edit_history_editor_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_message_edit_history_event_revision",
        "message_edit_history",
        ["conversation_id", "message_state_revision"],
    )
    op.create_index(
        "ix_message_edit_history_edited_by_id",
        "message_edit_history",
        ["edited_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_message_edit_history_edited_by_id", table_name="message_edit_history"
    )
    op.drop_index(
        "ix_message_edit_history_event_revision", table_name="message_edit_history"
    )
    op.drop_table("message_edit_history")
