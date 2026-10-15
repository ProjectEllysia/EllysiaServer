"""eunomia: categoría del sistema en la adopción de un marco

El ENS exige unas medidas u otras según la categoría del sistema (básica, media o alta). La
adopción guarda cuál es para calcular qué controles cuentan; es nula en las adopciones que ya
existen, que siguen exigiéndolo todo hasta que el dueño la elija.

Revision ID: a3c5e7b9d1f2
Revises: 043eb56bc866
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a3c5e7b9d1f2'
down_revision: Union[str, Sequence[str], None] = '043eb56bc866'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("EunomiaFrameworkAdoption") as batch:
        batch.add_column(sa.Column("system_category", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("EunomiaFrameworkAdoption") as batch:
        batch.drop_column("system_category")
