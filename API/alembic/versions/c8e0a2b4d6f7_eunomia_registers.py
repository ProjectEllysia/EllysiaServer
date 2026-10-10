"""eunomia: fichas de los registros y su historial

Revision ID: c8e0a2b4d6f7
Revises: b7d9f1a3c5e6
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e0a2b4d6f7'
down_revision: Union[str, Sequence[str], None] = 'b7d9f1a3c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaRecord',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('register_key', sa.String(length=64), nullable=False),
        sa.Column('register_version', sa.String(length=16), nullable=False),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
    )
    op.create_index('ix_eunomia_record_owner_register', 'EunomiaRecord', ['owner_user_id', 'register_key'])
    op.create_table(
        'EunomiaRecordEvent',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('record_id', sa.Integer(), sa.ForeignKey('EunomiaRecord.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.Column('actor_name', sa.String(length=255), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
    )
    op.create_index('ix_EunomiaRecordEvent_record_id', 'EunomiaRecordEvent', ['record_id'])


def downgrade() -> None:
    op.drop_index('ix_EunomiaRecordEvent_record_id', table_name='EunomiaRecordEvent')
    op.drop_table('EunomiaRecordEvent')
    op.drop_index('ix_eunomia_record_owner_register', table_name='EunomiaRecord')
    op.drop_table('EunomiaRecord')
