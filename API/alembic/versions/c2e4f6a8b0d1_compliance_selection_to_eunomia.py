"""eunomia: la elección de marcos de Themis pasa a ser la adopción de Eunomia

Había dos elecciones de marcos con dos reglas: la de Themis (cada usuario elige y, si su
organización fija algo, manda la organización) y la nueva de Eunomia (los datos son del dueño
efectivo). Esta migración pasa cada elección existente a adopciones y retira la tabla antigua.

- Una fila de **organización** se convierte en adopciones del **dueño** de esa organización;
  gana sobre la fila propia del dueño, como ganaba hasta ahora.
- Una fila de **usuario** se convierte en adopciones de ese usuario. Si es miembro, quedan
  ocultas mientras siga en la organización, igual que el resto de sus datos propios.
- Cada marco se adopta en la versión vigente del catálogo, congelada aquí como literal. Una
  lista vacía no crea nada. La cuota no se comprueba: no se pierde una elección que ya existía.

Revision ID: c2e4f6a8b0d1
Revises: b1d3e5f7a9c0
Create Date: 2026-10-10 00:00:00.000000

"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c2e4f6a8b0d1'
down_revision: Union[str, Sequence[str], None] = 'b1d3e5f7a9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Versión vigente de cada marco cuando se escribió esta migración. Congelada: tiene que dar el
#: mismo resultado dentro de un año, cuando el catálogo haya publicado otras versiones.
_CURRENT_VERSION = {"iso27001": "2022", "ens": "rd-311-2022", "nis2": "2022-2555"}


def _owners_and_frameworks(connection) -> dict[int, list[str]]:
    """Qué marcos adopta cada dueño, resolviendo la prioridad de la organización."""
    organizations = {
        row.id: row.owner_user_id
        for row in connection.execute(sa.text('SELECT id, owner_user_id FROM "Organization"'))
    }
    rows = connection.execute(sa.text(
        'SELECT user_id, organization_id, frameworks FROM "ComplianceFrameworkSelection"'
    )).all()

    result: dict[int, list[str]] = {}
    for row in rows:
        if row.organization_id is not None and row.organization_id in organizations:
            result[organizations[row.organization_id]] = _as_list(row.frameworks)
    for row in rows:
        if row.user_id is not None and row.user_id not in result:
            result[row.user_id] = _as_list(row.frameworks)
    return result


def _as_list(value) -> list[str]:
    """``JSONB`` llega ya decodificado en PostgreSQL y como texto en otros motores."""
    loaded = json.loads(value) if isinstance(value, (str, bytes)) else value
    return [key for key in dict.fromkeys(loaded or []) if key in _CURRENT_VERSION]


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("ComplianceFrameworkSelection"):
        return

    if inspector.has_table("EunomiaFrameworkAdoption"):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for owner_user_id, frameworks in _owners_and_frameworks(connection).items():
            for key in frameworks:
                connection.execute(sa.text(
                    'INSERT INTO "EunomiaFrameworkAdoption" '
                    "(owner_user_id, framework_key, catalog_version, status, adopted_at, adopted_by_user_id) "
                    "SELECT :owner, :key, :version, 'active', :now, :owner "
                    'WHERE NOT EXISTS (SELECT 1 FROM "EunomiaFrameworkAdoption" '
                    "WHERE owner_user_id = :owner AND framework_key = :key)"
                ), {"owner": owner_user_id, "key": key, "version": _CURRENT_VERSION[key], "now": now})

    op.drop_table("ComplianceFrameworkSelection")


def downgrade() -> None:
    """Vuelve a crear la tabla vacía: la elección ya vive en las adopciones."""
    op.create_table(
        "ComplianceFrameworkSelection",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("User.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("Organization.id", ondelete="CASCADE"),
                  nullable=True, unique=True),
        sa.Column("frameworks", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("(user_id IS NULL) <> (organization_id IS NULL)",
                           name="ck_complianceframeworkselection_one_owner"),
    )
