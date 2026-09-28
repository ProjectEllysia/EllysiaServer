"""iris: webhooks firmados (IrisWebhookSubscription, IrisWebhookDelivery)

Iris no podía avisar a ningún otro sistema. Un usuario da de alta un webhook
(URL https, eventos y un secreto de firma cifrado en reposo) y cada evento
queda como una entrega con sus intentos, deduplicada por su id de evento.

Revision ID: a5c9e1f3b7d2
Revises: f4b8d0e2a6c7
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a5c9e1f3b7d2'
down_revision: Union[str, Sequence[str], None] = 'f4b8d0e2a6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'IrisWebhookSubscription',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('event_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('disabled_reason', sa.String(length=20), nullable=True),
        sa.Column('disabled_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_iris_webhook_subscription_user_id', 'IrisWebhookSubscription', ['user_id'])
    op.create_table(
        'IrisWebhookDelivery',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=40), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.String(length=120), nullable=True),
        sa.Column('last_response_excerpt', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['subscription_id'], ['IrisWebhookSubscription.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subscription_id', 'event_id', name='uq_iris_webhook_delivery_subscription_event'),
    )
    op.create_index('ix_iris_webhook_delivery_status_next_attempt', 'IrisWebhookDelivery',
                    ['status', 'next_attempt_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_iris_webhook_delivery_status_next_attempt', table_name='IrisWebhookDelivery')
    op.drop_table('IrisWebhookDelivery')
    op.drop_index('ix_iris_webhook_subscription_user_id', table_name='IrisWebhookSubscription')
    op.drop_table('IrisWebhookSubscription')
