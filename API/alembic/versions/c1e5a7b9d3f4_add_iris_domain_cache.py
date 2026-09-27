"""iris: caché del contexto de infraestructura de un dominio (IrisDomainCache)

Primera consulta de Iris a un servicio externo: RDAP (edad, registrador y
servidores de nombres de un dominio) y la red donde se aloja. Se cachea por
dominio para no preguntar dos veces lo mismo al registro.

Revision ID: c1e5a7b9d3f4
Revises: b9d4f6a8c0e2
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c1e5a7b9d3f4'
down_revision: Union[str, Sequence[str], None] = 'b9d4f6a8c0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisDomainCache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('domain', sa.String(length=253), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('registered_at', sa.DateTime(), nullable=True),
        sa.Column('registry_expires_at', sa.DateTime(), nullable=True),
        sa.Column('registrar', sa.String(length=255), nullable=True),
        sa.Column('registry_status', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('nameservers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('address', sa.String(length=45), nullable=True),
        sa.Column('network_name', sa.String(length=255), nullable=True),
        sa.Column('country', sa.String(length=8), nullable=True),
        sa.Column('asn', sa.String(length=32), nullable=True),
        sa.Column('error', sa.String(length=64), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('domain'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('IrisDomainCache')
