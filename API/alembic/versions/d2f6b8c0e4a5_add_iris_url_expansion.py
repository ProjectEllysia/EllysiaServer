"""iris: expansión de URLs (IrisUrlExpansion)

Iris veía la URL escrita en el correo, no la página a la que lleva. Guarda,
por usuario, cada salto de los redirects de una URL, el certificado de cada
uno y el destino final.

Revision ID: d2f6b8c0e4a5
Revises: c1e5a7b9d3f4
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd2f6b8c0e4a5'
down_revision: Union[str, Sequence[str], None] = 'c1e5a7b9d3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisUrlExpansion',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('url_sha256', sa.String(length=64), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('hops', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('final_url', sa.Text(), nullable=True),
        sa.Column('final_domain', sa.String(length=253), nullable=True),
        sa.Column('final_status', sa.Integer(), nullable=True),
        sa.Column('page_title', sa.String(length=300), nullable=True),
        sa.Column('content_type', sa.String(length=120), nullable=True),
        sa.Column('is_domain_changed', sa.Boolean(), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'url_sha256', name='uq_iris_url_expansion_user_url'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('IrisUrlExpansion')
