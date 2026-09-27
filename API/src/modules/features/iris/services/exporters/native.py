"""JSON versionado de Iris (``EXPORT_SCHEMA_VERSION``)."""

from __future__ import annotations

from typing import Any, Dict

from . import EXPORT_SCHEMA_VERSION, PRODUCER_NAME, ExportDocument, defang_value
from .timestamps import format_timestamp


def render_native(document: ExportDocument, is_defanged: bool) -> Dict[str, Any]:
    """Traduce el documento al JSON propio de Iris.

    Es el formato para quien no usa STIX ni MISP: claves estables en
    ``camelCase`` y un ``schemaVersion`` que dice cómo leerlo.

    Args:
        document: Lo que se exporta.
        is_defanged: Si los valores van desactivados (``defanged: true`` en la
            salida lo deja dicho).

    Returns:
        dict: ``schemaVersion``, ``createdBy``, ``generatedAt``, ``defanged``,
            ``subject``, ``campaign``, ``analyses``, ``indicators`` y
            ``findings``.
    """
    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "createdBy": {"tool": PRODUCER_NAME, "version": document.producer_version,
                      "detectorVersion": document.detector_version or None},
        "generatedAt": format_timestamp(document.generated_at),
        "defanged": is_defanged,
        "subject": {
            "kind": document.subject_kind,
            "id": document.subject_id,
            "title": document.title,
            "verdict": document.verdict,
            "confidence": document.confidence,
            "firstSeen": format_timestamp(document.first_seen),
            "lastSeen": format_timestamp(document.last_seen),
        },
        "campaign": (
            {"id": document.campaign_id, "label": document.campaign_label or None}
            if document.campaign_id is not None else None
        ),
        "analyses": [
            {
                "analysisId": analysis.analysis_id,
                "title": analysis.title or None,
                "verdict": analysis.verdict,
                "confidence": analysis.confidence or None,
                "receivedAt": format_timestamp(analysis.received_at),
                "analystLabel": analysis.analyst_label or None,
            }
            for analysis in document.analyses
        ],
        "indicators": [
            {
                "type": indicator.kind,
                "value": defang_value(indicator.kind, indicator.value) if is_defanged else indicator.value,
                "source": PRODUCER_NAME,
                "confidence": indicator.confidence,
                "verdict": indicator.verdict,
                "validFrom": format_timestamp(indicator.valid_from),
                "validUntil": format_timestamp(indicator.valid_until),
                "analysisIds": list(indicator.analysis_ids),
            }
            for indicator in document.indicators
        ],
        "findings": [
            {
                "ruleId": finding.rule_id or None,
                "name": finding.name,
                "category": finding.category,
                "severity": finding.severity or None,
                "score": finding.score,
                "mitreTechniques": list(finding.mitre_techniques),
                "analysisId": finding.analysis_id,
            }
            for finding in document.findings
        ],
    }
