"""Channel publishing policy and message streams.

Revision ID: b241de8f753a
Revises: a8c37d4e91b2
"""
from alembic import op
import sqlalchemy as sa

revision = "b241de8f753a"
down_revision = "a8c37d4e91b2"
branch_labels = depends_on = None


def conversation_checks(channels):
    types = "'DIRECT', 'GROUP', 'CHANNEL'" if channels else "'DIRECT', 'GROUP'"
    groups = "'GROUP', 'CHANNEL'" if channels else "'GROUP'"
    op.create_check_constraint("ck_conversations_valid_type", "conversations", f"type IN ({types})")
    op.create_check_constraint("ck_conversations_valid_type_and_users", "conversations",
        "(type = 'DIRECT' AND user_a_id IS NOT NULL AND user_b_id IS NOT NULL "
        "AND user_a_id < user_b_id AND created_by IN (user_a_id,user_b_id)) "
        f"OR (type IN ({groups}) AND user_a_id IS NULL AND user_b_id IS NULL)")


def replace_checks(channels):
    for name in ("ck_conversations_valid_type", "ck_conversations_valid_type_and_users"):
        op.drop_constraint(name, "conversations", type_="check")
    conversation_checks(channels)
    op.drop_constraint("ck_message_update_events_type", "message_update_events", type_="check")
    kinds = "'UPDATED','DELETED','CREATED'" if channels else "'UPDATED','DELETED'"
    op.create_check_constraint("ck_message_update_events_type", "message_update_events", f"event_type IN ({kinds})")


def upgrade():
    for flag in ("is_read_only", "is_archived"):
        op.add_column("server_channels", sa.Column(flag, sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint("uq_server_channels_server_name", "server_channels", type_="unique")
    op.create_index("uq_server_channels_server_name", "server_channels", ["server_id", "name"],
                    unique=True, postgresql_where=sa.text("NOT is_archived"))
    op.add_column("conversations", sa.Column("channel_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_conversations_channel", "conversations", "server_channels",
                          ["channel_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_conversations_channel", "conversations", ["channel_id"])
    replace_checks(True)
    op.create_check_constraint("ck_conversations_channel_scope", "conversations",
                               "(type = 'CHANNEL') = (channel_id IS NOT NULL)")
    for field in ("server_id", "channel_id"):
        op.add_column("moderation_report_evidence", sa.Column(field, sa.Integer(), nullable=True))
    op.execute("INSERT INTO conversations (type,channel_id,created_by) "
               "SELECT 'CHANNEL',c.id,s.owner_id FROM server_channels c JOIN servers s ON s.id=c.server_id")


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT EXISTS (SELECT FROM messages m JOIN conversations c "
                         "ON c.id=m.conversation_id WHERE c.type='CHANNEL') "
                         "OR EXISTS (SELECT FROM server_channels WHERE is_read_only OR is_archived)")):
        raise RuntimeError("Downgrade requires an empty channel history and default channel policies.")
    op.execute("DELETE FROM conversations WHERE type='CHANNEL'")
    op.drop_constraint("ck_conversations_channel_scope", "conversations", type_="check")
    replace_checks(False)
    for field in ("channel_id", "server_id"):
        op.drop_column("moderation_report_evidence", field)
    op.drop_column("conversations", "channel_id")
    op.drop_index("uq_server_channels_server_name", table_name="server_channels")
    op.create_unique_constraint("uq_server_channels_server_name", "server_channels", ["server_id", "name"])
    for flag in ("is_archived", "is_read_only"):
        op.drop_column("server_channels", flag)
