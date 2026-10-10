"""
Lo que Hygeia aporta a Eunomia como evidencia automática del inventario de activos.

Se registra en ``EvidenceProviderRegistry`` desde ``hygeia/__init__.py``.
"""

from src.modules.features.eunomia import AutomaticEvidence

#: Controles a los que aporta, por marco.
CONTROLS = {
    "nis2": ("RE.12.2", "RE.12.4"),
    "ens": ("op.exp.1",),
    "iso27001": ("A.5.9",),
}

_LINK = "/hygeia/activos"


def summarize_inventory(summary: dict) -> list[AutomaticEvidence]:
    """Convierte las cifras del parque en evidencias legibles.

    Args:
        summary: Resultado de ``HygeiaAssetManager.get_inventory_summary``.

    Returns:
        list[AutomaticEvidence]: Una evidencia «sin activos» si no hay ninguno; si no, el
            número de activos con su estado de reporte y la fecha del último inventario de
            software.
    """
    if not summary["assets"]:
        return [AutomaticEvidence(
            "Inventario de activos", "No hay activos monitorizados con un agente de Hygeia.",
            link=_LINK, status="missing")]
    silent = summary["silent"]
    items = [AutomaticEvidence(
        "Activos monitorizados",
        f"{summary['assets']} activo(s); {summary['reportingRecently']} han reportado en la última semana"
        + (f" y {silent} no." if silent else "."),
        None, _LINK, "warning" if silent else "ok")]
    last = summary["lastInventoryAt"]
    if last is not None:
        items.append(AutomaticEvidence(
            "Inventario de software", f"{summary['withInventory']} activo(s) han reportado el software instalado.",
            last.date(), _LINK, "ok"))
    return items
