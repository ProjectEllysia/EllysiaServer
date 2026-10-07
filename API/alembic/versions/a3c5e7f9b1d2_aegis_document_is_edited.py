"""aegis document: marca de edición del texto generado por la IA

Los correos de una campaña dicen que el contenido se ha elaborado con ayuda de
inteligencia artificial y, si la empresa lo editó antes de enviarlo, que además
lo ha revisado. Para saberlo hay que guardar si la píldora pasó por una edición.
Las píldoras que ya existen se quedan como no editadas.

Revision ID: a3c5e7f9b1d2
Revises: d5f7a9c1e3b8
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c5e7f9b1d2'
down_revision: Union[str, Sequence[str], None] = 'd5f7a9c1e3b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('AegisDocument', sa.Column('is_edited', sa.Boolean(), nullable=False,
                                             server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('AegisDocument', 'is_edited')
