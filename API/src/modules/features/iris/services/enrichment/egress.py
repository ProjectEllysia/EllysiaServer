"""
La única puerta de Iris hacia internet.

Pedir una URL que viene de un correo de phishing es la operación con más riesgo
de SSRF (que el servidor acabe pidiendo algo de su propia red interna) de todo
el módulo. Esta capa lo impide así:

- **Protocolos y puertos**: solo ``http`` y ``https``, a los puertos web
  habituales (``ALLOWED_PORTS``).
- **Direcciones**: el nombre se resuelve aquí, y si **cualquiera** de sus
  direcciones es privada, de loopback, link-local, multicast o reservada, no se
  conecta. Un nombre que resuelve a una pública y a una privada es justo el
  truco que se busca.
- **DNS rebinding**: la conexión va a la dirección ya comprobada, no al nombre.
  Un DNS que contesta una IP pública al comprobar y una privada al conectar no
  tiene segunda oportunidad, porque no hay segunda resolución.
- **Redirects**: no se siguen solos. ``fetch_following`` los sigue a mano y
  cada salto pasa otra vez por todas las comprobaciones.
- **Sin credenciales**: ni cookies, ni ``Authorization``, ni el ``usuario:clave@``
  que traiga la URL. Se manda un ``User-Agent`` propio. La única excepción son
  las claves de API de un proveedor de reputación, que el adaptador pasa
  explícitamente en ``extra_headers`` para llamar a **ese** proveedor.
- **Límites**: tiempo por operación de red y bytes leídos.

A propósito no hay interruptor para permitir direcciones privadas, ni siquiera
en desarrollo: una garantía de seguridad no se rebaja por configuración.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

#: Protocolos que se piden. ``ftp``, ``file``, ``gopher``… no.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Puertos a los que se conecta. Los web y sus alternativos habituales; un
#: enlace a ``:22`` o ``:6379`` no es una página, es un intento de hablar con
#: otro servicio.
ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})

#: Cómo se presenta Ellysia al pedir algo fuera.
USER_AGENT = "Ellysia-Iris/1.0 (+https://ellysia.es; enrichment)"

#: Métodos que se usan: leer una página o consultar la API de un proveedor.
_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST"})

#: Códigos HTTP que son un redirect.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class EgressBlockedError(Exception):
    """Una petición que no se hace porque saldría de lo permitido.

    Attributes:
        reason: Por qué: ``method``, ``scheme``, ``port``, ``host``,
            ``unresolvable``, ``private_address`` o ``too_many_redirects``.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        """Construye el error.

        Args:
            reason: Motivo estable (ver la clase).
            detail: Explicación técnica para el log. Por defecto vacía.
        """
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class EgressResponse:
    """Respuesta de una petición, ya leída.

    Attributes:
        url: URL pedida.
        status: Código HTTP.
        headers: Cabeceras, con los nombres en minúsculas.
        body: Cuerpo, como mucho ``max_bytes``.
        is_truncated: Si el cuerpo era más largo y se cortó.
        peer_address: Dirección IP a la que se conectó.
        certificate: Certificado del servidor en HTTPS (``subject``,
            ``issuer``, ``notBefore``, ``notAfter``), o ``None`` en HTTP.
    """

    url: str
    status: int
    headers: Dict[str, str]
    body: bytes
    is_truncated: bool
    peer_address: str
    certificate: Optional[Dict[str, str]] = None

    @property
    def is_redirect(self) -> bool:
        """Si la respuesta es un redirect con destino."""
        return self.status in _REDIRECT_STATUSES and bool(self.headers.get("location"))


@dataclass(frozen=True)
class EgressHop:
    """Un salto de una cadena de redirects, para enseñarlo.

    Attributes:
        url: URL pedida en este salto.
        status: Código HTTP, o ``None`` si la petición no llegó a hacerse.
        peer_address: IP a la que se conectó, o ``None``.
        certificate: Certificado del salto HTTPS, o ``None``.
        error: Por qué se cortó aquí (``private_address``, ``timeout``…), o
            ``None`` si respondió.
    """

    url: str
    status: Optional[int] = None
    peer_address: Optional[str] = None
    certificate: Optional[Dict[str, str]] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class RedirectChain:
    """Resultado de seguir los redirects de una URL.

    Attributes:
        hops: Cada salto, en orden.
        final: Última respuesta obtenida, o ``None`` si ningún salto respondió.
    """

    hops: Tuple[EgressHop, ...] = field(default_factory=tuple)
    final: Optional[EgressResponse] = None


