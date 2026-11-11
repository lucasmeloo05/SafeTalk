
"""add user relationships tables

Revision ID: 1b2711d27349
Revises: b3a25b568222
Create Date: 2026-11-10 19:54:35.463707

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b2711d27349'
down_revision: Union[str, Sequence[str], None] = 'b3a25b568222'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Tabela de bloqueios entre usuários
    op.create_table(
        'blocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('blocker_id', sa.Integer(), nullable=False),
        sa.Column('blocked_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.CheckConstraint(
            'blocker_id <> blocked_id',
            name='ck_blocks_no_self_block'
        ),
        sa.ForeignKeyConstraint(['blocked_id'], ['users.id']),
        sa.ForeignKeyConstraint(['blocker_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'blocker_id',
            'blocked_id',
            name='uq_blocks_blocker_blocked'
        )
    )

    # Tabela de amizades
    op.create_table(
        'friendships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_a_id', sa.Integer(), nullable=False),
        sa.Column('user_b_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'REMOVED')",
            name='ck_friendships_valid_status'
        ),
        sa.CheckConstraint(
            'requested_by_id IN (user_a_id, user_b_id)',
            name='ck_friendships_requester_in_pair'
        ),
        sa.CheckConstraint(
            'user_a_id < user_b_id',
            name='ck_friendships_user_order'
        ),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_a_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_b_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_a_id',
            'user_b_id',
            name='uq_friendships_user_pair'
        )
    )

    # Tabela de administradores e moderadores oficiais da plataforma
    op.create_table(
        'platform_staff',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column(
            'appointed_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('ADMIN', 'MODERATOR')",
            name='ck_platform_staff_valid_role'
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')",
            name='ck_platform_staff_valid_status'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id')
    )

    # Configurações de privacidade dos usuários
    op.create_table(
        'user_privacy_settings',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column(
            'allow_messages_from_strangers',
            sa.Boolean(),
            nullable=False
        ),
        sa.Column(
            'allow_friend_requests',
            sa.Boolean(),
            nullable=False
        ),
        sa.Column(
            'show_online_status',
            sa.Boolean(),
            nullable=False
        ),
        sa.Column(
            'allow_group_invites',
            sa.Boolean(),
            nullable=False
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id')
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Remove somente as quatro tabelas criadas nesta migração.
    # A tabela users e seus índices permanecem intactos.

    op.drop_table('user_privacy_settings')
    op.drop_table('platform_staff')
    op.drop_table('friendships')
    op.drop_table('blocks')
