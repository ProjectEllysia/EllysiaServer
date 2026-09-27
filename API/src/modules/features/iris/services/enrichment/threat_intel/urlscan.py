"""urlscan.io: si algún escaneo público de ese dominio, URL o IP salió malicioso."""

from __future__ import annotations

from urllib.parse import quote

from ....model import ThreatIntelVerdict
from .base import ThreatIntelAdapter, ThreatIntelFinding, request_json

_API = "https://urlscan.io/api/v1/search/"

_FIELD_BY_KIND = {"domain": "page.domain", "url": "page.url", "ip": "page.ip"}


class UrlscanAdapter(ThreatIntelAdapter):
    """Adaptador de urlscan.io (búsqueda en sus escaneos)."""

    NAME = "urlscan"
    SUPPORTED_KINDS = frozenset(_FIELD_BY_KIND)

    def _query(self, kind: str, value: str, api_key: str, timeout_seconds: float,
               max_bytes: int) -> ThreatIntelFinding:
        """Busca escaneos del indicador marcados como maliciosos (ver la base).

        Args:
            kind: Tipo de indicador.
            value: El indicador.
            api_key: Clave de API (cabecera ``API-Key``).
            timeout_seconds: Tiempo máximo de cada operación de red.
            max_bytes: Bytes que se leen como mucho.

        Returns:
            ThreatIntelFinding: ``known_malicious`` si algún escaneo lo marcó,
                ``unknown`` si no.
        """
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        query = quote(f'{_FIELD_BY_KIND[kind]}:"{escaped}" AND verdicts.malicious:true')
        status, payload = request_json(f"{_API}?q={query}&size=1", timeout_seconds=timeout_seconds,
                                       max_bytes=max_bytes, headers={"API-Key": api_key})
        if status != 200 or not isinstance(payload, dict):
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=f"http_{status}")
        malicious_scans = int(payload.get("total", 0))
        verdict = ThreatIntelVerdict.KNOWN_MALICIOUS if malicious_scans else ThreatIntelVerdict.UNKNOWN
        return ThreatIntelFinding(self.NAME, verdict, {"maliciousScans": malicious_scans})
