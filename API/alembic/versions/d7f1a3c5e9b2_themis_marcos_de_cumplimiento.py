"""themis: marcos de cumplimiento elegidos por usuario u organización

Revision ID: d7f1a3c5e9b2
Revises: c4e6a8b0d2f3
Create Date: 2026-09-25 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd7f1a3c5e9b2'
down_revision: Union[str, Sequence[str], None] = 'c4e6a8b0d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea ``ComplianceFrameworkSelection``.

    Guarda qué marcos de cumplimiento (ISO 27001, ENS, NIS2) quiere ver un
    usuario o una organización en los informes de Lybra. Cada fila es de uno de
    los dos, nunca de ambos, y se borra con su dueño.
    """
    op.create_table(
        "ComplianceFrameworkSelection",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("frameworks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (organization_id IS NULL)",
            name="ck_complianceframeworkselection_one_owner",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["User.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["Organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("organization_id"),
    )


def downgrade() -> None:
    """Borra la tabla; las elecciones de marcos se pierden."""
    op.drop_table("ComplianceFrameworkSelection")
