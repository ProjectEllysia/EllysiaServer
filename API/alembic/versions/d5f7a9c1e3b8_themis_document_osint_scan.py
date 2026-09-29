"""themis document: un informe puede ser de un escaneo de dominio

Un escaneo de exposición cloud no es un ``Scan`` (no tiene host que sondear),
así que su informe no podía guardarse como documento de Themis, que exigía
``scan_id``. El documento pasa a pertenecer a uno de los dos: un escaneo
normal (``scan_id``) o un escaneo de dominio (``osint_scan_id``). Una
restricción de comprobación exige exactamente uno de los dos.

Revision ID: d5f7a9c1e3b8
Revises: c4e8a1b7d2f6
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f7a9c1e3b8'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1b7d2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ThemisDocument', sa.Column('osint_scan_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_ThemisDocument_osint_scan_id'), 'ThemisDocument', ['osint_scan_id'],
                    unique=False)
    op.create_foreign_key('ThemisDocument_osint_scan_id_fkey', 'ThemisDocument', 'OsintScan',
                          ['osint_scan_id'], ['id'], ondelete='CASCADE')
    op.alter_column('ThemisDocument', 'scan_id', existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint('ck_themisdocument_one_parent', 'ThemisDocument',
                               '(scan_id IS NULL) <> (osint_scan_id IS NULL)')


def downgrade() -> None:
    """Downgrade schema.

    Los informes de escaneos de dominio no caben en el esquema anterior, que
    exige ``scan_id``: se borran antes de volver a hacerlo obligatorio, junto
    con su fila de ``Document``. Las dos filas se borran en una sola sentencia
    porque ``ThemisDocument.id`` apunta a ``Document.id``: la clave ajena se
    comprueba al terminar la sentencia, cuando ya no queda ninguna de las dos.
    """
    op.drop_constraint('ck_themisdocument_one_parent', 'ThemisDocument', type_='check')
    op.execute('WITH removed AS (DELETE FROM "ThemisDocument" WHERE osint_scan_id IS NOT NULL '
               'RETURNING id) DELETE FROM "Document" WHERE id IN (SELECT id FROM removed)')
    op.alter_column('ThemisDocument', 'scan_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('ThemisDocument_osint_scan_id_fkey', 'ThemisDocument', type_='foreignkey')
    op.drop_index(op.f('ix_ThemisDocument_osint_scan_id'), table_name='ThemisDocument')
    op.drop_column('ThemisDocument', 'osint_scan_id')
