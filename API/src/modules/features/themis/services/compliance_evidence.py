"""
Lo que Themis aporta a Eunomia como evidencia automática de la gestión de vulnerabilidades.

Se registra en ``EvidenceProviderRegistry`` desde ``themis/__init__.py``. Solo consulta los
escaneos del dueño efectivo: abrir los de los miembros sería otra excepción a «la organización
comparte plan, no datos».
"""

from datetime import date, datetime, timedelta

from src.modules.features.eunomia import AutomaticEvidence

#: Días sin un escaneo terminado a partir de los cuales deja de ser «reciente».
STALE_AFTER_DAYS = 30

#: Controles a los que aporta, por marco.
CONTROLS = {
    "nis2": ("RE.6.6", "RE.6.10"),
    "ens": ("op.exp.4", "op.mon.3"),
    "iso27001": ("A.8.8",),
}

_LINK = "/themis/escaneos"


def collect_vulnerability_evidence(owner_user_id: int, framework_key: str, identifier: str,
                                   summary: dict, today: date) -> list[AutomaticEvidence]:
    """Convierte el resumen de escaneos en evidencias legibles.

    Args:
        owner_user_id: Dueño efectivo; no se usa más que para quien llama.
        framework_key: Marco del control.
        identifier: Control.
        summary: Resultado de ``ScanHistoryManager.get_vulnerability_management_summary``.
        today: Fecha de referencia, para contar los días.

    Returns:
        list[AutomaticEvidence]: Una evidencia «sin escaneos» si no ha terminado ninguno; si no,
            el último escaneo, los escaneos programados y los hallazgos críticos abiertos.
    """
    last: datetime | None = summary["lastFinishedAt"]
    if last is None:
        return [AutomaticEvidence(
            "Escaneos de vulnerabilidades", "Todavía no se ha terminado ningún escaneo.",
            link=_LINK, status="missing")]
    days = (today - last.date()).days
    is_stale = last.date() < today - timedelta(days=STALE_AFTER_DAYS)
    scheduled = summary["activeScheduledScans"]
    critical = summary["openCritical"]
    return [
        AutomaticEvidence(
            "Último escaneo", f"Terminó el {last.strftime('%d/%m/%Y')} (hace {days} días).",
            last.date(), _LINK, "warning" if is_stale else "ok"),
        AutomaticEvidence(
            "Escaneos programados",
            f"{scheduled} activo(s)." if scheduled else "No hay ningún escaneo programado activo.",
            None, _LINK, "ok"),
        AutomaticEvidence(
            "Hallazgos críticos abiertos",
            f"{critical} crítico(s) abierto(s) de {summary['openFindings']} hallazgos abiertos.",
            last.date(), _LINK, "warning" if critical else "ok"),
    ]
