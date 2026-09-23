"""lybra: la severidad que declara cada check

Revision ID: c3d8f2a4b6e1
Revises: a7c3e91f5d20
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d8f2a4b6e1'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91f5d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Cada check del feed declara una severidad (CRÍTICA para unas credenciales
    a la vista, INFO para un panel visible), pero el hallazgo no la guardaba y
    la prioridad se calculaba sólo por CVSS: todo check confirmado sin CVE
    salía en MEDIA. Con esta columna la prioridad parte de lo que declara el
    check. Es nula en los hallazgos anteriores, que siguen puntuándose como
    hasta ahora hasta que un escaneo nuevo los vuelva a producir.
    """
    op.add_column("Finding", sa.Column("severity", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Se pierde la severidad declarada; los hallazgos de checks vuelven a
    puntuarse con el suelo de MEDIA.
    """
    op.drop_column("Finding", "severity")
