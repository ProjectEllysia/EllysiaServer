"""eunomia: marcos adoptados por el dueño efectivo de los datos

Una fila por (dueño, marco), fijada a una versión del catálogo. Un marco quitado se archiva
(``status = 'archived'``) y se purga pasado el plazo.

Revision ID: b1d3e5f7a9c0
Revises: a9c1d3e5f7b8
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1d3e5f7a9c0'
down_revision: Union[str, Sequence[str], None] = 'a9c1d3e5f7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaFrameworkAdoption',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('framework_key', sa.String(length=32), nullable=False),
        sa.Column('catalog_version', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('adopted_at', sa.DateTime(), nullable=False),
        sa.Column('adopted_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('archived_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.UniqueConstraint('owner_user_id', 'framework_key', name='uq_eunomia_adoption_owner_framework'),
    )
    op.create_index('ix_EunomiaFrameworkAdoption_owner_user_id', 'EunomiaFrameworkAdoption', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_EunomiaFrameworkAdoption_owner_user_id', table_name='EunomiaFrameworkAdoption')
    op.drop_table('EunomiaFrameworkAdoption')
