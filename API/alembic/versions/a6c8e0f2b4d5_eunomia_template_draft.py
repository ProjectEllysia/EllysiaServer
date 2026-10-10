"""eunomia: borradores de plantillas de documentos

Una fila por (dueño efectivo, plantilla) con lo que el usuario escribió en el formulario.

Revision ID: a6c8e0f2b4d5
Revises: f5b7c9d1e3a4
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a6c8e0f2b4d5'
down_revision: Union[str, Sequence[str], None] = 'f5b7c9d1e3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaTemplateDraft',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('template_key', sa.String(length=64), nullable=False),
        sa.Column('template_version', sa.String(length=16), nullable=False),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.UniqueConstraint('owner_user_id', 'template_key', name='uq_eunomia_template_draft_owner_template'),
    )
    op.create_index('ix_EunomiaTemplateDraft_owner_user_id', 'EunomiaTemplateDraft', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_EunomiaTemplateDraft_owner_user_id', table_name='EunomiaTemplateDraft')
    op.drop_table('EunomiaTemplateDraft')
