"""Host.ip_address a 45 caracteres para admitir IPv6 (#315)

Revision ID: 4673e0aaf802
Revises: b8e3c6f1a5d2
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4673e0aaf802'
down_revision: Union[str, Sequence[str], None] = 'b8e3c6f1a5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    ``Host.ip_address`` estaba declarada como ``String(15)`` —exactamente el
    máximo de una IPv4 y de nada más— con un docstring que prometía admitir
    también IPv6. Una dirección IPv6 completa sin comprimir ocupa hasta 45
    caracteres (``"0000:0000:0000:0000:0000:0000:0000:0000"``), así que la
    columna se ensancha a ese límite para que la declaración sea cierta.

    Ampliar un ``varchar`` no reescribe la tabla en PostgreSQL (es un cambio
    de metadatos) y no toca ni un dato existente.
    """
    op.alter_column(
        'Host', 'ip_address',
        existing_type=sa.String(length=15),
        type_=sa.String(length=45),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema.

    Estrechar la columna sí puede perder datos: cualquier IPv6 guardada tras
    la subida mide más de 15 caracteres. Se trunca explícitamente antes de
    alterar el tipo, en vez de dejar que la base de datos falle a mitad.
    """
    op.execute('UPDATE "Host" SET ip_address = left(ip_address, 15)')
    op.alter_column(
        'Host', 'ip_address',
        existing_type=sa.String(length=45),
        type_=sa.String(length=15),
        existing_nullable=False,
    )
