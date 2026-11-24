"""Persistent two-factor enrollment, challenges and audit."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "e21b7c84a603"
down_revision = "b241de8f753a"
branch_labels = depends_on = None

def upgrade():
    op.create_table("user_two_factor",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("secret", sa.Text()), sa.Column("session_version", sa.String(64)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("setup_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_step", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("recovery_hashes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)))
    op.create_table("two_factor_challenges",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_two_factor_challenges_user_id", "two_factor_challenges", ["user_id"])
    op.create_table("two_factor_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_two_factor_audit_user_id", "two_factor_audit", ["user_id"])

def downgrade():
    op.drop_table("two_factor_audit")
    op.drop_table("two_factor_challenges")
    op.drop_table("user_two_factor")
