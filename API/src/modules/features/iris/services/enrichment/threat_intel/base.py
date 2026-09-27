"""Contrato común de los adaptadores de reputación y su registro."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

from ....model import ThreatIntelVerdict
from ..egress import EgressBlockedError, EgressResponse, fetch

#: Orden de gravedad de los veredictos, de menos a más. ``unavailable`` es el
#: menos informativo: cualquier respuesta real lo supera.
_VERDICT_ORDER = (
    ThreatIntelVerdict.UNAVAILABLE,
    ThreatIntelVerdict.UNKNOWN,
    ThreatIntelVerdict.SUSPICIOUS,
    ThreatIntelVerdict.KNOWN_MALICIOUS,
)


@dataclass(frozen=True)
class ThreatIntelFinding:
    """Lo que dice un proveedor de un indicador, ya normalizado.

    Attributes:
        provider: Nombre del proveedor.
        verdict: Veredicto común.
        detail: Datos del proveedor que justifican el veredicto (recuentos de
            motores, estado, enlace a su ficha…), pequeños y sin el indicador.
        error: Por qué no hay veredicto cuando es ``unavailable``, o ``None``.
    """

    provider: str
    verdict: ThreatIntelVerdict
    detail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class ThreatIntelAdapter(ABC):
    """Un proveedor de reputación.

    Las subclases declaran ``NAME`` y ``SUPPORTED_KINDS`` y redefinen
    ``_query``; se dan de alta solas en el registro al definirse.

    Attributes:
        NAME: Nombre del proveedor, el mismo que su bloque de configuración.
        SUPPORTED_KINDS: Tipos de indicador que sabe consultar.
    """

    NAME: ClassVar[str] = ""
    SUPPORTED_KINDS: ClassVar[FrozenSet[str]] = frozenset()
    _registry: ClassVar[Dict[str, "ThreatIntelAdapter"]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Da de alta la subclase en el registro por su ``NAME``."""
        super().__init_subclass__(**kwargs)
        if cls.NAME:
            ThreatIntelAdapter._registry[cls.NAME] = cls()

    def lookup(self, kind: str, value: str, api_key: str, timeout_seconds: float,
               max_bytes: int) -> ThreatIntelFinding:
        """Consulta un indicador. Nunca lanza: un fallo es ``unavailable``.

        Args:
            kind: ``domain``, ``url``, ``ip`` o ``hash``.
            value: El indicador, sin desactivar.
            api_key: Clave de API del proveedor.
            timeout_seconds: Tiempo máximo de cada operación de red.
            max_bytes: Bytes que se leen como mucho de la respuesta.

        Returns:
            ThreatIntelFinding: El veredicto del proveedor.
        """
        if kind not in self.SUPPORTED_KINDS:
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error="unsupported_kind")
        try:
            return self._query(kind, value, api_key, timeout_seconds, max_bytes)
        except EgressBlockedError as e:
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=e.reason)
        except (OSError, ValueError, KeyError, TypeError) as e:
            error = "timeout" if isinstance(e, TimeoutError) else type(e).__name__.lower()[:32]
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error=error)
        except Exception:  # pylint: disable=broad-exception-caught
            return ThreatIntelFinding(self.NAME, ThreatIntelVerdict.UNAVAILABLE, error="provider_error")

    @abstractmethod
    def _query(self, kind: str, value: str, api_key: str, timeout_seconds: float,
               max_bytes: int) -> ThreatIntelFinding:
        """Gancho: la llamada concreta al proveedor y la normalización de su respuesta.

        Lo redefinen ``VirusTotalAdapter``, ``UrlscanAdapter``,
        ``PhishTankAdapter`` y ``UrlhausAdapter``. Puede lanzar: ``lookup``
        convierte cualquier fallo en ``unavailable``.

        Args:
            kind: Tipo de indicador, ya comprobado que está soportado.
            value: El indicador.
            api_key: Clave de API.
            timeout_seconds: Tiempo máximo de cada operación de red.
            max_bytes: Bytes que se leen como mucho.

        Returns:
            ThreatIntelFinding: El veredicto.
        """


def request_json(url: str, *, timeout_seconds: float, max_bytes: int, method: str = "GET",
                 headers: Optional[Dict[str, str]] = None, body: Optional[bytes] = None) -> tuple[int, Any]:
    """Llama a la API de un proveedor y lee su JSON.

    Args:
        url: Endpoint del proveedor.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes que se leen como mucho.
        method: ``GET`` o ``POST``. Por defecto ``GET``.
        headers: Clave de API y tipo de contenido. Por defecto ``None``.
        body: Cuerpo del ``POST``. Por defecto ``None``.

    Returns:
        tuple: ``(código HTTP, JSON)``; el JSON es ``None`` si no lo había o
            no se entendía.
    """
    response: EgressResponse = fetch(url, timeout_seconds=timeout_seconds, max_bytes=max_bytes, method=method,
                                     accept="application/json", extra_headers=headers, body=body)
    try:
        payload = json.loads(response.body.decode("utf-8")) if response.body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    return response.status, payload


def adapter_for(provider: str) -> Optional[ThreatIntelAdapter]:
    """El adaptador de un proveedor.

    Args:
        provider: Nombre del proveedor.

    Returns:
        Optional[ThreatIntelAdapter]: El adaptador, o ``None`` si no existe.
    """
    return ThreatIntelAdapter._registry.get(provider)


def registered_adapters() -> List[ThreatIntelAdapter]:
    """Todos los adaptadores, por nombre.

    Returns:
        List[ThreatIntelAdapter]: Los adaptadores registrados.
    """
    return [ThreatIntelAdapter._registry[name] for name in sorted(ThreatIntelAdapter._registry)]


def worst_verdict(verdicts: List[ThreatIntelVerdict]) -> ThreatIntelVerdict:
    """El veredicto más grave de varios proveedores.

    Args:
        verdicts: Veredictos.

    Returns:
        ThreatIntelVerdict: El más grave; ``unavailable`` si la lista está vacía
            o ninguno respondió.
    """
    return max(verdicts, key=_VERDICT_ORDER.index, default=ThreatIntelVerdict.UNAVAILABLE)
