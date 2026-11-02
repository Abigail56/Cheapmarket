"""notification bell

Revision ID: b41c7e9d2a10
Revises: 7f2751be0a48
Create Date: 2026-11-02 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = 'b41c7e9d2a10'
down_revision: Union[str, None] = '7f2751be0a48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=150), nullable=False),
    sa.Column('body', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('order_number', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_table('notifications')
