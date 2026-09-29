"""lybra: escaneo pasivo de dominios (OsintScan) y caché de sus fuentes (OsintSourceCache)

- OsintScan: un escaneo pasivo de un dominio —Certificate Transparency,
  Shodan, Censys, SecurityTrails y la higiene de su DNS— con sus subdominios,
  el resultado de cada fuente y sus hallazgos. No es un Scan: no sondea nada
  ni tiene host. La columna mode deja sitio a otros modos pasivos que partan
  de los subdominios encontrados.
- OsintSourceCache: la última respuesta de cada fuente a cada consulta, con la
  fecha en que se descargó; la caducidad se calcula al leer.

Revision ID: a7c1e3f5b9d2
Revises: e9a3c5d7f1b6
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c1e3f5b9d2'
down_revision: Union[str, Sequence[str], None] = 'e9a3c5d7f1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'OsintScan',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False, server_default='passive'),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('failure_reason', sa.String(length=40), nullable=True),
        sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('dns_checks', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('subdomains', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_OsintScan_user_id'), 'OsintScan', ['user_id'], unique=False)
    op.create_index(op.f('ix_OsintScan_domain'), 'OsintScan', ['domain'], unique=False)

    op.create_table(
        'OsintSourceCache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('query', sa.String(length=255), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'query', name='uq_osintsourcecache_source_query'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('OsintSourceCache')
    op.drop_index(op.f('ix_OsintScan_domain'), table_name='OsintScan')
    op.drop_index(op.f('ix_OsintScan_user_id'), table_name='OsintScan')
    op.drop_table('OsintScan')
