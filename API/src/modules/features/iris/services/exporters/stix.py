"""STIX 2.1: el formato de intercambio de inteligencia que leen los SIEM y los TIP.

Un *bundle* con:

- una ``identity`` para Ellysia Iris, que firma todo lo demás;
- un ``indicator`` por IOC, con su patrón STIX, su confianza y su validez;
- un ``attack-pattern`` por técnica MITRE ATT&CK de las reglas que penalizaron;
- un ``campaign`` cuando lo exportado es (o pertenece a) una campaña, con una
  relación ``indicates`` desde cada indicador;
- un ``report`` que lo referencia todo y resume las reglas en
  ``x_ellysia_findings``.

Los identificadores son UUID v5 derivados del contenido: exportar dos veces lo
mismo da los mismos ids, y un TIP que ya lo importó reconoce los objetos en vez
de duplicarlos.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from . import PRODUCER_NAME, ExportDocument, ExportedIndicator
from .timestamps import format_timestamp

#: Espacio de nombres de los UUID v5 de Ellysia. Fijo para siempre: cambiarlo
#: cambiaría el id de todo lo que ya se exportó.
EXPORT_NAMESPACE = uuid.UUID("7f1d3c2a-5b6e-4f80-9a1b-2c3d4e5f6071")

#: Tipo de indicador STIX según el veredicto (vocabulario ``indicator-type-ov``).
_INDICATOR_TYPES = {
    "Phishing": ["malicious-activity"],
    "Suspicious": ["anomalous-activity"],
    "Legitimate": ["benign"],
}

#: Fecha fija de los objetos que no dependen de ningún análisis (la identidad
#: y las técnicas MITRE): así su id y su versión no cambian entre exportaciones.
_STATIC_CREATED = "2026-01-01T00:00:00.000Z"

_SPEC_VERSION = "2.1"


def render_stix(document: ExportDocument) -> Dict[str, Any]:
    """Traduce el documento a un *bundle* STIX 2.1.

    Args:
        document: Lo que se exporta.

    Returns:
        dict: El *bundle* (``type: bundle``), con ``objects`` en el orden
            identidad, indicadores, técnicas, campaña, relaciones e informe.
    """
    created = format_timestamp(document.first_seen)
    modified = format_timestamp(document.generated_at)
    identity_id = f"identity--{_uuid('identity', PRODUCER_NAME)}"
    identity = {
        "type": "identity", "spec_version": _SPEC_VERSION, "id": identity_id,
        "created": _STATIC_CREATED, "modified": _STATIC_CREATED,
        "name": PRODUCER_NAME, "identity_class": "system",
    }

    indicators = [_indicator(indicator, identity_id, modified) for indicator in document.indicators]

    techniques = sorted({technique for finding in document.findings for technique in finding.mitre_techniques})
    attack_patterns = [
        {
            "type": "attack-pattern", "spec_version": _SPEC_VERSION,
            "id": f"attack-pattern--{_uuid('attack-pattern', technique)}",
            "created": _STATIC_CREATED, "modified": _STATIC_CREATED,
            "created_by_ref": identity_id, "name": technique,
            "external_references": [{
                "source_name": "mitre-attack", "external_id": technique,
                "url": f"https://attack.mitre.org/techniques/{technique.replace('.', '/')}/",
            }],
        }
        for technique in techniques
    ]

    campaign_objects: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    if document.campaign_id is not None:
        campaign_id = f"campaign--{_uuid('campaign', str(document.campaign_id))}"
        campaign_objects.append({
            "type": "campaign", "spec_version": _SPEC_VERSION, "id": campaign_id,
            "created": created, "modified": modified, "created_by_ref": identity_id,
            "name": document.campaign_label or f"Campaña {document.campaign_id}",
            "first_seen": created, "last_seen": format_timestamp(document.last_seen),
        })
        relationships = [
            {
                "type": "relationship", "spec_version": _SPEC_VERSION,
                "id": f"relationship--{_uuid('indicates', indicator['id'] + campaign_id)}",
                "created": created, "modified": modified, "created_by_ref": identity_id,
                "relationship_type": "indicates", "source_ref": indicator["id"], "target_ref": campaign_id,
            }
            for indicator in indicators
        ]

    referenced = [identity_id] + [item["id"] for item in indicators + attack_patterns + campaign_objects + relationships]
    report_id = f"report--{_uuid('report', f'{document.subject_kind}:{document.subject_id}')}"
    report = {
        "type": "report", "spec_version": _SPEC_VERSION, "id": report_id,
        "created": created, "modified": modified, "created_by_ref": identity_id,
        "name": document.title, "report_types": ["threat-report"],
        "published": modified, "object_refs": referenced,
        "confidence": document.confidence, "labels": [document.verdict.lower()],
        "description": f"{PRODUCER_NAME}: {document.subject_kind} {document.subject_id} ({document.verdict}).",
        "x_ellysia_findings": [
            {
                "rule_id": finding.rule_id or None, "name": finding.name, "severity": finding.severity or None,
                "score": finding.score, "mitre_techniques": list(finding.mitre_techniques),
                "analysis_id": finding.analysis_id,
            }
            for finding in document.findings
        ],
        "x_ellysia_analysis_ids": [analysis.analysis_id for analysis in document.analyses],
    }

    return {
        "type": "bundle",
        "id": f"bundle--{_uuid('bundle', report_id + modified)}",
        "objects": [identity, *indicators, *attack_patterns, *campaign_objects, *relationships, report],
    }


def build_pattern(kind: str, value: str) -> str:
    """Patrón STIX que casa con un indicador.

    Args:
        kind: ``domain``, ``url``, ``ip``, ``email`` o ``hash``.
        value: El valor sin desactivar.

    Returns:
        str: El patrón (``[domain-name:value = 'evil.example']``…), con las
            comillas simples y las barras invertidas escapadas.

    Raises:
        ValueError: Si el tipo no se conoce.
    """
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    if kind == "domain":
        return f"[domain-name:value = '{escaped}']"
    if kind == "url":
        return f"[url:value = '{escaped}']"
    if kind == "ip":
        object_type = "ipv6-addr" if ":" in value else "ipv4-addr"
        return f"[{object_type}:value = '{escaped}']"
    if kind == "email":
        return f"[email-addr:value = '{escaped}']"
    if kind == "hash":
        return f"[file:hashes.'SHA-256' = '{escaped}']"
    raise ValueError(f"Tipo de indicador desconocido: {kind}")


def _indicator(indicator: ExportedIndicator, identity_id: str, modified: str) -> Dict[str, Any]:
    """Un ``indicator`` STIX a partir de un IOC exportado.

    Args:
        indicator: El IOC.
        identity_id: Id de la identidad que lo firma.
        modified: Fecha de la exportación, que es su última modificación.

    Returns:
        dict: El objeto ``indicator``.
    """
    valid_from = format_timestamp(indicator.valid_from)
    return {
        "type": "indicator", "spec_version": _SPEC_VERSION,
        "id": f"indicator--{_uuid('indicator', f'{indicator.kind}:{indicator.value}')}",
        "created": valid_from, "modified": max(modified, valid_from),
        "created_by_ref": identity_id,
        "name": f"{indicator.kind}: {indicator.value}",
        "indicator_types": _INDICATOR_TYPES.get(indicator.verdict, ["unknown"]),
        "pattern": build_pattern(indicator.kind, indicator.value),
        "pattern_type": "stix",
        "valid_from": valid_from,
        "valid_until": format_timestamp(indicator.valid_until),
        "confidence": indicator.confidence,
        "labels": ["phishing"] if indicator.verdict == "Phishing" else [indicator.verdict.lower()],
        "x_ellysia_analysis_ids": list(indicator.analysis_ids),
    }


def _uuid(kind: str, key: str) -> uuid.UUID:
    """UUID v5 determinista de un objeto.

    Args:
        kind: Tipo de objeto, para que un indicador y una campaña con la misma
            clave no colisionen.
        key: Lo que identifica al objeto.

    Returns:
        uuid.UUID: El UUID.
    """
    return uuid.uuid5(EXPORT_NAMESPACE, f"{kind}:{key}")
