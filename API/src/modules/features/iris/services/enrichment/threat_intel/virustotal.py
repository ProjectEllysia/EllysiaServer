"""VirusTotal (API v3): cuántos motores de análisis marcan un indicador."""

from __future__ import annotations

import base64

from ....model import ThreatIntelVerdict
from .base import ThreatIntelAdapter, ThreatIntelFinding, request_json

_API = "https://www.virustotal.com/api/v3"

#: Motores que tienen que marcarlo como malicioso para darlo por conocido; con
#: uno solo es sospechoso (los falsos positivos de un motor aislado son
#: frecuentes).
_MALICIOUS_ENGINES = 2

_PATH_BY_KIND = {"domain": "domains", "url": "urls", "ip": "ip_addresses", "hash": "files"}


class VirusTotalAdapter(ThreatIntelAdapter):
    """Adaptador de VirusTotal."""

    NAME = "virustotal"
    SUPPORTED_KINDS = frozenset(_PATH_BY_KIND)

    def _query(self, kind: str, value: str, api_key: str, timeout_seconds: float,
               max_bytes: int) -> ThreatIntelFinding:
        """Consulta el informe de VirusTotal del indicador (ver la base).

        Args:
            kind: Tipo de indicador.
            value: El indicador.
            api_key: Clave de API (cabecera ``x-apikey``).
            timeout_seconds: Tiempo máximo de cada operación de red.
            max_bytes: Bytes que se leen como mucho.

        Returns:
            ThreatIntelFinding: ``known_malicious`` con dos motores o más,
                ``suspicious`` con uno o alguno «sospechoso», ``unknown`` si no
                lo conoce o nadie lo marca.
        """
        identifier = base64.urlsafe_b64encode(value.encode()).decode().rstrip("=") if kind == "url" else value
        status, payload = request_json(f"{_API}/{_PATH_BY_KIND[kind]}/{identifier}", timeout_seconds=timeout_seconds,
                                       max_bytes=max_bytes, headers={"x-apikey": api_key})
        if status == 404:
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNKNOWN, {"known": False})
        if status != 200 or not isinstance(payload, dict):
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=f"http_{status}")
        stats = payload["data"]["attributes"].get("last_analysis_stats") or {}
        malicious, suspicious = int(stats.get("malicious", 0)), int(stats.get("suspicious", 0))
        if malicious >= _MALICIOUS_ENGINES:
            verdict = ThreatIntelVerdict.KNOWN_MALICIOUS
        elif malicious or suspicious:
            verdict = ThreatIntelVerdict.SUSPICIOUS
        else:
            verdict = ThreatIntelVerdict.UNKNOWN
        return ThreatIntelFinding(self.NAME, verdict, {
            "malicious": malicious, "suspicious": suspicious,
            "engines": sum(int(count) for count in stats.values() if isinstance(count, int)),
        })
