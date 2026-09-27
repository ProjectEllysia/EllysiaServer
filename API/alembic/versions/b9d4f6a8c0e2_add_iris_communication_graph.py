"""iris: grafo de comunicación (IrisCommunicationEdge) y desviación de contacto

Cada análisis era independiente de los anteriores: Iris no sabía si el
remitente era alguien con quien el destinatario habla habitualmente. Las
aristas remitente→destinatario (solo metadatos, con retención corta) lo
permiten, y cada análisis guarda si su remitente imitaba a un contacto
habitual.

Revision ID: b9d4f6a8c0e2
Revises: a8c3e5f7b9d1
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b9d4f6a8c0e2'
down_revision: Union[str, Sequence[str], None] = 'a8c3e5f7b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('IrisAnalysis', sa.Column(
        'contact_deviation', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
    ))
    op.create_table(
        'IrisCommunicationEdge',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('sender_address', sa.String(length=320), nullable=False),
        sa.Column('sender_domain', sa.String(length=253), nullable=False),
        sa.Column('sender_display_name', sa.String(length=200), nullable=True),
        sa.Column('recipient_address', sa.String(length=320), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False),
        sa.Column('legitimate_count', sa.Integer(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'sender_address', 'recipient_address', 'kind',
                            name='uq_iris_communication_edge'),
    )
    op.create_index('ix_iris_communication_edge_user_sender', 'IrisCommunicationEdge',
                    ['user_id', 'sender_address'])
    op.create_index('ix_iris_communication_edge_last_seen_at', 'IrisCommunicationEdge', ['last_seen_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_iris_communication_edge_last_seen_at', table_name='IrisCommunicationEdge')
    op.drop_index('ix_iris_communication_edge_user_sender', table_name='IrisCommunicationEdge')
    op.drop_table('IrisCommunicationEdge')
    op.drop_column('IrisAnalysis', 'contact_deviation')
