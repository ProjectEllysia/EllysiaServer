"""lybra: escaneo padre para un lote de hosts

Revision ID: c58d0f2248a1
Revises: ace84a6be06e
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c58d0f2248a1'
down_revision: Union[str, Sequence[str], None] = 'ace84a6be06e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Lybra sólo sabía escanear un host por escaneo. Cuando ``run_scan`` recibe
    una lista de objetivos (o un CIDR ya expandido por
    ``ScanManager.validate_targets``), abanica a un escaneo hijo por host y
    crea un escaneo padre que los agrupa — la fila que representa "el
    escaneo de esta red", no ninguno de los hosts en concreto.

    El padre nunca descubre nada por sí mismo: ``format_scan`` le suma los
    contadores de sus hijos en vez de leer la tabla ``Finding`` con su propio
    id, que siempre estará vacía.

    ``ondelete="CASCADE"`` porque los hijos sólo existen por haber sido
    lanzados como parte del lote del padre — borrar el padre borra el lote
    entero, no lo deja huérfano.
    """
    op.add_column(
        'LybraScan',
        sa.Column('parent_scan_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_LybraScan_parent_scan_id'), 'LybraScan', ['parent_scan_id'],
    )
    op.create_foreign_key(
        'fk_lybrascan_parent_scan_id', 'LybraScan', 'LybraScan',
        ['parent_scan_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    """Downgrade schema. Sin pérdida de hallazgos: sólo se pierde la
    agrupación padre/hijo, no ningún dato de los escaneos en sí."""
    op.drop_constraint('fk_lybrascan_parent_scan_id', 'LybraScan', type_='foreignkey')
    op.drop_index(op.f('ix_LybraScan_parent_scan_id'), table_name='LybraScan')
    op.drop_column('LybraScan', 'parent_scan_id')
