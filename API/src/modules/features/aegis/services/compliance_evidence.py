"""
Lo que Aegis aporta a Eunomia como evidencia automática de formación y concienciación.

Se registra en ``EvidenceProviderRegistry`` desde ``aegis/__init__.py``. Solo se cuentan las
campañas del dueño efectivo y solo en agregado: nunca un destinatario concreto.
"""

from src.modules.features.eunomia import AutomaticEvidence

#: Controles a los que aporta, por marco.
CONTROLS = {
    "nis2": ("RE.8.1", "RE.8.2"),
    "ens": ("mp.per.3", "mp.per.4"),
    "iso27001": ("A.6.3",),
}

#: Tasa de finalización por debajo de la cual la formación se considera floja.
LOW_COMPLETION = 0.5

_LINK = "/aegis/campanas"


def _percent(part: int, whole: int) -> int:
    """Porcentaje entero de ``part`` sobre ``whole``; 0 si ``whole`` es 0."""
    return round(100 * part / whole) if whole else 0


def summarize_awareness(summary: dict) -> list[AutomaticEvidence]:
    """Convierte las cifras de las campañas en evidencias legibles.

    Args:
        summary: Resultado de ``CampaignManager.get_awareness_summary``.

    Returns:
        list[AutomaticEvidence]: Una evidencia «sin campañas» si no hubo ninguna en la ventana;
            si no, el número de campañas y destinatarios, la finalización y el acierto.
    """
    if not summary["campaigns"]:
        return [AutomaticEvidence(
            "Campañas de concienciación", "No se ha lanzado ninguna campaña en los últimos 12 meses.",
            link=_LINK, status="missing")]
    recipients, completed = summary["recipients"], summary["completed"]
    completion = completed / recipients if recipients else 0.0
    return [
        AutomaticEvidence(
            "Campañas en los últimos 12 meses",
            f"{summary['campaigns']} campaña(s) enviadas a {recipients} destinatario(s).", None, _LINK, "ok"),
        AutomaticEvidence(
            "Participación", f"{_percent(completed, recipients)} % ha completado el quiz ({completed} de {recipients}).",
            None, _LINK, "warning" if completion < LOW_COMPLETION else "ok"),
        AutomaticEvidence(
            "Acierto", f"{_percent(summary['correctAnswers'], summary['answers'])} % de las respuestas fue correcta.",
            None, _LINK, "ok"),
    ]
