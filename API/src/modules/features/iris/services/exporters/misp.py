"""MISP: un evento en el formato JSON que importa una instancia MISP.

Cada IOC es un atributo con su tipo MISP, categoría, ventana de validez
(``first_seen``/``last_seen``) y ``to_ids``: solo los de un correo de phishing
se marcan para que el IDS los bloquee; los de uno sospechoso o legítimo se
exportan como contexto. Las técnicas MITRE ATT&CK van como etiquetas de la
galaxia ``mitre-attack-pattern`` y el veredicto, como etiqueta propia.
"""

from __future__ import annotations

import calendar
import uuid
from typing import Any, Dict

from . import PRODUCER_NAME, ExportDocument
from .stix import EXPORT_NAMESPACE
from .timestamps import format_timestamp

#: Tipo y categoría MISP de cada tipo de indicador. Direcciones, dominios, URLs
#: e IPs salen de las cabeceras o de los enlaces del cuerpo; el hash, de un
#: adjunto.
_MISP_TYPE_BY_KIND = {
    "domain": ("domain", "Network activity"),
    "url": ("url", "Network activity"),
    "ip": ("ip-src", "Network activity"),
    "email": ("email-src", "Payload delivery"),
    "hash": ("sha256", "Payload delivery"),
}

#: ``threat_level_id`` de MISP: 1 alto, 2 medio, 3 bajo, 4 sin definir.
_THREAT_LEVEL_BY_VERDICT = {"Phishing": "1", "Suspicious": "2", "Legitimate": "3"}


def render_misp(document: ExportDocument) -> Dict[str, Any]:
    """Traduce el documento a un evento MISP.

    El evento tiene siempre el mismo ``uuid`` para lo mismo exportado, así que
    MISP lo actualiza en vez de duplicarlo.

    Args:
        document: Lo que se exporta.

    Returns:
        dict: ``{"Event": {...}}`` con ``info``, ``date``, ``threat_level_id``,
            ``analysis`` (2: completo), ``distribution`` (0: solo esta
            organización, lo más restrictivo; quien lo importa decide si lo
            comparte), ``Orgc``, ``Attribute`` y ``Tag``.
    """
    event_uuid = uuid.uuid5(EXPORT_NAMESPACE, f"misp-event:{document.subject_kind}:{document.subject_id}")
    attributes = []
    for indicator in document.indicators:
        misp_type, category = _MISP_TYPE_BY_KIND[indicator.kind]
        attributes.append({
            "uuid": str(uuid.uuid5(EXPORT_NAMESPACE, f"misp-attribute:{event_uuid}:{indicator.kind}:{indicator.value}")),
            "type": misp_type,
            "category": category,
            "value": indicator.value,
            "to_ids": indicator.verdict == "Phishing",
            "comment": f"{PRODUCER_NAME} · confianza {indicator.confidence} · análisis "
                       + ", ".join(str(analysis_id) for analysis_id in indicator.analysis_ids),
            "first_seen": format_timestamp(indicator.valid_from),
            "last_seen": format_timestamp(indicator.valid_until),
            "distribution": "5",
        })

    tags = [{"name": f'ellysia:verdict="{document.verdict.lower()}"'}]
    tags += [
        {"name": f'misp-galaxy:mitre-attack-pattern="{technique}"'}
        for technique in sorted({technique for finding in document.findings for technique in finding.mitre_techniques})
    ]
    if document.campaign_id is not None:
        tags.append({"name": f'ellysia:campaign="{document.campaign_id}"'})

    return {
        "Event": {
            "uuid": str(event_uuid),
            "info": f"{PRODUCER_NAME}: {document.title}",
            "date": document.first_seen.strftime("%Y-%m-%d"),
            "timestamp": str(calendar.timegm(document.generated_at.utctimetuple())),
            "threat_level_id": _THREAT_LEVEL_BY_VERDICT.get(document.verdict, "4"),
            "analysis": "2",
            "distribution": "0",
            "published": False,
            "Orgc": {"name": PRODUCER_NAME},
            "Attribute": attributes,
            "Tag": tags,
        }
    }
