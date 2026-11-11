"""add birth date to users

Revision ID: b3a25b568222
Revises: f46a25e64a14
Create Date: 2026-11-01 01:53:13.664603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3a25b568222'
down_revision: Union[str, Sequence[str], None] = 'f46a25e64a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "birth_date")