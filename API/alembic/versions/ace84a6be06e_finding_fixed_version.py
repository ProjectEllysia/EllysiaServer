"""finding: persistir fixed_version

Revision ID: ace84a6be06e
Revises: e69f6af8eeef
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ace84a6be06e'
down_revision: Union[str, Sequence[str], None] = 'e69f6af8eeef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    La versión que corrige un hallazgo por versión se calculaba al vuelo en
    cada informe (``services/reports/findings.py::_find_fixed_version``, hoy
    ``services/cve_context.py``), así que no era ni consultable por API ni
    agrupable por SQL — «esta actualización cierra 14 hallazgos» no se podía
    responder sin recorrer todos los hallazgos a mano.

    La columna se rellena hacia delante, en el momento de persistir cada
    hallazgo nuevo (ver ``LybraEngineManager._persist_scan_results``). Los
    hallazgos ya existentes se quedan en ``NULL`` — no se recalculan en esta
    migración porque hacerlo exigiría repetir la misma consulta a la KB que
    ya hace el informe, y el próximo escaneo de cada host los actualiza de
    todas formas.
    """
    op.add_column('Finding', sa.Column('fixed_version', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Sin pérdida de otros datos: sólo se deja de guardar
    la versión corregida: el informe la sigue calculando al vuelo como antes."""
    op.drop_column('Finding', 'fixed_version')
