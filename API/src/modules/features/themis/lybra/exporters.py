"""Exportadores puros de un escaneo Lybra a formatos estándar de la industria.

Lybra sólo salía del sistema por su propia API y por un PDF, lo que obligaba
a Ellysia a ser el destino final de cada hallazgo — y casi nunca lo es: un
equipo de seguridad ya tiene un SIEM, un TIP o un pipeline de CI donde esos
datos tienen que aterrizar. Este módulo cubre los tres consumidores más
comunes:

``to_sarif``
    El formato de resultados de análisis estático. GitHub lo ingiere de forma
    nativa en su pestaña de seguridad, y es lo que permite un *gate* de CI:
    "este despliegue no sale si Lybra encuentra un CRITICAL".

``to_stix``
    Inteligencia de amenazas, para publicar a un TIP.

``to_ocsf``
    El esquema que consumen los SIEM modernos.

Las tres son funciones puras sobre el dict que produce
``LybraEngineManager.format_scan`` (``target`` + ``findings``, cada uno ya en
la forma de ``finding_to_json``): no hacen ni una consulta ni abren un
socket, así que son triviales de testear y no rompen la invariante de
pureza de ``lybra/`` (ver el docstring del paquete).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from .correlation import PRIORITY_LADDER

# SARIF exige "note" | "warning" | "error" (no admite una escala de cinco
# niveles); INFO y LOW comparten "note" porque ninguno de los dos debe romper
# un gate de CI por sí solo.
_SARIF_LEVEL_BY_PRIORITY: Dict[str, str] = {
    "INFO": "note",
    "LOW": "note",
    "MEDIUM": "warning",
    "HIGH": "error",
    "CRITICAL": "error",
}

# OCSF Vulnerability Finding (2002): severity_id es un entero de un enum fijo,
# no la cadena de PRIORITY_LADDER. 0 = Unknown se usa como red de seguridad
# para una prioridad que no está en la tabla.
_OCSF_SEVERITY_ID_BY_PRIORITY: Dict[str, int] = {
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}

# OCSF Finding status_id: 1 New, 3 Suppressed, 4 Resolved. "accepted" (riesgo
# aceptado) y "false_positive" (desmentido) se mapean los dos a Suppressed:
# ninguno de los dos es ya un hallazgo activo, y OCSF no distingue el motivo
# a este nivel — eso vive en `stateReason`, que no tiene hueco en este esquema.
_OCSF_STATUS_ID_BY_STATE: Dict[str, int] = {
    "open": 1,
    "regressed": 1,
    "accepted": 3,
    "false_positive": 3,
    "fixed": 4,
}

# Namespace propio para los UUID deterministas de STIX: dos exportaciones del
# mismo escaneo deben producir los mismos identificadores de objeto, para que
# un TIP que ya los tiene los reconozca como el mismo objeto en vez de
# duplicarlos.
_STIX_NAMESPACE = uuid.UUID("f6d1a6d0-6e6f-4b8a-9b7a-2e6c9d6a9b7a")


def _stix_id(sdo_type: str, seed: str) -> str:
    """Compone un id STIX (``"<tipo>--<uuid>"``) determinista a partir de ``seed``.

    Args:
        sdo_type: El tipo de objeto STIX (``"vulnerability"``,
            ``"infrastructure"``, ``"relationship"``).
        seed: Cadena estable que identifica el objeto dentro del escaneo (por
            ejemplo el id del hallazgo, o el objetivo escaneado).

    Returns:
        str: El id en la forma que exige STIX 2.1, siempre el mismo para el
            mismo ``sdo_type`` + ``seed``.
    """
    return f"{sdo_type}--{uuid.uuid5(_STIX_NAMESPACE, f'{sdo_type}:{seed}')}"


def _priority_of(finding: Dict[str, Any]) -> str:
    """La prioridad del hallazgo, o ``"INFO"`` si viene ausente o no reconocida."""
    priority = finding.get("priority")
    return priority if priority in PRIORITY_LADDER else "INFO"


def to_sarif(scan: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte un escaneo a un documento SARIF 2.1.0.

    Cada hallazgo es un ``result``: ``checkId`` (o, si no hay check activo de
    por medio, la categoría) es el ``ruleId``, la prioridad mapea a
    ``level``, y ``target:puerto`` es la ubicación. Las reglas que aparecen
    se declaran una sola vez en ``tool.driver.rules``, con lo que el
    documento queda autodescriptivo sin depender de que el consumidor ya
    conozca el feed de Lybra.

    Args:
        scan: El dict de ``LybraEngineManager.format_scan`` — necesita
            ``target`` (el host escaneado) y ``findings`` (lista en la forma
            de ``finding_to_json``).

    Returns:
        dict: Un documento SARIF con un único ``run``. Un escaneo sin
            hallazgos produce ``results: []``, que es un SARIF válido y vacío.
    """
    target = scan.get("target") or "unknown"
    findings = scan.get("findings") or []

    rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    for finding in findings:
        rule_id = finding.get("checkId") or finding.get("category") or "lybra-finding"
        title = finding.get("title") or rule_id
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": rule_id,
                "shortDescription": {"text": title},
            }
        location = f"{target}:{finding['port']}" if finding.get("port") else target
        results.append({
            "ruleId": rule_id,
            "level": _SARIF_LEVEL_BY_PRIORITY.get(_priority_of(finding), "note"),
            "message": {"text": title},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": location},
                },
            }],
        })

    return {
        "$schema": (
            "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
            "master/Schemata/sarif-schema-2.1.0.json"
        ),
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "Lybra",
                    "informationUri": "https://ellysia.io",
                    "rules": list(rules.values()),
                },
            },
            "results": results,
        }],
    }


