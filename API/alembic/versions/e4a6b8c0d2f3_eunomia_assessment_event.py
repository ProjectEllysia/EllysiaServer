"""eunomia: historial de cambios de las evaluaciones

Una fila por cambio, de solo añadir. ``actor_name`` guarda el nombre visible al hacer el
cambio para que sobreviva a la baja de la cuenta, que anula ``actor_user_id``.

Revision ID: e4a6b8c0d2f3
Revises: d3f5a7b9c1e2
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4a6b8c0d2f3'
down_revision: Union[str, Sequence[str], None] = 'd3f5a7b9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaAssessmentEvent',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('framework_key', sa.String(length=32), nullable=False),
        sa.Column('control_identifier', sa.String(length=128), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.Column('actor_name', sa.String(length=255), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
    )
    op.create_index('ix_eunomia_event_owner_framework_control', 'EunomiaAssessmentEvent',
                    ['owner_user_id', 'framework_key', 'control_identifier'])


def downgrade() -> None:
    op.drop_index('ix_eunomia_event_owner_framework_control', table_name='EunomiaAssessmentEvent')
    op.drop_table('EunomiaAssessmentEvent')
