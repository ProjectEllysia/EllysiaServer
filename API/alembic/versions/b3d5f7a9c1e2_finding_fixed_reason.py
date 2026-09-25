"""finding: motivo de un «corregido» que no es una remediación

Revision ID: b3d5f7a9c1e2
Revises: e7a2c9d4b1f6
Create Date: 2026-09-25 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d5f7a9c1e2'
down_revision: Union[str, Sequence[str], None] = 'e7a2c9d4b1f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añade ``Finding.fixed_reason``.

    Un hallazgo pasa a ``fixed`` tanto cuando el cliente lo arregla como cuando
    el motor deja de verlo por una mejora propia (la distribución ya lo había
    parcheado, o su sitio es un alias del sitio por defecto). El informe tiene
    que poder separar las dos cosas para no atribuirle al cliente correcciones
    que no ha hecho. Nullable y sin valor por defecto: las filas existentes
    quedan como remediaciones, que es como se contaban.
    """
    op.add_column("Finding", sa.Column("fixed_reason", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Quita ``Finding.fixed_reason``."""
    op.drop_column("Finding", "fixed_reason")
