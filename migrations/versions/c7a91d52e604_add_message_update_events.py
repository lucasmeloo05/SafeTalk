"""add per-conversation message update events

Revision ID: c7a91d52e604
Revises: f6a4c20d93b1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7a91d52e604"
down_revision: Union[str, Sequence[str], None] = "f6a4c20d93b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("messages_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_conversations_messages_revision_nonnegative",
        "conversations",
        "messages_revision >= 0",
    )
    op.create_unique_constraint(
        "uq_messages_id_conversation", "messages", ["id", "conversation_id"]
    )
    op.create_table(
        "message_update_events",
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id", "revision", name="pk_message_update_events"),
        sa.CheckConstraint("revision >= 1", name="ck_message_update_events_revision_positive"),
        sa.CheckConstraint("event_type IN ('UPDATED', 'DELETED')", name="ck_message_update_events_type"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"],
            name="fk_message_update_events_conversation", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "conversation_id"], ["messages.id", "messages.conversation_id"],
            name="fk_message_update_events_message_conversation", ondelete="CASCADE",
        ),
    )

def downgrade() -> None:
    op.drop_table("message_update_events")
    op.drop_constraint("uq_messages_id_conversation", "messages", type_="unique")
    op.drop_constraint("ck_conversations_messages_revision_nonnegative", "conversations", type_="check")
    op.drop_column("conversations", "messages_revision")
