"""iris: ingesta por eventos (IrisMailboxSubscription)

Gmail y Microsoft Graph pueden avisar en cuanto llega un correo, en vez de
esperar al siguiente sondeo. Cada conexión de buzón con los eventos encendidos
tiene una suscripción en el proveedor, y esta tabla guarda su estado: cuándo
caduca, el secreto con que Graph firma los avisos (su huella SHA-256) y lo
necesario para descartar avisos repetidos y agrupar ráfagas.

Revision ID: d8f2b4c6e0a5
Revises: c7e1a3b5d9f4
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8f2b4c6e0a5'
down_revision: Union[str, Sequence[str], None] = 'c7e1a3b5d9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisMailboxSubscription',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('client_state_sha256', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_history_id', sa.String(length=40), nullable=True),
        sa.Column('last_event_at', sa.DateTime(), nullable=True),
        sa.Column('events_received', sa.Integer(), nullable=False),
        sa.Column('last_renewed_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['IrisMailboxConnection.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id'),
    )
    op.create_index('ix_iris_mailbox_subscription_external_id', 'IrisMailboxSubscription',
                    ['external_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_iris_mailbox_subscription_external_id', table_name='IrisMailboxSubscription')
    op.drop_table('IrisMailboxSubscription')
