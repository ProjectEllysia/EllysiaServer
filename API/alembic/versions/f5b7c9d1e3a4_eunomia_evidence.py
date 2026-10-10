"""eunomia: evidencias, su contenido cifrado y sus enlaces con los controles

Tres tablas: la ficha de la evidencia, su contenido cifrado en reposo en fila aparte (1:1) y
los enlaces muchos a muchos con los controles que demuestra.

Revision ID: f5b7c9d1e3a4
Revises: e4a6b8c0d2f3
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f5b7c9d1e3a4'
down_revision: Union[str, Sequence[str], None] = 'e4a6b8c0d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'EunomiaEvidence',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=128), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.Column('expiry_notified_for', sa.Date(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('uploaded_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
    )
    op.create_index('ix_EunomiaEvidence_owner_user_id', 'EunomiaEvidence', ['owner_user_id'])
    op.create_table(
        'EunomiaEvidenceContent',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('evidence_id', sa.Integer(), sa.ForeignKey('EunomiaEvidence.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('content', sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        'EunomiaEvidenceLink',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('evidence_id', sa.Integer(), sa.ForeignKey('EunomiaEvidence.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('framework_key', sa.String(length=32), nullable=False),
        sa.Column('control_identifier', sa.String(length=128), nullable=False),
        sa.Column('linked_at', sa.DateTime(), nullable=False),
        sa.Column('linked_by_user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=True),
        sa.UniqueConstraint('evidence_id', 'framework_key', 'control_identifier', name='uq_eunomia_evidence_link'),
    )
    op.create_index('ix_eunomia_evidence_link_control', 'EunomiaEvidenceLink', ['framework_key', 'control_identifier'])


def downgrade() -> None:
    op.drop_index('ix_eunomia_evidence_link_control', table_name='EunomiaEvidenceLink')
    op.drop_table('EunomiaEvidenceLink')
    op.drop_table('EunomiaEvidenceContent')
    op.drop_index('ix_EunomiaEvidence_owner_user_id', table_name='EunomiaEvidence')
    op.drop_table('EunomiaEvidence')
