"""asset group: los grupos de hosts que se analizan juntos

Un grupo define una red por su rango CIDR, para que el motor pueda razonar
sobre varios hosts a la vez (riesgo de movimiento lateral). La pertenencia de un
host a un grupo se calcula por su dirección, así que no hay tabla de miembros.

Revision ID: c4e8a1b7d2f6
Revises: b3d9f1a2c8e4
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a1b7d2f6'
down_revision: Union[str, Sequence[str], None] = 'b3d9f1a2c8e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'AssetGroup',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('cidr', sa.String(length=43), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_assetgroup_user_name'),
    )
    op.create_index(op.f('ix_AssetGroup_user_id'), 'AssetGroup', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_AssetGroup_user_id'), table_name='AssetGroup')
    op.drop_table('AssetGroup')
