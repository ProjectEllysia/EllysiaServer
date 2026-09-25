"""aegis: el idioma en que se generó cada píldora

Revision ID: a8d3f1c6e2b7
Revises: c4e6a8b0d2f3
Create Date: 2026-09-25 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8d3f1c6e2b7'
down_revision: Union[str, Sequence[str], None] = 'c4e6a8b0d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Una columna nula con el idioma de la píldora, del que depende el idioma de
    los correos de sus campañas. Las píldoras existentes nacen vacías y sus
    campañas usan el idioma del perfil de Aegis de su dueño, que es con el que
    se generaron salvo que se pidiera otro al generarlas.
    """
    op.add_column("AegisDocument", sa.Column("language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Se pierde el idioma de cada píldora; las campañas vuelven a salir en el
    idioma del perfil de Aegis.
    """
    op.drop_column("AegisDocument", "language")
