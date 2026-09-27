"""URLhaus (abuse.ch): URLs, hosts y ficheros que distribuyen malware."""

from __future__ import annotations

from urllib.parse import urlencode

from ....model import ThreatIntelVerdict
from .base import ThreatIntelAdapter, ThreatIntelFinding, request_json

_API = "https://urlhaus-api.abuse.ch/v1"

#: Recurso de la API y nombre del campo según el tipo de indicador.
_ENDPOINT_BY_KIND = {
    "url": ("url", "url"),
    "domain": ("host", "host"),
    "ip": ("host", "host"),
    "hash": ("payload", "sha256_hash"),
}


class UrlhausAdapter(ThreatIntelAdapter):
    """Adaptador de URLhaus."""

    NAME = "urlhaus"
    SUPPORTED_KINDS = frozenset(_ENDPOINT_BY_KIND)

    def _query(self, kind: str, value: str, api_key: str, timeout_seconds: float,
               max_bytes: int) -> ThreatIntelFinding:
        """Consulta el indicador en URLhaus (ver la base).

        Args:
            kind: Tipo de indicador.
            value: El indicador.
            api_key: Clave de abuse.ch (cabecera ``Auth-Key``).
            timeout_seconds: Tiempo máximo de cada operación de red.
            max_bytes: Bytes que se leen como mucho.

        Returns:
            ThreatIntelFinding: ``known_malicious`` si URLhaus lo tiene
                registrado, ``unknown`` si no.
        """
        resource, field_name = _ENDPOINT_BY_KIND[kind]
        status, payload = request_json(
            f"{_API}/{resource}/", timeout_seconds=timeout_seconds, max_bytes=max_bytes, method="POST",
            headers={"Auth-Key": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode({field_name: value}).encode(),
        )
        if status != 200 or not isinstance(payload, dict):
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=f"http_{status}")
        query_status = payload.get("query_status")
        if query_status == "ok":
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.KNOWN_MALICIOUS,
                                      {"status": payload.get("url_status") or "listed"})
        if query_status in ("no_results", "not_found"):
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNKNOWN, {"status": "not_listed"})
        return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=str(query_status or "invalid")[:32])
