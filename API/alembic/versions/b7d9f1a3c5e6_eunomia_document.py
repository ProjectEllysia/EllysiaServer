"""eunomia: documentos de cumplimiento generados en segundo plano

Subtipo de ``Document`` (herencia joined-table) con la plantilla, los valores con los que se
generó y el nombre de descarga.

Revision ID: b7d9f1a3c5e6
Revises: a6c8e0f2b4d5
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d9f1a3c5e6'
down_revision: Union[str, Sequence[str], None] = 'a6c8e0f2b4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaDocument',
        sa.Column('id', sa.Integer(), sa.ForeignKey('Document.id'), primary_key=True),
        sa.Column('template_key', sa.String(length=64), nullable=False),
        sa.Column('template_version', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('requested_by_name', sa.String(length=255), nullable=False),
        sa.Column('download_name', sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('EunomiaDocument')
