"""iris: campañas (IrisCampaign, IrisCampaignMember) y huellas para agruparlas

Un analista investigaba por separado cada mensaje de una misma campaña. Los
IOCs de cada análisis ya estaban indexados (``IrisIndicator``); faltaba lo que
no es un IOC pero delata una campaña —el asunto normalizado, la plantilla del
cuerpo y la marca suplantada— y una tabla que agrupe los análisis parecidos.

Revision ID: a8c3e5f7b9d1
Revises: d7f1a3c5e9b2
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a8c3e5f7b9d1'
down_revision: Union[str, Sequence[str], None] = 'd7f1a3c5e9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('IrisAnalysis', sa.Column('subject_fingerprint', sa.String(length=64), nullable=True))
    op.add_column('IrisAnalysis', sa.Column('template_fingerprint', sa.String(length=64), nullable=True))
    op.add_column('IrisAnalysis', sa.Column(
        'impersonated_brands', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
    ))
    op.create_index('ix_iris_analysis_user_subject_fingerprint', 'IrisAnalysis',
                    ['user_id', 'subject_fingerprint'])
    op.create_index('ix_iris_analysis_user_template_fingerprint', 'IrisAnalysis',
                    ['user_id', 'template_fingerprint'])
    op.create_table(
        'IrisCampaign',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_iris_campaign_user_id', 'IrisCampaign', ['user_id'])
    op.create_table(
        'IrisCampaignMember',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.Column('similarity', sa.Float(), nullable=False),
        sa.Column('matched_signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['IrisCampaign.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['analysis_id'], ['IrisAnalysis.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('analysis_id', name='uq_iris_campaign_member_analysis'),
    )
    op.create_index('ix_iris_campaign_member_campaign_id', 'IrisCampaignMember', ['campaign_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_iris_campaign_member_campaign_id', table_name='IrisCampaignMember')
    op.drop_table('IrisCampaignMember')
    op.drop_index('ix_iris_campaign_user_id', table_name='IrisCampaign')
    op.drop_table('IrisCampaign')
    op.drop_index('ix_iris_analysis_user_template_fingerprint', table_name='IrisAnalysis')
    op.drop_index('ix_iris_analysis_user_subject_fingerprint', table_name='IrisAnalysis')
    op.drop_column('IrisAnalysis', 'impersonated_brands')
    op.drop_column('IrisAnalysis', 'template_fingerprint')
    op.drop_column('IrisAnalysis', 'subject_fingerprint')
