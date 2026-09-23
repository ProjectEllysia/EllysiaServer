"""lybra: sitios con nombre detrás de una misma IP

Revision ID: a7c3e91f5d20
Revises: b0246d3aa0cb
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91f5d20'
down_revision: Union[str, Sequence[str], None] = 'b0246d3aa0cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Un servidor compartido sirve varias webs detrás de la misma IP y el mismo
    puerto, y decide cuál responde por el nombre que dice el cliente. Lybra
    audita ahora cada sitio con nombre que descubre, así que el mismo check
    puede disparar sobre dos sitios del mismo puerto: ``vhost`` dice sobre
    cuál. Es nula en todo hallazgo anterior, que se refería al host sin más.
    """
    op.add_column("Finding", sa.Column("vhost", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Se pierde a qué sitio se refería cada hallazgo; los hallazgos siguen ahí,
    indistinguibles entre sitios del mismo puerto.
    """
    op.drop_column("Finding", "vhost")