def is_blocked_address(address: str) -> bool:
    """Si una IP no es de internet y no se le debe hacer ninguna petición.

    Args:
        address: IPv4 o IPv6.

    Returns:
        bool: ``True`` para privadas, loopback, link-local, multicast,
            reservadas y sin especificar, también si vienen envueltas en una
            IPv6 (``::ffff:10.0.0.1``). ``True`` si no es una IP válida.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified or not ip.is_global)


def resolve_public_address(host: str, port: int) -> str:
    """Resuelve un nombre y comprueba que todas sus direcciones son públicas.

    Args:
        host: Nombre o IP literal.
        port: Puerto al que se va a conectar.

    Returns:
        str: La primera dirección pública, a la que se conectará.

    Raises:
        EgressBlockedError: ``unresolvable`` si no resuelve, o
            ``private_address`` si alguna dirección no es pública.
    """
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise EgressBlockedError("unresolvable", f"{host}: {e}") from e
    addresses = [result[4][0] for result in results]
    if not addresses:
        raise EgressBlockedError("unresolvable", host)
    blocked = [address for address in addresses if is_blocked_address(address)]
    if blocked:
        raise EgressBlockedError("private_address", f"{host} → {', '.join(blocked)}")
    return addresses[0]


def fetch(url: str, *, timeout_seconds: float, max_bytes: int, method: str = "GET",
          accept: str = "*/*", extra_headers: Optional[Dict[str, str]] = None,
          body: Optional[bytes] = None) -> EgressResponse:
    """Hace una petición, sin seguir redirects, con todas las comprobaciones.

    Args:
        url: URL absoluta ``http`` o ``https``.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes del cuerpo que se leen como mucho.
        method: ``GET``, ``HEAD`` o ``POST``. Por defecto ``GET``.
        accept: Cabecera ``Accept``. Por defecto ``*/*``.
        extra_headers: Cabeceras añadidas, solo para la clave de API y el tipo
            de contenido de una llamada a un proveedor. Por defecto ``None``.
        body: Cuerpo de un ``POST``. Por defecto ``None``.

    Returns:
        EgressResponse: La respuesta.

    Raises:
        EgressBlockedError: Si la URL sale de lo permitido.
        OSError: Si falla la red (``socket.timeout``, conexión rechazada,
            error TLS…).
        http.client.HTTPException: Si la respuesta no es HTTP válido.
    """
    if method not in _ALLOWED_METHODS:
        raise EgressBlockedError("method", method)
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise EgressBlockedError("scheme", scheme or "(ninguno)")
    host = parts.hostname
    if not host:
        raise EgressBlockedError("host", url)
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise EgressBlockedError("port", str(e)) from e
    if port not in ALLOWED_PORTS:
        raise EgressBlockedError("port", str(port))
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise EgressBlockedError("host", host) from e
    address = resolve_public_address(ascii_host, port)

    connection_class = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
    connection = connection_class(ascii_host, address, port, timeout_seconds)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    host_header = ascii_host if port in (80, 443) else f"{ascii_host}:{port}"
    try:
        headers = {
            "Host": host_header, "User-Agent": USER_AGENT, "Accept": accept,
            "Accept-Encoding": "identity", "Connection": "close",
        }
        headers.update(extra_headers or {})
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        body = response.read(max_bytes + 1) if method != "HEAD" else b""
        certificate = connection.peer_certificate()
        return EgressResponse(
            url=url, status=response.status,
            headers={name.lower(): value for name, value in response.getheaders()},
            body=body[:max_bytes], is_truncated=len(body) > max_bytes,
            peer_address=address, certificate=certificate,
        )
    finally:
        connection.close()


def fetch_following(url: str, *, max_redirects: int, timeout_seconds: float, max_bytes: int,
                    method: str = "GET", accept: str = "*/*") -> RedirectChain:
    """Pide una URL y sigue sus redirects, comprobando cada salto.

    Nunca lanza por la red: un salto que no se puede hacer queda en la cadena
    con su ``error`` y la cadena se corta ahí.

    Args:
        url: URL de partida.
        max_redirects: Redirects que se siguen como mucho.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes del cuerpo que se leen de cada salto.
        method: ``GET`` o ``HEAD``. Por defecto ``GET``.
        accept: Cabecera ``Accept``. Por defecto ``*/*``.

    Returns:
        RedirectChain: Los saltos y la última respuesta obtenida.
    """
    hops: List[EgressHop] = []
    current_url = url
    final: Optional[EgressResponse] = None
    for _ in range(max_redirects + 1):
        try:
            response = fetch(current_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes,
                             method=method, accept=accept)
        except EgressBlockedError as e:
            hops.append(EgressHop(url=current_url, error=e.reason))
            return RedirectChain(hops=tuple(hops), final=final)
        except (OSError, http.client.HTTPException) as e:
            hops.append(EgressHop(url=current_url, error=_network_error_reason(e)))
            return RedirectChain(hops=tuple(hops), final=final)
        final = response
        hops.append(EgressHop(url=current_url, status=response.status, peer_address=response.peer_address,
                              certificate=response.certificate))
        if not response.is_redirect:
            return RedirectChain(hops=tuple(hops), final=final)
        current_url = urljoin(current_url, response.headers["location"].strip())
    hops.append(EgressHop(url=current_url, error="too_many_redirects"))
    return RedirectChain(hops=tuple(hops), final=final)


