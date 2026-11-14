"""require positive server role positions

Revision ID: 990fa9af113d
Revises: 8a62d13e4f90
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "990fa9af113d"
down_revision: Union[str, Sequence[str], None] = "8a62d13e4f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_server_roles_position_positive",
        "server_roles",
        "position >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_server_roles_position_positive",
        "server_roles",
        type_="check",
    )
