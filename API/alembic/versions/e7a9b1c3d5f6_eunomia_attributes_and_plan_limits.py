"""eunomia: atributos ABAC y topes de plan

Da a todos los usuarios existentes los cuatro atributos de Eunomia (una cuenta
nueva los recibe por ``DEFAULT_USER_ATTRIBUTES``) y siembra los topes de plan de
sus tres claves en las bases ya desplegadas.

Los valores de los topes son provisionales: los fija producto, y se editan
desde el panel de planes sin tocar esta migración.

Revision ID: e7a9b1c3d5f6
Revises: d6f8a0b2c4e5
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e7a9b1c3d5f6'
down_revision: Union[str, Sequence[str], None] = 'd6f8a0b2c4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Congelados como literal, igual que en la migración de atributos por defecto:
#: tienen que dar el mismo resultado dentro de un año.
_ATTRIBUTES: tuple[str, ...] = (
    "eunomia_create", "eunomia_read", "eunomia_update", "eunomia_delete",
)

#: (periodo, {plan: valor}). ``None`` es ilimitado. ``evidence_storage`` va en bytes.
_LIMITS: dict[str, tuple[str, dict[str, int | None]]] = {
    "eunomia.frameworks":       ("stock", {"freemium": 1, "bronze": 3, "silver": 6, "gold": None}),
    "eunomia.evidence_storage": ("stock", {"freemium": 104_857_600, "bronze": 1_073_741_824,
                                           "silver": 5_368_709_120, "gold": 21_474_836_480}),
    "eunomia.documents":        ("month", {"freemium": 2, "bronze": 10, "silver": 50, "gold": 200}),
}


def upgrade() -> None:
    for attribute in _ATTRIBUTES:
        op.execute(
            f"""
            INSERT INTO "UserAttribute" (user_id, attribute_name)
            SELECT u.id, '{attribute}'
              FROM "User" u
             WHERE u.role = 'role_user'
               AND NOT EXISTS (
                   SELECT 1 FROM "UserAttribute" ua
                    WHERE ua.user_id = u.id
                      AND ua.attribute_name = '{attribute}'
               )
            """
        )

    if not sa.inspect(op.get_bind()).has_table("PlanLimit"):
        return
    for limit_key, (period, values) in _LIMITS.items():
        for code, value in values.items():
            literal = "NULL" if value is None else str(value)
            op.execute(
                f"""
                INSERT INTO "PlanLimit" (plan_id, limit_key, scope, value, period)
                SELECT p.id, '{limit_key}', 'holder', {literal}, '{period}'
                  FROM "Plan" p
                 WHERE p.code = '{code}'
                   AND NOT EXISTS (
                       SELECT 1 FROM "PlanLimit" l
                        WHERE l.plan_id = p.id
                          AND l.limit_key = '{limit_key}'
                          AND l.scope = 'holder'
                   )
                """
            )


def downgrade() -> None:
    for attribute in _ATTRIBUTES:
        op.execute(f"""DELETE FROM "UserAttribute" WHERE attribute_name = '{attribute}'""")
    if sa.inspect(op.get_bind()).has_table("PlanLimit"):
        keys = ", ".join(f"'{key}'" for key in _LIMITS)
        op.execute(f"""DELETE FROM "PlanLimit" WHERE limit_key IN ({keys})""")
