"""lybra: perfil de escaneo elegido (#308)

Revision ID: e69f6af8eeef
Revises: 4673e0aaf802
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e69f6af8eeef'
down_revision: Union[str, Sequence[str], None] = '4673e0aaf802'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Hasta ahora Lybra sólo tenía un modo de operar (los puertos de
    ``DEFAULT_PORTS``, el feed completo, modo ``safe``), así que no hacía
    falta guardar nada: el informe no necesitaba decir cómo se escaneó
    porque siempre era de la misma manera. Con los perfiles ("fast",
    "standard", "thorough") eso deja de ser cierto: "no se encontró nada" no
    significa lo mismo si el perfil miró cien puertos que si miró todos.

    ``server_default`` es obligatorio y no cosmético: la columna es NOT NULL
    y la tabla ya tiene filas. Los escaneos anteriores quedan como
    "standard", que es el comportamiento que de hecho tenían.
    """
    op.add_column(
        "LybraScan",
        sa.Column("profile", sa.String(length=20), nullable=False,
                  server_default="standard"),
    )


def downgrade() -> None:
    """Downgrade schema.

    Reversible sin pérdida de hallazgos: al bajar se pierde únicamente la
    marca de qué perfil se usó, no ningún dato del escaneo.
    """
    op.drop_column("LybraScan", "profile")
