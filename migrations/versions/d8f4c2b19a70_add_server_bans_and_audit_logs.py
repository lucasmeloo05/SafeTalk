"""add server ban cycles and moderation audit logs

Revision ID: d8f4c2b19a70
Revises: 990fa9af113d
Create Date: 2026-11-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d8f4c2b19a70"
down_revision: Union[str, Sequence[str], None] = "990fa9af113d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "server_bans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("banned_by", sa.Integer(), nullable=False),
        sa.Column(
            "banned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("target_highest_role_position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "target_highest_role_position >= 0",
            name="ck_server_bans_non_negative_target_position",
        ),
        sa.CheckConstraint(
            "(is_active AND revoked_at IS NULL AND revoked_by IS NULL) OR "
            "(NOT is_active AND revoked_at IS NOT NULL "
            "AND revoked_by IS NOT NULL)",
            name="ck_server_bans_revocation_consistency",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= banned_at",
            name="ck_server_bans_revoked_after_ban",
        ),
        sa.CheckConstraint(
            "banned_by <> user_id",
            name="ck_server_bans_no_self_ban",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name="fk_server_bans_server_id_servers"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_server_bans_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["banned_by"], ["users.id"], name="fk_server_bans_banned_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"], ["users.id"], name="fk_server_bans_revoked_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["server_id", "user_id"],
            ["server_members.server_id", "server_members.user_id"],
            name="fk_server_bans_member_server_user",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_server_bans"),
        sa.UniqueConstraint(
            "id", "server_id", "user_id", name="uq_server_bans_id_server_user"
        ),
    )
    op.create_index(
        "uq_server_bans_one_active_per_user",
        "server_bans",
        ["server_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_server_bans_server_user_banned_at",
        "server_bans",
        ["server_id", "user_id", "banned_at"],
    )
    op.create_index(
        "ix_server_bans_server_active_banned_at",
        "server_bans",
        ["server_id", "is_active", "banned_at"],
    )

    op.create_table(
        "server_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ban_id", sa.Integer(), nullable=True),
        sa.Column("role_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "event_type IN "
            "('MEMBER_KICKED', 'MEMBER_BANNED', 'MEMBER_UNBANNED')",
            name="ck_server_audit_logs_valid_event_type",
        ),
        sa.CheckConstraint(
            "actor_user_id <> target_user_id",
            name="ck_server_audit_logs_actor_differs_from_target",
        ),
        sa.CheckConstraint(
            "(event_type = 'MEMBER_KICKED' AND ban_id IS NULL "
            "AND role_snapshot IS NOT NULL "
            "AND jsonb_typeof(role_snapshot) = 'array') OR "
            "(event_type = 'MEMBER_BANNED' AND ban_id IS NOT NULL "
            "AND role_snapshot IS NOT NULL "
            "AND jsonb_typeof(role_snapshot) = 'array') OR "
            "(event_type = 'MEMBER_UNBANNED' AND ban_id IS NOT NULL "
            "AND (role_snapshot IS NULL "
            "OR role_snapshot = 'null'::jsonb))",
            name="ck_server_audit_logs_event_ban_snapshot_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name="fk_server_audit_logs_server_id_servers",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_server_audit_logs_actor_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_server_audit_logs_target_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["ban_id", "server_id", "target_user_id"],
            ["server_bans.id", "server_bans.server_id", "server_bans.user_id"],
            name="fk_server_audit_logs_ban_server_target",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_server_audit_logs"),
    )
    op.create_index(
        "ix_server_audit_logs_server_occurred_at",
        "server_audit_logs",
        ["server_id", "occurred_at"],
    )
    op.create_index(
        "ix_server_audit_logs_server_target_occurred_at",
        "server_audit_logs",
        ["server_id", "target_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_server_audit_logs_server_actor_occurred_at",
        "server_audit_logs",
        ["server_id", "actor_user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_server_audit_logs_server_actor_occurred_at",
        table_name="server_audit_logs",
    )
    op.drop_index(
        "ix_server_audit_logs_server_target_occurred_at",
        table_name="server_audit_logs",
    )
    op.drop_index(
        "ix_server_audit_logs_server_occurred_at",
        table_name="server_audit_logs",
    )
    op.drop_table("server_audit_logs")

    op.drop_index(
        "ix_server_bans_server_active_banned_at",
        table_name="server_bans",
    )
    op.drop_index(
        "ix_server_bans_server_user_banned_at",
        table_name="server_bans",
    )
    op.drop_index(
        "uq_server_bans_one_active_per_user",
        table_name="server_bans",
    )
    op.drop_table("server_bans")
