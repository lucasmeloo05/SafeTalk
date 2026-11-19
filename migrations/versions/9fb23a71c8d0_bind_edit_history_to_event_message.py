"""bind message edit history to the event's message

Revision ID: 9fb23a71c8d0
Revises: ee65b71a98a3
"""
from typing import Sequence, Union

from alembic import op


revision: str = "9fb23a71c8d0"
down_revision: Union[str, Sequence[str], None] = "ee65b71a98a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The event primary key remains (conversation_id, revision). PostgreSQL
    # needs an exact unique key for the strengthened three-column FK.
    op.create_unique_constraint(
        "uq_message_update_events_conversation_revision_message",
        "message_update_events",
        ["conversation_id", "revision", "message_id"],
    )
    op.drop_constraint(
        "fk_message_edit_history_update_event",
        "message_edit_history",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_message_edit_history_update_event_message",
        "message_edit_history",
        "message_update_events",
        ["conversation_id", "message_state_revision", "message_id"],
        ["conversation_id", "revision", "message_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_message_edit_history_update_event_message",
        "message_edit_history",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_message_update_events_conversation_revision_message",
        "message_update_events",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_message_edit_history_update_event",
        "message_edit_history",
        "message_update_events",
        ["conversation_id", "message_state_revision"],
        ["conversation_id", "revision"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
