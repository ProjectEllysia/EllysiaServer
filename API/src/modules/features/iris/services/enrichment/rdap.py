"""
RDAP: quién registró un dominio, cuándo, y en qué red vive.

RDAP es el sucesor en JSON de WHOIS. Se pregunta a un servicio de arranque
(``features.iris.enrichment.rdap.baseUrl``) que redirige a la base de datos del
registro que toca; la redirección se sigue con ``egress.fetch_following``, que
comprueba cada salto.

Dos consultas por dominio:

1. ``/domain/<dominio>``: fechas de alta y caducidad, registrador, estados y
   servidores de nombres.
2. ``/ip/<ip>`` de la primera IP pública del dominio: nombre de la red, país y,
   si el registro lo publica, el sistema autónomo de origen.

Si la segunda falla, la primera sigue valiendo: el contexto sale parcial, no
vacío. Si falla la primera, el resultado es neutro (``unavailable``).

La edad de un dominio **nunca decide nada por sí sola**: hay dominios nuevos
legítimos (una campaña de marketing) y dominios viejos comprometidos. Es
contexto para quien investiga.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .egress import fetch_following, is_blocked_address

#: Redirects que se siguen como mucho: arranque → registro, y alguno más.
_MAX_REDIRECTS = 3

_RDAP_ACCEPT = "application/rdap+json, application/json"


@dataclass(frozen=True)
class DomainRegistration:
    """Lo que dice el registro de un dominio.

    Attributes:
        registered_at: Fecha de alta, o ``None``.
        expires_at: Fecha de caducidad, o ``None``.
        registrar: Nombre del registrador, o ``None``.
        statuses: Estados EPP del dominio.
        nameservers: Servidores de nombres, en minúsculas.
    """

    registered_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    registrar: Optional[str] = None
    statuses: Tuple[str, ...] = field(default_factory=tuple)
    nameservers: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NetworkRegistration:
    """Lo que dice el registro de la red de una IP.

    Attributes:
        address: La IP consultada.
        name: Nombre de la red, o ``None``.
        country: País (dos letras), o ``None``.
        asn: Sistema autónomo de origen (``AS15169``), o ``None`` si el
            registro no lo publica.
    """

    address: str
    name: Optional[str] = None
    country: Optional[str] = None
    asn: Optional[str] = None


@dataclass(frozen=True)
class DomainContext:
    """Contexto completo de un dominio, o por qué no lo hay.

    Attributes:
        registration: Datos del registro, o ``None`` si no se obtuvieron.
        network: Datos de la red, o ``None``.
        error: Motivo si ``registration`` es ``None`` (``timeout``,
            ``not_found``, ``private_address``…), o ``None``.
    """

    registration: Optional[DomainRegistration] = None
    network: Optional[NetworkRegistration] = None
    error: Optional[str] = None


def parse_domain_response(payload: Dict[str, Any]) -> DomainRegistration:
    """Extrae los datos útiles de una respuesta RDAP de dominio (RFC 9083).

    Args:
        payload: JSON de ``/domain/<dominio>``.

    Returns:
        DomainRegistration: Los datos; los que falten quedan a ``None`` o vacíos.
    """
    events = {event.get("eventAction"): event.get("eventDate") for event in payload.get("events") or []
              if isinstance(event, dict)}
    registrar = None
    for entity in payload.get("entities") or []:
        if isinstance(entity, dict) and "registrar" in (entity.get("roles") or []):
            registrar = _vcard_name(entity) or entity.get("handle")
            break
    nameservers = tuple(sorted({
        (nameserver.get("ldhName") or "").lower().rstrip(".")
        for nameserver in payload.get("nameservers") or [] if isinstance(nameserver, dict) and nameserver.get("ldhName")
    }))
    return DomainRegistration(
        registered_at=_parse_date(events.get("registration")),
        expires_at=_parse_date(events.get("expiration")),
        registrar=registrar,
        statuses=tuple(str(status) for status in payload.get("status") or []),
        nameservers=nameservers,
    )


def parse_ip_response(address: str, payload: Dict[str, Any]) -> NetworkRegistration:
    """Extrae los datos útiles de una respuesta RDAP de red.

    El sistema autónomo no forma parte del estándar para una red; algunos
    registros (ARIN) lo publican en una extensión propia, que se lee si está.

    Args:
        address: IP consultada.
        payload: JSON de ``/ip/<ip>``.

    Returns:
        NetworkRegistration: Los datos.
    """
    asn = None
    for key, value in payload.items():
        if "originautnum" in key.lower() and isinstance(value, list) and value:
            asn = f"AS{value[0]}"
            break
    country = payload.get("country")
    return NetworkRegistration(
        address=address,
        name=payload.get("name") or None,
        country=country.upper() if isinstance(country, str) and country else None,
        asn=asn,
    )


def lookup_domain(domain: str, *, base_url: str, timeout_seconds: float, max_bytes: int) -> DomainContext:
    """Consulta el registro de un dominio y la red donde se aloja.

    Nunca lanza: cualquier fallo sale como ``DomainContext.error``.

    Args:
        domain: Dominio registrable, en minúsculas.
        base_url: Servicio RDAP de arranque (sin barra final).
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes que se leen como mucho de cada respuesta.

    Returns:
        DomainContext: El contexto, completo, parcial (sin red) o vacío con
            su motivo.
    """
    payload, error = _get_json(f"{base_url.rstrip('/')}/domain/{domain}", timeout_seconds, max_bytes)
    if payload is None:
        return DomainContext(error=error)
    registration = parse_domain_response(payload)

    address = _first_public_address(domain)
    network = None
    if address is not None:
        ip_payload, _ = _get_json(f"{base_url.rstrip('/')}/ip/{address}", timeout_seconds, max_bytes)
        network = parse_ip_response(address, ip_payload) if ip_payload is not None else NetworkRegistration(address)
    return DomainContext(registration=registration, network=network)


def _get_json(url: str, timeout_seconds: float, max_bytes: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Pide un recurso RDAP siguiendo sus redirects.

    Args:
        url: Recurso RDAP.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes que se leen como mucho.

    Returns:
        Tuple: ``(json, None)`` si respondió 200 con JSON; ``(None, motivo)``
            si no (``not_found``, ``http_<código>``, ``invalid_response`` o el
            motivo del salto que falló).
    """
    chain = fetch_following(url, max_redirects=_MAX_REDIRECTS, timeout_seconds=timeout_seconds,
                            max_bytes=max_bytes, accept=_RDAP_ACCEPT)
    last_hop = chain.hops[-1] if chain.hops else None
    if last_hop is not None and last_hop.error:
        return None, last_hop.error
    if chain.final is None:
        return None, "invalid_response"
    if chain.final.status == 404:
        return None, "not_found"
    if chain.final.status != 200 or chain.final.is_truncated:
        return None, f"http_{chain.final.status}" if chain.final.status != 200 else "too_large"
    try:
        payload = json.loads(chain.final.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid_response"
    return (payload, None) if isinstance(payload, dict) else (None, "invalid_response")


def _first_public_address(domain: str) -> Optional[str]:
    """Primera IP pública a la que resuelve un dominio.

    Args:
        domain: Dominio.

    Returns:
        Optional[str]: La IP, o ``None`` si no resuelve o solo resuelve a
            direcciones privadas (de las que no se pregunta nada fuera).
    """
    try:
        results = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    for result in results:
        address = result[4][0]
        if not is_blocked_address(address):
            return address
    return None


def _vcard_name(entity: Dict[str, Any]) -> Optional[str]:
    """El nombre (``fn``) de la tarjeta jCard de una entidad RDAP.

    Args:
        entity: Entidad RDAP.

    Returns:
        Optional[str]: El nombre, o ``None`` si no trae.
    """
    vcard = entity.get("vcardArray")
    if not isinstance(vcard, list) or len(vcard) < 2 or not isinstance(vcard[1], list):
        return None
    for item in vcard[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] == "fn" and isinstance(item[3], str):
            return item[3].strip() or None
    return None


def _parse_date(value: Any) -> Optional[datetime]:
    """Fecha RDAP (RFC 3339) a ``datetime`` naive en UTC.

    Args:
        value: Cadena de fecha, o cualquier otra cosa.

    Returns:
        Optional[datetime]: La fecha, o ``None`` si no se entiende.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = (moment - moment.utcoffset()).replace(tzinfo=None)
    return moment
