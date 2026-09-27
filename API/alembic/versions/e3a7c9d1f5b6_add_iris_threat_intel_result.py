"""iris: caché de reputación de indicadores (IrisThreatIntelResult)

Iris no consultaba ninguna reputación externa. Guarda, por proveedor e
indicador, el veredicto normalizado (known_malicious, suspicious, unknown o
unavailable), su detalle y cuándo caduca.

Revision ID: e3a7c9d1f5b6
Revises: d2f6b8c0e4a5
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e3a7c9d1f5b6'
down_revision: Union[str, Sequence[str], None] = 'd2f6b8c0e4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisThreatIntelResult',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('value_sha256', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('verdict', sa.String(length=20), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.String(length=64), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'kind', 'value_sha256', name='uq_iris_threat_intel_result'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('IrisThreatIntelResult')
