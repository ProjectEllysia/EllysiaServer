"""
Reputación de un indicador en servicios de threat intelligence.

Cada proveedor (VirusTotal, urlscan, PhishTank, URLhaus) es un adaptador que
traduce su respuesta a un veredicto común, ``ThreatIntelVerdict``: ``known_malicious``,
``suspicious``, ``unknown`` o ``unavailable``. Los adaptadores se dan de alta en
un registro, así que añadir un proveedor es escribir uno más.

Lo único que sale hacia un proveedor es **el indicador** (un dominio, una URL,
una IP o el hash de un adjunto) y la clave de API de ese proveedor. Nunca el
correo, ni su cuerpo, ni sus cabeceras, ni un adjunto: un hash no revela el
fichero. Todas las llamadas pasan por ``egress.fetch``.
"""

from .base import (
    ThreatIntelAdapter,
    ThreatIntelFinding,
    adapter_for,
    registered_adapters,
    worst_verdict,
)
from . import phishtank, urlhaus, urlscan, virustotal  # noqa: F401  (se dan de alta al importarse)

__all__ = [
    "ThreatIntelAdapter",
    "ThreatIntelFinding",
    "adapter_for",
    "registered_adapters",
    "worst_verdict",
]
