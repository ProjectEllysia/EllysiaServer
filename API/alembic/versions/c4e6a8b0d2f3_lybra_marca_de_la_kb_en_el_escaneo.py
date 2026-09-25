"""lybra: la marca de la base de conocimiento, en el escaneo y con OVAL

Revision ID: c4e6a8b0d2f3
Revises: b3d5f7a9c1e2
Create Date: 2026-09-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e6a8b0d2f3'
down_revision: Union[str, Sequence[str], None] = 'b3d5f7a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añade ``LybraScan.kb_version`` y ensancha ``Finding.feed_version``.

    El informe de un escaneo tiene que decir contra qué fecha de cada fuente
    de la base de conocimiento se resolvió, y no contra cuál está hoy: un
    informe regenerado días después no puede afirmar que usó datos que aún no
    existían. La marca se guarda en el escaneo porque un escaneo sin hallazgos
    por versión no tendría otro sitio donde llevarla.

    La marca incluye ahora OVAL y ocupa hasta 70 caracteres, más que los 64 de
    ``Finding.feed_version``. Las filas existentes no cambian; los escaneos
    anteriores quedan sin marca, y el informe lo dice.
    """
    op.add_column("LybraScan", sa.Column("kb_version", sa.String(length=128), nullable=True))
    op.alter_column("Finding", "feed_version",
                    existing_type=sa.String(length=64), type_=sa.String(length=128))


def downgrade() -> None:
    """Deshace la columna y el ensanche.

    Una marca de más de 64 caracteres escrita con la versión nueva no cabe de
    vuelta; se recorta, que es lo único que puede hacer una bajada de versión.
    """
    op.execute('UPDATE "Finding" SET feed_version = LEFT(feed_version, 64)')
    op.alter_column("Finding", "feed_version",
                    existing_type=sa.String(length=128), type_=sa.String(length=64))
    op.drop_column("LybraScan", "kb_version")
