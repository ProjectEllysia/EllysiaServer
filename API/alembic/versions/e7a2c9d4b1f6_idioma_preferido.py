"""idioma preferido del usuario y de la organización

Revision ID: e7a2c9d4b1f6
Revises: d4e9a1b7c2f3
Create Date: 2026-09-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a2c9d4b1f6'
down_revision: Union[str, Sequence[str], None] = 'd4e9a1b7c2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Dos columnas nulas: el idioma que eligió cada usuario y el que su
    organización da por defecto. Nacen vacías en las filas existentes, y vacío
    significa «no he elegido»: todo el mundo sigue en el idioma de la
    plataforma, como hasta ahora.
    """
    op.add_column("User", sa.Column("language", sa.String(length=8), nullable=True))
    op.add_column("Organization", sa.Column("default_language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Se pierde el idioma elegido por cada usuario y por cada organización; la
    interfaz vuelve a recordarlo solo en el dispositivo.
    """
    op.drop_column("Organization", "default_language")
    op.drop_column("User", "language")
