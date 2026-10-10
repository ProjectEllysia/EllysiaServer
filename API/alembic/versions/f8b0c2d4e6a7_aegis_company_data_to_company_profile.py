"""aegis: los datos de empresa del perfil de Aegis pasan al perfil de empresa

Para cada ``AegisOrgProfile`` crea el ``CompanyProfile`` **del mismo usuario**
con su razón social, contacto, tamaño, jurisdicción, sector, modelo de trabajo,
plantilla y logo; si ese usuario ya tenía perfil de empresa, solo se rellenan
los campos que tuviera vacíos, sin pisar nada. Es una migración de datos: las
columnas de ``AegisOrgProfile`` se retiran en la siguiente.

También se copian los de los miembros de una organización: mientras estén en
ella sus datos propios no se ven, y vuelven a aplicarse si la dejan.

Revision ID: f8b0c2d4e6a7
Revises: e7a9b1c3d5f6
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f8b0c2d4e6a7'
down_revision: Union[str, Sequence[str], None] = 'e7a9b1c3d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: columna de CompanyProfile -> columna de AegisOrgProfile de la que sale.
_COLUMNS: dict[str, str] = {
    "legal_name": "company",
    "sector": "sector",
    "company_size": "company_size",
    "employee_count": "employee_count",
    "jurisdiction": "jurisdiction",
    "work_model": "work_model",
    "security_contact": "contact_email",
    "brand_logo": "brand_logo",
}


def _can_copy() -> bool:
    """Indica si hay algo que copiar: la tabla de origen y sus columnas existen."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("AegisOrgProfile") or not inspector.has_table("CompanyProfile"):
        return False
    present = {column["name"] for column in inspector.get_columns("AegisOrgProfile")}
    return set(_COLUMNS.values()) <= present


def upgrade() -> None:
    if not _can_copy():
        return

    # Un perfil de empresa nuevo para quien no lo tenía.
    columns = ", ".join(_COLUMNS)
    sources = ", ".join(
        f"NULLIF(a.{source}, '')" if source not in ("employee_count",) else f"a.{source}"
        for source in _COLUMNS.values()
    )
    op.execute(
        f"""
        INSERT INTO "CompanyProfile" (user_id, {columns}, created_at, updated_at)
        SELECT a.user_id, {sources}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
          FROM "AegisOrgProfile" a
         WHERE NOT EXISTS (SELECT 1 FROM "CompanyProfile" c WHERE c.user_id = a.user_id)
        """
    )

    # Quien ya tenía perfil de empresa conserva lo suyo; solo se completan huecos.
    for target, source in _COLUMNS.items():
        value = f"NULLIF(a.{source}, '')" if source != "employee_count" else f"a.{source}"
        op.execute(
            f"""
            UPDATE "CompanyProfile"
               SET {target} = (SELECT {value} FROM "AegisOrgProfile" a
                                WHERE a.user_id = "CompanyProfile".user_id)
             WHERE {target} IS NULL
               AND EXISTS (SELECT 1 FROM "AegisOrgProfile" a
                            WHERE a.user_id = "CompanyProfile".user_id)
            """
        )


def downgrade() -> None:
    """No deshace la copia: los datos ya estaban también en el perfil de Aegis."""
