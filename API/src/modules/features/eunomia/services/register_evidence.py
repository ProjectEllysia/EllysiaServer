"""
Un registro con fichas como evidencia automática de los requisitos que lo exigen.

Eunomia es el único proveedor que conoce sus propios registros: se da de alta en su propio
``EvidenceProviderRegistry`` una vez por tipo de registro, con los controles que la definición
declara.
"""

from datetime import date

from src.modules.infrastructure.session import build_repository

from ..repositories import EunomiaRecordRepository
from .providers import AutomaticEvidence, EvidenceProviderRegistry
from .registers import RegisterType, compute_deadlines, load_registers
from src.modules.shared import utcnow_naive


def _collect(register: RegisterType):
    """Fabrica la función que resume un registro para un dueño."""
    def collect(owner_user_id: int, framework_key: str, identifier: str) -> list[AutomaticEvidence]:
        rows = build_repository(EunomiaRecordRepository).list_for_register(owner_user_id, register.key)
        link = f"/eunomia/registros/{register.key}"
        if not rows:
            return [AutomaticEvidence(register.title, "El registro está vacío.", link=link, status="missing")]
        now = utcnow_naive()
        overdue = sum(1 for row in rows for item in compute_deadlines(register, dict(row.values), now)
                      if item["status"] == "overdue")
        last = max(row.updated_at for row in rows)
        summary = f"{len(rows)} ficha(s)." + (f" {overdue} plazo(s) vencido(s) sin cumplir." if overdue else "")
        return [AutomaticEvidence(register.title, summary, last.date() if last else date.today(), link,
                                  "warning" if overdue else "ok")]
    return collect


def register_providers() -> None:
    """Da de alta un proveedor por cada tipo de registro que declara requisitos."""
    for register in load_registers():
        if register.controls:
            EvidenceProviderRegistry.register(
                f"eunomia.register.{register.key}", name=register.title, controls=register.controls,
                collect=_collect(register))
