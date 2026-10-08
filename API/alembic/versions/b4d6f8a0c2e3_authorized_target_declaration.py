"""authorized target: declaración del titular del sistema

Al autorizar un objetivo, el usuario declara que el sistema es suyo o que su
titular le ha autorizado a analizarlo. Se guarda la versión del texto que
aceptó y la IP desde la que lo hizo; la fecha ya la lleva ``created_at``. Las
entradas que ya existen se quedan sin declaración (siguen siendo válidas).

Revision ID: b4d6f8a0c2e3
Revises: a3c5e7f9b1d2
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d6f8a0c2e3'
down_revision: Union[str, Sequence[str], None] = 'a3c5e7f9b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('AuthorizedTarget', sa.Column('declaration_version', sa.String(length=32), nullable=True))
    op.add_column('AuthorizedTarget', sa.Column('declaration_ip', sa.String(length=45), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('AuthorizedTarget', 'declaration_ip')
    op.drop_column('AuthorizedTarget', 'declaration_version')
