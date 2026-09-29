"""iris: canal de reporte (IrisIntegrationToken y procedencia del análisis)

Un cliente de correo (complemento de Outlook o Gmail, extensión, script)
reporta un mensaje con un token de integración propio, distinto de la sesión
del usuario. El análisis guarda desde qué canal y con qué token llegó.

Revision ID: b6d0f2a4c8e3
Revises: a5c9e1f3b7d2
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d0f2a4c8e3'
down_revision: Union[str, Sequence[str], None] = 'a5c9e1f3b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisIntegrationToken',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('key_id', sa.String(length=16), nullable=False),
        sa.Column('secret_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_id'),
    )
    op.create_index('ix_iris_integration_token_user_id', 'IrisIntegrationToken', ['user_id'])
    op.add_column('IrisAnalysis', sa.Column('report_channel', sa.String(length=32), nullable=True))
    op.add_column('IrisAnalysis', sa.Column('integration_token_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_iris_analysis_integration_token_id', 'IrisAnalysis', 'IrisIntegrationToken',
        ['integration_token_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_iris_analysis_integration_token_id', 'IrisAnalysis', type_='foreignkey')
    op.drop_column('IrisAnalysis', 'integration_token_id')
    op.drop_column('IrisAnalysis', 'report_channel')
    op.drop_index('ix_iris_integration_token_user_id', table_name='IrisIntegrationToken')
    op.drop_table('IrisIntegrationToken')
