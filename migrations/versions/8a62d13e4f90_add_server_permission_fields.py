"""add server permission foundation fields

Revision ID: 8a62d13e4f90
Revises: bc365585aa97
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8a62d13e4f90"
down_revision: Union[str, Sequence[str], None] = "bc365585aa97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "server_roles",
        sa.Column(
            "is_system_role",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "servers",
        sa.Column(
            "everyone_permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_servers_everyone_permissions_object",
        "servers",
        "jsonb_typeof(everyone_permissions) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_servers_everyone_permissions_object",
        "servers",
        type_="check",
    )
    op.drop_column("servers", "everyone_permissions")
    op.drop_column("server_roles", "is_system_role")
