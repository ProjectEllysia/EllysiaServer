"""PhishTank: si una URL está en su base de phishing verificado por la comunidad."""

from __future__ import annotations

from urllib.parse import urlencode

from ....model import ThreatIntelVerdict
from .base import ThreatIntelAdapter, ThreatIntelFinding, request_json

_API = "https://checkurl.phishtank.com/checkurl/"


class PhishTankAdapter(ThreatIntelAdapter):
    """Adaptador de PhishTank."""

    NAME = "phishtank"
    SUPPORTED_KINDS = frozenset({"url"})

    def _query(self, kind: str, value: str, api_key: str, timeout_seconds: float,
               max_bytes: int) -> ThreatIntelFinding:
        """Comprueba la URL en PhishTank (ver la base).

        Args:
            kind: ``url``.
            value: La URL.
            api_key: Clave de aplicación de PhishTank.
            timeout_seconds: Tiempo máximo de cada operación de red.
            max_bytes: Bytes que se leen como mucho.

        Returns:
            ThreatIntelFinding: ``known_malicious`` si está verificada como
                phishing, ``suspicious`` si está enviada pero sin verificar,
                ``unknown`` si no está.
        """
        body = urlencode({"url": value, "format": "json", "app_key": api_key}).encode()
        status, payload = request_json(_API, timeout_seconds=timeout_seconds, max_bytes=max_bytes, method="POST",
                                       headers={"Content-Type": "application/x-www-form-urlencoded"}, body=body)
        if status != 200 or not isinstance(payload, dict):
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=f"http_{status}")
        results = payload.get("results") or {}
        if not results.get("in_database"):
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNKNOWN, {"inDatabase": False})
        is_verified = bool(results.get("verified")) and bool(results.get("valid"))
        verdict = ThreatIntelVerdict.KNOWN_MALICIOUS if is_verified else ThreatIntelVerdict.SUSPICIOUS
        return ThreatIntelFinding(self.NAME, verdict, {"inDatabase": True, "verified": is_verified})
