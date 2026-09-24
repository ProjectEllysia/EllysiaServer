"""lybra: la identidad reutilizada de un servicio caduca

Revision ID: d4e9a1b7c2f3
Revises: c3d8f2a4b6e1
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e9a1b7c2f3'
down_revision: Union[str, Sequence[str], None] = 'c3d8f2a4b6e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Un re-escaneo reutiliza el producto y la versión que un escaneo anterior
    sacó de cada servicio, en vez de volver a sondearlo. Estas dos columnas
    dicen cuándo y con qué revisión del identificador se sondeó de verdad,
    para que esa identidad caduque. Nacen nulas en las filas existentes, y una
    identidad sin fecha no se reutiliza: el primer escaneo tras migrar vuelve a
    sondear cada servicio conocido.
    """
    op.add_column("HostService", sa.Column("identified_at", sa.DateTime(), nullable=True))
    op.add_column("HostService", sa.Column("identified_by", sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Se pierde cuándo se identificó cada servicio; el planificador vuelve a
    reutilizar cualquier identidad guardada sin plazo.
    """
    op.drop_column("HostService", "identified_by")
    op.drop_column("HostService", "identified_at")
