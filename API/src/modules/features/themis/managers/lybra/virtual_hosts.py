"""La mitad de red del descubrimiento de sitios: los certificados, el PTR y la resolución.

La decisión (qué nombres valen y cómo se reportan) vive en
``lybra.virtual_hosts``, libre de red; aquí sólo se habla con el objetivo y
con el DNS.
"""

import socket
from typing import Callable, List, Optional, Tuple

from ...lybra import is_ftp_service, is_http_service, is_tls_service, select_site_names


def discover_sites(
    address: str,
    services: list,
    limit: int,
    tls_fetch: Callable,
    reverse_lookup: Callable[[str], Optional[str]] = None,
    resolve: Callable[[str], set] = None,
) -> List[Tuple[str, str]]:
    """Los sitios con nombre que sirve ``address``, con el origen de cada nombre.

    Los candidatos salen, por este orden, de los certificados de cada servicio
    TLS (el SAN y el CN; el FTP en claro, tras ``AUTH TLS``) y del DNS inverso
    de la IP. Pasan sólo los que resuelven de vuelta a ``address``.

    Args:
        address: La IP escaneada.
        services: Los servicios del escaneo.
        limit: Máximo de sitios; a cero no se hace ninguna consulta.
        tls_fetch: ``(host, port, starttls=None) -> TlsInfo | None``.
        reverse_lookup: ``ip -> nombre | None``. Por defecto, el PTR del sistema.
        resolve: ``nombre -> set de IPs``. Por defecto, el resolutor del sistema.

    Returns:
        list: Pares ``(nombre, origen)``; vacía si no hay ninguno.
    """
    if limit <= 0:
        return []
    reverse_lookup = reverse_lookup or _reverse_name
    resolve = resolve or _addresses_of

    candidates: List[Tuple[str, str]] = []
    for service in services:
        is_ftp = is_ftp_service(service) and not is_tls_service(service) and service.port != 990
        if not (is_ftp or is_tls_service(service) or (is_http_service(service) and service.port == 443)):
            continue
        info = tls_fetch(address, service.port, starttls="ftp") if is_ftp else tls_fetch(address, service.port)
        for name in getattr(info, "names", None) or ():
            candidates.append((name, f"certificado TLS de {service.port}/tcp"))
    ptr = reverse_lookup(address)
    if ptr:
        candidates.append((ptr, "DNS inverso de la IP"))

    return select_site_names(candidates, lambda name: address in resolve(name), limit)


def _reverse_name(address: str) -> Optional[str]:
    """El nombre del registro PTR de ``address``, o ``None`` si no tiene."""
    try:
        return socket.gethostbyaddr(address)[0]
    except OSError:
        return None


def _addresses_of(name: str) -> set:
    """Las IPs a las que resuelve ``name``; vacío si no resuelve."""
    try:
        return {info[4][0] for info in socket.getaddrinfo(name, None)}
    except OSError:
        return set()
