"""iris: acciones sobre el buzón conectado (IrisActionAudit, permiso iris_mailbox_action)

Iris puede poner en cuarentena, marcar, mandar a spam o a la papelera un
correo de un buzón conectado, siempre a petición del usuario y con auditoría.

- IrisActionAudit: una fila por acción y por deshacer.
- IrisMailboxConnection.remediation_enabled: si al conectar se pidió permiso de
  escritura. Las conexiones que ya existían quedan en solo lectura (false).
- Atributo ABAC iris_mailbox_action: se concede a los role_user existentes,
  igual que el resto de atributos por defecto (ver f1a2b3c4d5e6), para que el
  administrador lo pueda retirar a quien no deba actuar sobre su buzón.

Revision ID: c7e1a3b5d9f4
Revises: b6d0f2a4c8e3
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7e1a3b5d9f4'
down_revision: Union[str, Sequence[str], None] = 'b6d0f2a4c8e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Nombre del atributo, congelado aquí como literal (una migración no importa
#: del código de la aplicación, que puede cambiar después).
_ATTRIBUTE = "iris_mailbox_action"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('IrisMailboxConnection', sa.Column(
        'remediation_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'IrisActionAudit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_username', sa.String(length=150), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('analysis_id', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('provider_message_id', sa.String(length=255), nullable=False),
        sa.Column('provider_message_id_after', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=24), nullable=False),
        sa.Column('is_destructive', sa.Boolean(), nullable=False),
        sa.Column('is_rollback', sa.Boolean(), nullable=False),
        sa.Column('rollback_of_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('permission', sa.String(length=40), nullable=False),
        sa.Column('was_recommended', sa.Boolean(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=80), nullable=True),
        sa.Column('previous_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['User.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['connection_id'], ['IrisMailboxConnection.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['analysis_id'], ['IrisAnalysis.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rollback_of_id'], ['IrisActionAudit.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('actor_id', 'idempotency_key', name='uq_iris_action_audit_actor_idempotency'),
    )
    op.create_index('ix_iris_action_audit_analysis_id', 'IrisActionAudit', ['analysis_id'])
    op.create_index('ix_iris_action_audit_actor_id', 'IrisActionAudit', ['actor_id'])
    op.execute(
        f"""
        INSERT INTO "UserAttribute" (user_id, attribute_name)
        SELECT u.id, '{_ATTRIBUTE}'
          FROM "User" u
         WHERE u.role = 'role_user'
           AND NOT EXISTS (
               SELECT 1 FROM "UserAttribute" ua
                WHERE ua.user_id = u.id AND ua.attribute_name = '{_ATTRIBUTE}'
           )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"""DELETE FROM "UserAttribute" WHERE attribute_name = '{_ATTRIBUTE}'""")
    op.drop_index('ix_iris_action_audit_actor_id', table_name='IrisActionAudit')
    op.drop_index('ix_iris_action_audit_analysis_id', table_name='IrisActionAudit')
    op.drop_table('IrisActionAudit')
    op.drop_column('IrisMailboxConnection', 'remediation_enabled')
