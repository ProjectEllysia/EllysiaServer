"""accounts: el valor de un tope de plan pasa a BIGINT

Un tope de almacenamiento va en bytes: 5 GiB son 5 368 709 120, más de lo que cabe en un INTEGER
de 32 bits de PostgreSQL. La migración que siembra los topes de Eunomia ya ensancha la columna
antes de insertar; esta revisión hace lo mismo para las bases que ya la habían pasado, y no hace
nada si la columna ya es BIGINT.

Revision ID: 043eb56bc866
Revises: c8e0a2b4d6f7
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '043eb56bc866'
down_revision: Union[str, Sequence[str], None] = 'c8e0a2b4d6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("PlanLimit"):
        return
    with op.batch_alter_table("PlanLimit") as batch:
        batch.alter_column("value", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    """No estrecha la columna: volver a 32 bits fallaría en cuanto hubiera un tope grande."""
