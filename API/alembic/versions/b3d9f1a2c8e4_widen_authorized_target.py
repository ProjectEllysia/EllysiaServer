"""authorized target: ensanchar target a 255 para dominios y recursos cloud

El registro de objetivos autorizados pasa a guardar, además de IP/CIDR,
dominios (hasta 253 caracteres) y recursos cloud ``proveedor:identificador``
(un ``azure:cuenta/contenedor`` supera los 64 antiguos). No hay tabla ni
columna nueva: la forma del objetivo se distingue por la propia cadena.

Revision ID: b3d9f1a2c8e4
Revises: a7c1e3f5b9d2
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d9f1a2c8e4'
down_revision: Union[str, Sequence[str], None] = 'a7c1e3f5b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('AuthorizedTarget') as batch_op:
        batch_op.alter_column(
            'target',
            existing_type=sa.String(length=64),
            type_=sa.String(length=255),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('AuthorizedTarget') as batch_op:
        batch_op.alter_column(
            'target',
            existing_type=sa.String(length=255),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
