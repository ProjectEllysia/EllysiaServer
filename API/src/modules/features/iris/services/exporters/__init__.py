"""
Exportación de inteligencia de Iris para un SOC: JSON versionado, STIX 2.1 y MISP.

La exportación parte de un documento **neutro** (``ExportDocument``) que el
manager monta a partir de lo que Iris guarda —el índice de IOCs, las reglas
que penalizaron, la corrección del analista y la campaña— y que cada formato
traduce a su manera. Así los tres formatos dicen siempre lo mismo, y añadir
uno es escribir un renderizador más.

Cada indicador lleva su **fuente**, su **confianza**, **cuándo empieza y deja
de ser válido** y de qué análisis sale, que es lo que un SIEM o un SOAR
necesita para no tratar un IOC viejo como si fuera de hoy.

Todo el paquete es puro: sin base de datos ni red.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

#: Versión del esquema del JSON propio. Cambia solo si cambia algo que rompe a
#: quien lo lee (un campo que desaparece o cambia de tipo); añadir campos no.
EXPORT_SCHEMA_VERSION = "iris-export/1"

#: Nombre con el que Ellysia firma lo que exporta (``created_by`` en STIX,
#: ``Orgc`` en MISP, ``createdBy`` en el JSON).
PRODUCER_NAME = "Ellysia Iris"


class ExportFormat(StrEnum):
    """Formato de exportación.

    - ``JSON``: el JSON versionado de Iris (``EXPORT_SCHEMA_VERSION``).
    - ``STIX``: un *bundle* STIX 2.1.
    - ``MISP``: un evento MISP en su formato JSON de importación.
    """

    JSON = "json"
    STIX = "stix"
    MISP = "misp"


@dataclass(frozen=True)
class ExportedIndicator:
    """Un IOC tal como se exporta.

    Attributes:
        kind: ``domain``, ``url``, ``ip``, ``email`` o ``hash`` (SHA-256).
        value: El valor, sin desactivar.
        confidence: Confianza de 0 a 100 (ver ``indicator_confidence``).
        verdict: Peor veredicto de los análisis en que aparece
            (``Phishing``, ``Suspicious`` o ``Legitimate``).
        valid_from: Primera vez que se vio.
        valid_until: Hasta cuándo se considera vigente.
        analysis_ids: Análisis en los que aparece, ordenados.
    """

    kind: str
    value: str
    confidence: int
    verdict: str
    valid_from: datetime
    valid_until: datetime
    analysis_ids: Tuple[int, ...]


@dataclass(frozen=True)
class ExportedFinding:
    """Una regla que penalizó, con su identidad estable.

    Attributes:
        rule_id: Id estable de la regla (``iris.content.image_text_phishing``);
            vacío en análisis anteriores a la taxonomía.
        name: Nombre legible de la regla.
        category: Categoría de la regla.
        severity: Severidad declarada (``low``…``critical``), o vacía.
        score: Penalización (negativa).
        mitre_techniques: Técnicas MITRE ATT&CK asociadas (``T1566.002``…).
        analysis_id: Análisis del que sale.
    """

    rule_id: str
    name: str
    category: str
    severity: str
    score: float
    mitre_techniques: Tuple[str, ...]
    analysis_id: int


@dataclass(frozen=True)
class ExportedAnalysis:
    """Resumen de un análisis dentro de la exportación.

    Attributes:
        analysis_id: Id del análisis.
        title: Título, o vacío.
        verdict: Veredicto.
        confidence: Confianza ordinal de Iris (``high``/``medium``/``low``) o vacía.
        received_at: Cuándo se recibió.
        analyst_label: Última corrección del analista (``phishing``,
            ``legitimate``…), o vacía si no la hay.
    """

    analysis_id: int
    title: str
    verdict: str
    confidence: str
    received_at: datetime
    analyst_label: str = ""


@dataclass(frozen=True)
class ExportDocument:
    """Lo que se exporta, sin formato.

    Attributes:
        subject_kind: ``analysis`` (un análisis) o ``campaign`` (una campaña).
        subject_id: Id del análisis o de la campaña.
        title: Nombre legible.
        verdict: Peor veredicto de los análisis incluidos.
        confidence: Confianza global de 0 a 100.
        first_seen: Recepción del análisis más antiguo.
        last_seen: Recepción del más reciente.
        generated_at: Cuándo se genera la exportación.
        detector_version: Versión del catálogo de reglas, o vacía.
        producer_version: Versión de Ellysia.
        analyses: Análisis incluidos.
        indicators: IOCs, ordenados por tipo y valor.
        findings: Reglas que penalizaron.
        campaign_id: Campaña a la que pertenece lo exportado, o ``None``.
        campaign_label: Su rótulo, o vacío.
    """

    subject_kind: str
    subject_id: int
    title: str
    verdict: str
    confidence: int
    first_seen: datetime
    last_seen: datetime
    generated_at: datetime
    detector_version: str
    producer_version: str
    analyses: Tuple[ExportedAnalysis, ...]
    indicators: Tuple[ExportedIndicator, ...]
    findings: Tuple[ExportedFinding, ...] = field(default_factory=tuple)
    campaign_id: Optional[int] = None
    campaign_label: str = ""


#: Confianza (0-100) de un indicador según el veredicto y la confianza de Iris
#: en él. Un IOC de un correo legítimo no es malicioso: se exporta, porque un
#: SOC también quiere saber lo que ya se vio limpio, pero con confianza baja.
_CONFIDENCE_BY_VERDICT = {
    "Phishing": {"high": 90, "medium": 70, "low": 50},
    "Suspicious": {"high": 60, "medium": 45, "low": 30},
    "Legitimate": {"high": 10, "medium": 10, "low": 10},
}
_DEFAULT_CONFIDENCE = 30

_VERDICT_ORDER = ("Legitimate", "Suspicious", "Phishing")


def indicator_confidence(verdict: Optional[str], confidence: Optional[str]) -> int:
    """Confianza de 0 a 100 de un indicador.

    Args:
        verdict: Veredicto del análisis del que sale.
        confidence: Confianza ordinal de Iris en ese veredicto (``high``,
            ``medium``, ``low``), o ``None`` si no se evaluó.

    Returns:
        int: La confianza; ``_DEFAULT_CONFIDENCE`` si el veredicto no se conoce.
            Sin confianza evaluada se toma la del nivel ``low``.
    """
    by_level = _CONFIDENCE_BY_VERDICT.get(verdict or "")
    if by_level is None:
        return _DEFAULT_CONFIDENCE
    return by_level.get(confidence or "", by_level["low"])


def worst_verdict(verdicts: List[Optional[str]]) -> str:
    """El peor de varios veredictos.

    Args:
        verdicts: Veredictos; los ``None`` o desconocidos se ignoran.

    Returns:
        str: ``Phishing``, ``Suspicious`` o ``Legitimate``; ``Legitimate`` si
            no había ninguno conocido.
    """
    known = [verdict for verdict in verdicts if verdict in _VERDICT_ORDER]
    return max(known, key=_VERDICT_ORDER.index) if known else "Legitimate"


def render_export(document: ExportDocument, export_format: ExportFormat, is_defanged: bool = True) -> Dict[str, Any]:
    """Traduce el documento neutro al formato pedido.

    Args:
        document: Lo que se exporta.
        export_format: Formato de salida.
        is_defanged: Solo para ``JSON``: desactivar los valores
            (``hxxp``, ``[.]``) para que nadie los abra por accidente. STIX y
            MISP los llevan siempre sin desactivar, porque un patrón o un
            atributo desactivado no casa con nada. Por defecto ``True``.

    Returns:
        dict: El documento en el formato pedido, listo para serializar a JSON.
    """
    return _RENDERERS[export_format](document, is_defanged)


def defang_value(kind: str, value: str) -> str:
    """Desactiva un indicador para que no se pueda abrir por accidente.

    Args:
        kind: Tipo de indicador; los hashes no se tocan.
        value: El valor.

    Returns:
        str: ``http`` → ``hxxp``, ``.`` → ``[.]`` y ``@`` → ``[@]``.
    """
    if kind == "hash":
        return value
    defanged = value.replace("https://", "hxxps://").replace("http://", "hxxp://")
    return defanged.replace(".", "[.]").replace("@", "[@]")


def _render_json(document: ExportDocument, is_defanged: bool) -> Dict[str, Any]:
    """Renderizador de ``ExportFormat.JSON``; import tardío porque ``native`` importa este paquete."""
    from .native import render_native
    return render_native(document, is_defanged)


def _render_stix(document: ExportDocument, is_defanged: bool) -> Dict[str, Any]:
    """Renderizador de ``ExportFormat.STIX``; ``is_defanged`` no aplica."""
    from .stix import render_stix
    return render_stix(document)


def _render_misp(document: ExportDocument, is_defanged: bool) -> Dict[str, Any]:
    """Renderizador de ``ExportFormat.MISP``; ``is_defanged`` no aplica."""
    from .misp import render_misp
    return render_misp(document)


_RENDERERS: Dict[ExportFormat, Callable[[ExportDocument, bool], Dict[str, Any]]] = {
    ExportFormat.JSON: _render_json,
    ExportFormat.STIX: _render_stix,
    ExportFormat.MISP: _render_misp,
}
