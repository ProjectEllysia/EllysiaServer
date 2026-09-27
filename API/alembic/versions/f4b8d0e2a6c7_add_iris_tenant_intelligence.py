"""iris: inteligencia compartida en una organización (IrisTenantProfile, IrisTenantConsent)

Toda la inteligencia de Iris era por usuario. El dueño de una organización
puede activar que sus miembros compartan agregados anonimizados de
indicadores; cada miembro da o retira su consentimiento.

Revision ID: f4b8d0e2a6c7
Revises: e3a7c9d1f5b6
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4b8d0e2a6c7'
down_revision: Union[str, Sequence[str], None] = 'e3a7c9d1f5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisTenantProfile',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('is_sharing_enabled', sa.Boolean(), nullable=False),
        sa.Column('changed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('protected_domains', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('protected_brands', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['Organization.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_user_id'], ['User.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id'),
    )
    op.create_table(
        'IrisTenantConsent',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('consented_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['Organization.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_iris_tenant_consent_organization_id', 'IrisTenantConsent', ['organization_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_iris_tenant_consent_organization_id', table_name='IrisTenantConsent')
    op.drop_table('IrisTenantConsent')
    op.drop_table('IrisTenantProfile')
