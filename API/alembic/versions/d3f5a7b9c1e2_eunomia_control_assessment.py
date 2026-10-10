"""eunomia: evaluación de los controles de un marco adoptado

Una fila por (dueño efectivo, marco, control). ``updated_at`` es también el testigo de la
concurrencia optimista.

Revision ID: d3f5a7b9c1e2
Revises: c2e4f6a8b0d1
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3f5a7b9c1e2'
down_revision: Union[str, Sequence[str], None] = 'c2e4f6a8b0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaControlAssessment',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('framework_key', sa.String(length=32), nullable=False),
        sa.Column('catalog_version', sa.String(length=64), nullable=False),
        sa.Column('control_identifier', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('responsible_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.UniqueConstraint('owner_user_id', 'framework_key', 'control_identifier',
                            name='uq_eunomia_assessment_owner_framework_control'),
    )
    op.create_index('ix_EunomiaControlAssessment_owner_user_id', 'EunomiaControlAssessment', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_EunomiaControlAssessment_owner_user_id', table_name='EunomiaControlAssessment')
    op.drop_table('EunomiaControlAssessment')
