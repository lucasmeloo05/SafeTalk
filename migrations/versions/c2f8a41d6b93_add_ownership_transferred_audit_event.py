"""allow audited server ownership transfers

Revision ID: c2f8a41d6b93
Revises: 9fb23a71c8d0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c2f8a41d6b93"
down_revision: Union[str, Sequence[str], None] = "9fb23a71c8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_server_audit_logs_valid_event_type",
        "server_audit_logs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_server_audit_logs_valid_event_type",
        "server_audit_logs",
        "event_type IN "
        "('MEMBER_KICKED', 'MEMBER_BANNED', 'MEMBER_UNBANNED', "
        "'OWNERSHIP_TRANSFERRED')",
    )
    op.drop_constraint(
        "ck_server_audit_logs_event_ban_snapshot_consistency",
        "server_audit_logs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_server_audit_logs_event_ban_snapshot_consistency",
        "server_audit_logs",
        "(event_type = 'MEMBER_KICKED' AND ban_id IS NULL "
        "AND role_snapshot IS NOT NULL "
        "AND jsonb_typeof(role_snapshot) = 'array') OR "
        "(event_type = 'MEMBER_BANNED' AND ban_id IS NOT NULL "
        "AND role_snapshot IS NOT NULL "
        "AND jsonb_typeof(role_snapshot) = 'array') OR "
        "(event_type = 'MEMBER_UNBANNED' AND ban_id IS NOT NULL "
        "AND (role_snapshot IS NULL "
        "OR role_snapshot = 'null'::jsonb)) OR "
        "(event_type = 'OWNERSHIP_TRANSFERRED' AND ban_id IS NULL "
        "AND (role_snapshot IS NULL "
        "OR role_snapshot = 'null'::jsonb))",
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_ownership_events = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM server_audit_logs "
            "WHERE event_type = 'OWNERSHIP_TRANSFERRED')"
        )
    ).scalar_one()
    if has_ownership_events:
        raise RuntimeError(
            "Cannot downgrade while ownership-transfer audit events exist; "
            "preserve the historical records before changing this schema."
        )

    op.drop_constraint(
        "ck_server_audit_logs_event_ban_snapshot_consistency",
        "server_audit_logs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_server_audit_logs_event_ban_snapshot_consistency",
        "server_audit_logs",
        "(event_type = 'MEMBER_KICKED' AND ban_id IS NULL "
        "AND role_snapshot IS NOT NULL "
        "AND jsonb_typeof(role_snapshot) = 'array') OR "
        "(event_type = 'MEMBER_BANNED' AND ban_id IS NOT NULL "
        "AND role_snapshot IS NOT NULL "
        "AND jsonb_typeof(role_snapshot) = 'array') OR "
        "(event_type = 'MEMBER_UNBANNED' AND ban_id IS NOT NULL "
        "AND (role_snapshot IS NULL "
        "OR role_snapshot = 'null'::jsonb))",
    )
    op.drop_constraint(
        "ck_server_audit_logs_valid_event_type",
        "server_audit_logs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_server_audit_logs_valid_event_type",
        "server_audit_logs",
        "event_type IN "
        "('MEMBER_KICKED', 'MEMBER_BANNED', 'MEMBER_UNBANNED')",
    )
