"""aegis: retira del perfil de Aegis las columnas de datos de empresa

Ya viven en ``CompanyProfile`` (ver la migración anterior). Se separan en dos
revisiones para que la copia de datos no comparta paso con el borrado.

Revision ID: a9c1d3e5f7b8
Revises: f8b0c2d4e6a7
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a9c1d3e5f7b8'
down_revision: Union[str, Sequence[str], None] = 'f8b0c2d4e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DROPPED = (
    "company", "contact_email", "company_size", "jurisdiction", "sector",
    "work_model", "employee_count", "brand_logo",
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("AegisOrgProfile"):
        return
    present = {column["name"] for column in inspector.get_columns("AegisOrgProfile")}
    with op.batch_alter_table("AegisOrgProfile") as batch:
        for column in _DROPPED:
            if column in present:
                batch.drop_column(column)


def downgrade() -> None:
    """Vuelve a crear las columnas y las rellena desde ``CompanyProfile``."""
    with op.batch_alter_table("AegisOrgProfile") as batch:
        batch.add_column(sa.Column("company", sa.String(128), nullable=True))
        batch.add_column(sa.Column("contact_email", sa.String(128), nullable=True))
        batch.add_column(sa.Column("company_size", sa.String(16), nullable=True))
        batch.add_column(sa.Column("jurisdiction", sa.String(128), nullable=True))
        batch.add_column(sa.Column("sector", sa.String(128), nullable=True))
        batch.add_column(sa.Column("work_model", sa.String(16), nullable=True))
        batch.add_column(sa.Column("employee_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("brand_logo", sa.Text(), nullable=True))
    pairs = {
        "company": "legal_name", "contact_email": "security_contact", "company_size": "company_size",
        "jurisdiction": "jurisdiction", "sector": "sector", "work_model": "work_model",
        "employee_count": "employee_count", "brand_logo": "brand_logo",
    }
    for target, source in pairs.items():
        op.execute(
            f"""
            UPDATE "AegisOrgProfile"
               SET {target} = (SELECT c.{source} FROM "CompanyProfile" c
                                WHERE c.user_id = "AegisOrgProfile".user_id)
            """
        )
