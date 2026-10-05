"""El dissector de Memcached.

Memcached no saluda al conectar: espera un comando. Su protocolo de texto es de
una línea por comando, y no lleva autenticación alguna salvo que el servidor se
haya arrancado con SASL (y entonces el protocolo de texto queda deshabilitado).
Durante años las instalaciones por defecto escuchaban en todas las interfaces,
y de ahí salieron tanto fugas de datos de caché (sesiones, tokens, trozos de
base de datos) como los ataques de amplificación por UDP más voluminosos que
se recuerdan.

Dos comandos, ambos de **lectura** y sin ningún efecto sobre lo almacenado:

* ``version`` contesta ``VERSION 1.6.21``. Da el producto y la versión.
* ``stats`` contesta las estadísticas del servidor, una línea ``STAT <clave>
  <valor>`` por contador. Un servidor que no deja entrar sin credenciales no
  las devuelve; uno abierto, sí. Esa es la evidencia, y no que ``version``
  conteste: es el comando más inocuo del protocolo y un servidor con las
  restricciones activadas puede contestarlo igualmente.

El parseo es a mano sobre el protocolo de texto, sin ``pymemcache`` ni nada
parecido, por la misma razón que lleva a SNMP, MongoDB y compañía a prescindir
de su librería de cliente.
"""

from __future__ import annotations

import logging
import re
import socket
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from ..checks import is_memcached_service
from .dispatch import Dissector, DissectorResult
from .registry import register_dissector

logger = logging.getLogger(__name__)

_PRODUCT = "Memcached"
_VERSION_RE = re.compile(r"^VERSION\s+(\S+)", re.MULTILINE)
# Una línea de estadística: ``STAT pid 1``. Con una basta; un servidor que
# contesta ``ERROR`` o se calla no trae ninguna.
_STAT_RE = re.compile(r"^STAT\s+\S+\s+\S+", re.MULTILINE)
_MAX_REPLY_BYTES = 65536


@dataclass(frozen=True)
class MemcachedFingerprint:
    """Lo que se sabe de un Memcached tras preguntarle ``version`` y ``stats``.

    Attributes:
        product: ``"Memcached"``, o ``None`` si la respuesta a ``version`` no
            era la de un Memcached.
        version: La versión publicada, o ``None``.
        allows_unauthenticated_access: ``True`` si ``stats`` devolvió
            estadísticas; es lo que distingue un servidor abierto de uno que
            solo contesta ``version``.
    """
    product: Optional[str]
    version: Optional[str]
    allows_unauthenticated_access: bool = False


def parse_memcached_version(reply: str) -> Optional[str]:
    """Extrae la versión de la respuesta a ``version``.

    Args:
        reply: El texto de la respuesta, p. ej. ``"VERSION 1.6.21\\r\\n"``.

    Returns:
        str | None: La versión, o ``None`` si la respuesta no empieza por
        ``VERSION`` (otro servicio, o un Memcached que no contesta a este
        comando).
    """
    match = _VERSION_RE.search(reply or "")
    return match.group(1) if match else None


def fingerprint_memcached(version_reply: str, stats_reply: str = "") -> MemcachedFingerprint:
    """Construye el fingerprint a partir de las dos respuestas.

    Args:
        version_reply: La respuesta a ``version``.
        stats_reply: La respuesta a ``stats``. Por defecto, vacía: un servidor
            que no la dio no se toma por abierto.

    Returns:
        MemcachedFingerprint: Con ``product`` a ``None`` si lo primero no era
        Memcached.
    """
    version = parse_memcached_version(version_reply)
    if version is None:
        return MemcachedFingerprint(None, None)
    return MemcachedFingerprint(
        product=_PRODUCT,
        version=version,
        allows_unauthenticated_access=bool(_STAT_RE.search(stats_reply or "")),
    )


# =========================================================================
# SONDA (el borde de red: socket crudo, sin librería de cliente)
# =========================================================================

def _read_until(sock, terminator: bytes) -> bytes:
    """Lee del socket hasta ver ``terminator``, hasta el límite de bytes o hasta que se cierre.

    Args:
        sock: El socket ya conectado y con su plazo puesto.
        terminator: La secuencia que cierra la respuesta (``b"\\r\\n"`` para
            ``version``, ``b"END\\r\\n"`` para ``stats``).

    Returns:
        bytes: Lo leído, con el terminador incluido si llegó. Un fallo de red
        a medias devuelve lo acumulado hasta ese punto.
    """
    data = b""
    while terminator not in data and len(data) < _MAX_REPLY_BYTES:
        try:
            chunk = sock.recv(4096)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    return data


class MemcachedProbe:  # pylint: disable=too-few-public-methods
    """Manda ``version`` y ``stats`` sobre la misma conexión.

    **Ninguno de los dos comandos escribe nada.** ``stats`` es una lectura de
    contadores; se manda sin credenciales y su fracaso es tan informativo como
    su éxito.

    Args:
        timeout: El plazo de conexión y lectura, en segundos. Por defecto 5.
        connect: Callable ``(address, timeout) -> socket`` inyectable, para que
            un test use un socket falso. Por defecto, ``socket.create_connection``.
    """

    def __init__(self, timeout: float = 5.0, connect: Optional[Callable] = None) -> None:
        self._timeout = timeout
        self._connect = connect or socket.create_connection

    def fetch(self, host: str, port: int = 11211) -> Optional[Tuple[str, str]]:
        """Hace los dos intercambios contra ``host:port``.

        Args:
            host: El objetivo.
            port: El puerto de Memcached. Por defecto 11211.

        Returns:
            tuple | None: Un par ``(respuesta a version, respuesta a stats)``,
            con la segunda vacía si ``version`` no fue la de un Memcached, o
            ``None`` si ni siquiera ``version`` obtuvo respuesta.
        """
        try:
            sock = self._connect((host, port), self._timeout)
        except OSError as err:
            logger.debug("Memcached: conexión fallida a %s:%s: %s", host, port, err)
            return None
        try:
            sock.settimeout(self._timeout)
            sock.sendall(b"version\r\n")
            version_reply = _read_until(sock, b"\r\n").decode("ascii", "ignore")
            if not version_reply:
                return None
            if parse_memcached_version(version_reply) is None:
                return version_reply, ""
            sock.sendall(b"stats\r\n")
            return version_reply, _read_until(sock, b"END\r\n").decode("ascii", "ignore")
        except OSError as err:
            logger.debug("Memcached: intercambio fallido con %s:%s: %s", host, port, err)
            return None
        finally:
            try:
                sock.close()
            except OSError:
                pass


@register_dissector
class MemcachedDissector(Dissector):
    """``version`` para el producto y la versión; ``stats`` solo para el check."""

    label = "Memcached"

    def __init__(self, probe: Optional[MemcachedProbe] = None) -> None:
        self._probe = probe or MemcachedProbe()

    def applies(self, service) -> bool:
        return is_memcached_service(service)

    def probe(self, target, service, rate_limiter):
        rate_limiter.acquire(target)
        replies = self._probe.fetch(target, service.port or 11211)
        if replies is None:
            return None
        fingerprint = fingerprint_memcached(*replies)
        if not fingerprint.product:
            return None
        return DissectorResult(fingerprint.product, fingerprint.version, self.label)