def to_stix(scan: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte un escaneo a un *bundle* STIX 2.1.

    Cada hallazgo se traduce a un objeto ``vulnerability`` (con sus CVE como
    ``external_references``), relacionado por un objeto ``relationship`` con
    el objeto ``infrastructure`` que representa el objetivo escaneado.

    Args:
        scan: El dict de ``LybraEngineManager.format_scan``.

    Returns:
        dict: Un *bundle* STIX. Un escaneo sin hallazgos produce
            ``objects: []`` — un documento válido y vacío, sin siquiera el
            objeto de infraestructura, que no aporta nada por sí solo.
    """
    target = scan.get("target") or "unknown"
    findings = scan.get("findings") or []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    if not findings:
        return {"type": "bundle", "id": _stix_id("bundle", target), "objects": []}

    infrastructure_id = _stix_id("infrastructure", target)
    objects: List[Dict[str, Any]] = [{
        "type": "infrastructure",
        "id": infrastructure_id,
        "created": now,
        "modified": now,
        "name": target,
        "infrastructure_types": ["unknown"],
    }]

    for finding in findings:
        finding_id = finding.get("id")
        vulnerability_id = _stix_id("vulnerability", f"{target}:{finding_id}")
        external_references = [
            {"source_name": "cve", "external_id": cve_id}
            for cve_id in (finding.get("cveIds") or [])
        ]
        objects.append({
            "type": "vulnerability",
            "id": vulnerability_id,
            "created": now,
            "modified": now,
            "name": finding.get("title") or "Untitled finding",
            "external_references": external_references,
        })
        objects.append({
            "type": "relationship",
            "id": _stix_id("relationship", f"{infrastructure_id}:{vulnerability_id}"),
            "created": now,
            "modified": now,
            "relationship_type": "has",
            "source_ref": infrastructure_id,
            "target_ref": vulnerability_id,
        })

    return {"type": "bundle", "id": _stix_id("bundle", target), "objects": objects}


def to_ocsf(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convierte un escaneo a una lista de eventos OCSF *Vulnerability Finding* (2002).

    A diferencia de SARIF y STIX —cada uno un único documento—, OCSF describe
    eventos: la salida es una lista con un evento por hallazgo, que es como un
    SIEM los espera (uno por línea, o uno por mensaje).

    Args:
        scan: El dict de ``LybraEngineManager.format_scan``.

    Returns:
        list[dict]: Un evento OCSF por hallazgo. Un escaneo sin hallazgos
            produce una lista vacía, válida por definición: no hay nada que
            no valide.
    """
    target = scan.get("target") or "unknown"
    findings = scan.get("findings") or []
    now_millis = int(datetime.now(timezone.utc).timestamp() * 1000)

    events: List[Dict[str, Any]] = []
    for finding in findings:
        priority = _priority_of(finding)
        cve_ids = finding.get("cveIds") or []
        cvss_score = finding.get("cvssScore")
        cvss_field = [{"base_score": cvss_score}] if cvss_score is not None else None
        vulnerabilities = [
            {"cve": {"uid": cve_id}, **({"cvss": cvss_field} if cvss_field else {})}
            for cve_id in cve_ids
        ]
        events.append({
            "activity_id": 1,
            "activity_name": "Create",
            "category_uid": 2,
            "category_name": "Findings",
            "class_uid": 2002,
            "class_name": "Vulnerability Finding",
            "severity_id": _OCSF_SEVERITY_ID_BY_PRIORITY.get(priority, 0),
            "severity": priority,
            "status_id": _OCSF_STATUS_ID_BY_STATE.get(finding.get("state"), 99),
            "time": now_millis,
            "metadata": {
                "product": {"name": "Lybra", "vendor_name": "Ellysia"},
            },
            "finding_info": {
                "uid": str(finding.get("id")),
                "title": finding.get("title") or "Untitled finding",
            },
            "vulnerabilities": vulnerabilities,
            "resources": [{"name": target, "type": "host"}],
        })
    return events
