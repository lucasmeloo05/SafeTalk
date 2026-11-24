"""Private server channels and historical channel access events."""
from alembic import op
import sqlalchemy as sa

revision = "d7af10e95bc2"
down_revision = "c2f8a41d6b93"
branch_labels = None
depends_on = None

TYPE_CHECK = "ck_server_audit_logs_valid_event_type"
SHAPE_CHECK = "ck_server_audit_logs_event_ban_snapshot_consistency"
MEMBER_TYPES = "'MEMBER_KICKED', 'MEMBER_BANNED', 'MEMBER_UNBANNED', 'OWNERSHIP_TRANSFERRED'"
CHANNEL_TYPES = (
    "'CHANNEL_ROLE_ACCESS_GRANTED', 'CHANNEL_ROLE_ACCESS_REVOKED', "
    "'CHANNEL_BECAME_PRIVATE', 'CHANNEL_BECAME_PUBLIC'"
)
MEMBER_SHAPE = """
    (event_type = 'MEMBER_KICKED' AND ban_id IS NULL AND role_snapshot IS NOT NULL
        AND jsonb_typeof(role_snapshot) = 'array') OR
    (event_type = 'MEMBER_BANNED' AND ban_id IS NOT NULL AND role_snapshot IS NOT NULL
        AND jsonb_typeof(role_snapshot) = 'array') OR
    (event_type = 'MEMBER_UNBANNED' AND ban_id IS NOT NULL
        AND (role_snapshot IS NULL OR role_snapshot = 'null'::jsonb)) OR
    (event_type = 'OWNERSHIP_TRANSFERRED' AND ban_id IS NULL
        AND (role_snapshot IS NULL OR role_snapshot = 'null'::jsonb))
"""
CHANNEL_SHAPE = """
    target_user_id IS NULL AND channel_id IS NOT NULL AND ban_id IS NULL AND role_snapshot IS NULL AND (
        (event_type IN ('CHANNEL_ROLE_ACCESS_GRANTED', 'CHANNEL_ROLE_ACCESS_REVOKED') AND role_id IS NOT NULL)
        OR (event_type IN ('CHANNEL_BECAME_PRIVATE', 'CHANNEL_BECAME_PUBLIC') AND role_id IS NULL)
    )
"""
OLD_CHECKS = {TYPE_CHECK: f"event_type IN ({MEMBER_TYPES})", SHAPE_CHECK: MEMBER_SHAPE}
NEW_CHECKS = {
    TYPE_CHECK: f"event_type IN ({MEMBER_TYPES}, {CHANNEL_TYPES})",
    SHAPE_CHECK: f"({CHANNEL_SHAPE}) OR (target_user_id IS NOT NULL AND channel_id IS NULL "
                 f"AND role_id IS NULL AND ({MEMBER_SHAPE}))",
}


def replace_checks(checks):
    for name, condition in checks.items():
        op.drop_constraint(name, "server_audit_logs", type_="check")
        op.create_check_constraint(name, "server_audit_logs", condition)


def upgrade():
    op.add_column("server_channels", sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_unique_constraint("uq_server_channels_id_server", "server_channels", ["id", "server_id"])
    op.create_table(
        "server_channel_roles",
        sa.Column("channel_id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), primary_key=True),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id", "server_id"], ["server_channels.id", "server_channels.server_id"]),
        sa.ForeignKeyConstraint(["role_id", "server_id"], ["server_roles.id", "server_roles.server_id"],
                                name="fk_channel_access_role"),
    )
    for column in ("channel_id", "role_id"):
        op.add_column("server_audit_logs", sa.Column(column, sa.Integer()))
    op.alter_column("server_audit_logs", "target_user_id", nullable=True)
    replace_checks(NEW_CHECKS)


def downgrade():
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT FROM server_channels WHERE is_private) OR "
        "EXISTS (SELECT FROM server_audit_logs WHERE channel_id IS NOT NULL) OR "
        "EXISTS (SELECT FROM server_channel_roles)"
    )):
        raise RuntimeError("Downgrade would discard channel privacy or audit records.")
    replace_checks(OLD_CHECKS)
    op.alter_column("server_audit_logs", "target_user_id", nullable=False)
    op.drop_column("server_audit_logs", "role_id")
    op.drop_column("server_audit_logs", "channel_id")
    op.drop_table("server_channel_roles")
    op.drop_constraint("uq_server_channels_id_server", "server_channels", type_="unique")
    op.drop_column("server_channels", "is_private")
