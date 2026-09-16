"""hygeia: documentos generados en segundo plano

Revision ID: b0246d3aa0cb
Revises: c58d0f2248a1
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b0246d3aa0cb'
down_revision: Union[str, Sequence[str], None] = 'c58d0f2248a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Crea ``HygeiaDocument``, la tabla hija de ``Document`` para los ficheros
    que Hygeia genera en segundo plano: los CSV de estadísticas y el PDF del
    inventario. Sigue la herencia *joined-table* de ``IrisDocument`` y
    ``ThemisDocument``: la fila común (dueño, formato, estado, fechas, ruta)
    vive en ``Document`` con ``document_type = 'hygeia'``.

    No hay clave ajena a una entidad padre: un documento de Hygeia describe
    una consulta, y la consulta completa viaja en ``parameters``.
    """
    op.create_table(
        'HygeiaDocument',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('download_name', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['id'], ['Document.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema.

    Borra la tabla hija y las filas comunes que quedarían huérfanas en
    ``Document``. Los ficheros ya generados en disco no se tocan.
    """
    op.drop_table('HygeiaDocument')
    op.execute("DELETE FROM \"Document\" WHERE document_type = 'hygeia'")
