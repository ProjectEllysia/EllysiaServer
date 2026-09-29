"""iris: buzones compartidos de la organización, IMAP, cuentas de servicio y varias carpetas

- IrisMailboxConnection.kind (personal | shared) y organization_id: un buzón
  compartido pertenece a una organización. Las conexiones existentes son
  personales.
- IrisMailboxConnection.auth_mode (oauth | service_account | imap) y los
  datos IMAP (servidor, puerto, usuario y contraseña cifrada). refresh_token
  pasa a admitir NULL: solo lo tienen las conexiones OAuth.
- IrisMailboxConnection.additional_folders: carpetas vigiladas además de la
  principal ([] en las existentes).
- IrisMailboxMember: quién ve (viewer) o administra (manager) cada buzón
  compartido.
- Atributo ABAC iris_shared_mailbox: se concede a los role_user existentes,
  igual que el resto de atributos por defecto, para que el administrador lo
  pueda retirar. Además del atributo, conectar un buzón compartido exige ser
  el dueño de la organización.

Revision ID: e9a3c5d7f1b6
Revises: d8f2b4c6e0a5
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e9a3c5d7f1b6'
down_revision: Union[str, Sequence[str], None] = 'd8f2b4c6e0a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Nombre del atributo, congelado aquí como literal (una migración no importa
#: del código de la aplicación, que puede cambiar después).
_ATTRIBUTE = "iris_shared_mailbox"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('IrisMailboxConnection', sa.Column(
        'kind', sa.String(length=16), nullable=False, server_default='personal'))
    op.add_column('IrisMailboxConnection', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_iris_mailbox_connection_organization', 'IrisMailboxConnection', 'Organization',
                          ['organization_id'], ['id'], ondelete='CASCADE')
    op.add_column('IrisMailboxConnection', sa.Column(
        'auth_mode', sa.String(length=20), nullable=False, server_default='oauth'))
    op.add_column('IrisMailboxConnection', sa.Column('imap_host', sa.String(length=255), nullable=True))
    op.add_column('IrisMailboxConnection', sa.Column('imap_port', sa.Integer(), nullable=True))
    op.add_column('IrisMailboxConnection', sa.Column('imap_username', sa.String(length=320), nullable=True))
    op.add_column('IrisMailboxConnection', sa.Column('imap_password', sa.Text(), nullable=True))
    op.add_column('IrisMailboxConnection', sa.Column(
        'additional_folders', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[]'::jsonb")))
    op.alter_column('IrisMailboxConnection', 'refresh_token', existing_type=sa.Text(), nullable=True)

    op.create_table(
        'IrisMailboxMember',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('access', sa.String(length=16), nullable=False),
        sa.Column('granted_by_user_id', sa.Integer(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['IrisMailboxConnection.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by_user_id'], ['User.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'user_id', name='uq_iris_mailbox_member_connection_user'),
    )
    op.create_index('ix_iris_mailbox_member_user_id', 'IrisMailboxMember', ['user_id'])

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
    """Downgrade schema.

    Los buzones compartidos e IMAP no caben en el esquema anterior (no tienen
    refresh token), así que se borran antes de volver a exigirlo.
    """
    op.execute(f"""DELETE FROM "UserAttribute" WHERE attribute_name = '{_ATTRIBUTE}'""")
    op.drop_index('ix_iris_mailbox_member_user_id', table_name='IrisMailboxMember')
    op.drop_table('IrisMailboxMember')
    op.execute("""DELETE FROM "IrisMailboxConnection" WHERE auth_mode <> 'oauth' OR refresh_token IS NULL""")
    op.alter_column('IrisMailboxConnection', 'refresh_token', existing_type=sa.Text(), nullable=False)
    op.drop_column('IrisMailboxConnection', 'additional_folders')
    op.drop_column('IrisMailboxConnection', 'imap_password')
    op.drop_column('IrisMailboxConnection', 'imap_username')
    op.drop_column('IrisMailboxConnection', 'imap_port')
    op.drop_column('IrisMailboxConnection', 'imap_host')
    op.drop_column('IrisMailboxConnection', 'auth_mode')
    op.drop_constraint('fk_iris_mailbox_connection_organization', 'IrisMailboxConnection', type_='foreignkey')
    op.drop_column('IrisMailboxConnection', 'organization_id')
    op.drop_column('IrisMailboxConnection', 'kind')