def _network_error_reason(error: Exception) -> str:
    """Motivo estable de un fallo de red, para guardarlo y enseñarlo.

    Args:
        error: La excepción.

    Returns:
        str: ``timeout``, ``tls``, ``connection`` o ``protocol``.
    """
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(error, ssl.SSLError):
        return "tls"
    if isinstance(error, http.client.HTTPException):
        return "protocol"
    return "connection"


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Conexión HTTP a una IP ya comprobada, con el nombre solo en ``Host``."""

    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        """Prepara la conexión.

        Args:
            host: Nombre del servidor (para ``Host`` y SNI).
            address: IP comprobada a la que se conecta.
            port: Puerto.
            timeout: Tiempo máximo de cada operación de red.
        """
        super().__init__(address, port, timeout=timeout)
        self.server_name = host

    def peer_certificate(self) -> Optional[Dict[str, str]]:
        """Certificado del servidor; en HTTP no hay ninguno.

        Returns:
            Optional[dict]: Siempre ``None``.
        """
        return None


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    """Conexión HTTPS a una IP ya comprobada, verificando el certificado contra el nombre."""

    default_port = 443

    def connect(self) -> None:
        """Abre el socket a la IP comprobada y negocia TLS con el nombre como SNI.

        Redefine ``http.client.HTTPConnection.connect``: la conexión va a
        ``self.host`` (la IP), y el certificado se verifica contra
        ``self.server_name`` (el nombre), como haría un navegador.
        """
        raw_socket = socket.create_connection((self.host, self.port), self.timeout)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(raw_socket, server_hostname=self.server_name)

    def peer_certificate(self) -> Optional[Dict[str, str]]:
        """Resumen del certificado que presentó el servidor.

        Returns:
            Optional[dict]: ``subject``, ``issuer``, ``notBefore`` y ``notAfter``,
                o ``None`` si no hay socket TLS.
        """
        if not isinstance(self.sock, ssl.SSLSocket):
            return None
        certificate = self.sock.getpeercert() or {}
        return {
            "subject": _flatten_name(certificate.get("subject", ())),
            "issuer": _flatten_name(certificate.get("issuer", ())),
            "notBefore": certificate.get("notBefore", ""),
            "notAfter": certificate.get("notAfter", ""),
        }


def _flatten_name(name: tuple) -> str:
    """Convierte el nombre distinguido de ``getpeercert`` en ``CN=…, O=…``.

    Args:
        name: Tupla de RDNs tal como la da ``ssl``.

    Returns:
        str: Los atributos separados por comas.
    """
    return ", ".join(f"{key}={value}" for rdn in name for key, value in rdn)
