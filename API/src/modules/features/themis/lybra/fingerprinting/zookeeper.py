"""El dissector de Apache ZooKeeper.

ZooKeeper guarda la configuración y la coordinación de medio ecosistema de
datos (Kafka, Hadoop, HBase, Solr, Druid) y **no autentica por defecto**: sin
ACL configuradas, cualquiera que alcance el puerto 2181 puede listar, leer y
cambiar los nodos. Dos preguntas, de naturaleza distinta, por dos conexiones
distintas:

* **Las palabras de cuatro letras** (``srvr``): un comando de texto que el
  servidor contesta y cierra. Da la versión (``Zookeeper version: 3.7.1-...``).
  Desde la 3.5 solo ``srvr`` está en la lista blanca por defecto, y un
  servidor endurecido puede no contestarla: entonces no hay versión, pero eso
  no dice nada sobre si deja entrar.
* **Una sesión real del protocolo binario**: ``ConnectRequest`` y un
  ``getChildren`` sobre ``/``. Es la evidencia del hallazgo. Que el servidor
  abra la sesión y devuelva los hijos de la raíz significa que se puede leer el
  árbol sin credencial; un servidor con ACL o SASL obligatorio contesta
  ``NoAuth`` (-102) o cierra. La sesión se cierra explícitamente al terminar
  para no dejarle una abierta hasta que caduque por plazo.

Ninguna de las dos preguntas escribe nada. El parseo es a mano, sin ``kazoo``.
"""

from __future__ import annotations

import logging
import re
import socket
import struct
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ..checks import is_zookeeper_service
from .dispatch import Dissector, DissectorResult
from .registry import register_dissector

logger = logging.getLogger(__name__)

_PRODUCT = "ZooKeeper"
_VERSION_RE = re.compile(r"Zookeeper version:\s*(\d+(?:\.\d+)+)", re.IGNORECASE)
_MAX_REPLY_BYTES = 65536

#: Tipos de operación del protocolo (``OpCode`` de ZooKeeper) que usa la sonda.
OP_GET_CHILDREN = 8
OP_CLOSE_SESSION = -11

#: Plazo de sesión que se pide, en milisegundos. El servidor lo acota a su
#: rango; solo importa que sea positivo.
_SESSION_TIMEOUT_MS = 10000


@dataclass(frozen=True)
class ZookeeperFingerprint:
    """Lo que se sabe de un ZooKeeper tras las dos preguntas.

    Attributes:
        product: ``"ZooKeeper"``, o ``None`` si ninguna de las dos respuestas
            era de un ZooKeeper.
        version: La versión que publicó ``srvr``, o ``None`` (no contestó, o
            no está en la lista blanca de palabras de cuatro letras).
        allows_unauthenticated_access: ``True`` si el servidor abrió una
            sesión sin credenciales y devolvió los hijos de ``/``.
    """
    product: Optional[str]
    version: Optional[str]
    allows_unauthenticated_access: bool = False


def parse_srvr_version(reply: str) -> Optional[str]:
    """Extrae la versión de la respuesta a ``srvr``.

    Args:
        reply: El texto devuelto, que empieza por ``Zookeeper version: 3.7.1-<hash>,
            built on <fecha>``.

    Returns:
        str | None: La parte numérica de la versión (``"3.7.1"``), o ``None``
        si la respuesta no es la de ``srvr`` (p. ej. el aviso de que el
        comando no está en la lista blanca).
    """
    match = _VERSION_RE.search(reply or "")
    return match.group(1) if match else None


def build_connect_request() -> bytes:
    """Construye el ``ConnectRequest`` que abre una sesión.

    Returns:
        bytes: El marco completo, con su prefijo de longitud: versión de
        protocolo 0, último ``zxid`` visto 0, plazo de sesión, ``sessionId``
        0 (sesión nueva) y una contraseña de sesión de 16 bytes a cero.
    """
    body = struct.pack(">iqiqi", 0, 0, _SESSION_TIMEOUT_MS, 0, 16) + bytes(16)
    return struct.pack(">i", len(body)) + body


def build_get_children_request(path: str = "/", xid: int = 1) -> bytes:
    """Construye un ``getChildren`` sin vigilancia (``watch = false``).

    Args:
        path: El nodo cuyos hijos se piden. Por defecto la raíz, ``"/"``.
        xid: El identificador de la petición, que el servidor repite en la
            respuesta. Por defecto 1.

    Returns:
        bytes: El marco completo, con su prefijo de longitud.
    """
    encoded = path.encode("utf-8")
    body = (struct.pack(">ii", xid, OP_GET_CHILDREN) + struct.pack(">i", len(encoded))
            + encoded + b"\x00")
    return struct.pack(">i", len(body)) + body


def build_close_session_request(xid: int = 2) -> bytes:
    """Construye el ``closeSession`` con el que la sonda termina su sesión.

    Args:
        xid: El identificador de la petición. Por defecto 2.

    Returns:
        bytes: El marco completo, con su prefijo de longitud.
    """
    body = struct.pack(">ii", xid, OP_CLOSE_SESSION)
    return struct.pack(">i", len(body)) + body


def parse_connect_response(frame: bytes) -> bool:
    """Dice si el servidor aceptó la sesión.

    Args:
        frame: El cuerpo del marco de respuesta, **sin** su prefijo de
            longitud: versión de protocolo, plazo concedido, ``sessionId`` y
            contraseña.

    Returns:
        bool: ``True`` si el plazo concedido es positivo y el ``sessionId`` no
        es cero. Un servidor que rechaza la sesión contesta con plazo 0.
    """
    if len(frame) < 16:
        return False
    _protocol, timeout, session_id = struct.unpack_from(">iiq", frame, 0)
    return timeout > 0 and session_id != 0


def parse_get_children_response(frame: bytes) -> Optional[List[str]]:
    """Lee la respuesta a ``getChildren``.

    Args:
        frame: El cuerpo del marco de respuesta, **sin** su prefijo de
            longitud: ``xid``, ``zxid``, código de error y, si el error es 0,
            el vector de nombres.

    Returns:
        list | None: Los nombres de los hijos (vacía si el nodo no tiene),
        o ``None`` si el servidor contestó con un error —``NoAuth`` incluido—
        o la respuesta está truncada.
    """
    if len(frame) < 16:
        return None
    _xid, _zxid, error = struct.unpack_from(">iqi", frame, 0)
    if error != 0:
        return None
    offset = 16
    if len(frame) < offset + 4:
        return None
    (count,) = struct.unpack_from(">i", frame, offset)
    offset += 4
    children: List[str] = []
    for _ in range(max(count, 0)):
        if len(frame) < offset + 4:
            return None
        (length,) = struct.unpack_from(">i", frame, offset)
        offset += 4
        if length < 0 or len(frame) < offset + length:
            return None
        children.append(frame[offset:offset + length].decode("utf-8", "replace"))
        offset += length
    return children


def fingerprint_zookeeper(srvr_reply: str,
                          children: Optional[List[str]] = None) -> ZookeeperFingerprint:
    """Construye el fingerprint a partir de las dos lecturas.

    Args:
        srvr_reply: La respuesta a ``srvr``, o cadena vacía si no hubo.
        children: Los hijos de ``/`` si la sesión se abrió y el servidor los
            devolvió; ``None`` si no hubo sesión o hubo error. Por defecto,
            ``None``.

    Returns:
        ZookeeperFingerprint: Con ``product`` a ``None`` si ninguna de las dos
        lecturas era de un ZooKeeper.
    """
    version = parse_srvr_version(srvr_reply)
    is_open = children is not None
    return ZookeeperFingerprint(
        product=_PRODUCT if (version or is_open) else None,
        version=version,
        allows_unauthenticated_access=is_open,
    )


# =========================================================================
# SONDA (el borde de red: socket crudo, sin kazoo)
# =========================================================================

def _read_exact(sock, size: int) -> Optional[bytes]:
    """Lee exactamente ``size`` bytes o devuelve ``None`` si el socket se cierra antes."""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _read_frame(sock) -> Optional[bytes]:
    """Lee un marco del protocolo binario: longitud de cuatro bytes y ese cuerpo.

    Args:
        sock: El socket conectado y con su plazo puesto.

    Returns:
        bytes | None: El cuerpo sin el prefijo, o ``None`` si el socket se
        cerró, la longitud es absurda o hubo un fallo de red.
    """
    try:
        header = _read_exact(sock, 4)
        if header is None:
            return None
        (length,) = struct.unpack(">i", header)
        if length <= 0 or length > _MAX_REPLY_BYTES:
            return None
        return _read_exact(sock, length)
    except OSError:
        return None


def _four_letter_word(connect: Callable, timeout: float, host: str, port: int,
                      word: bytes) -> Optional[str]:
    """Manda una palabra de cuatro letras y devuelve la respuesta.

    Args:
        connect: El ``(address, timeout) -> socket`` con el que conectar.
        timeout: El plazo de conexión y lectura, en segundos.
        host: El objetivo.
        port: El puerto de ZooKeeper.
        word: La palabra, p. ej. ``b"srvr"``.

    Returns:
        str | None: La respuesta, o ``None`` si no hubo conexión o el
        servidor no dijo nada.
    """
    try:
        sock = connect((host, port), timeout)
    except OSError as err:
        logger.debug("ZooKeeper: conexión fallida a %s:%s: %s", host, port, err)
        return None
    try:
        sock.settimeout(timeout)
        sock.sendall(word)
        data = b""
        while len(data) < _MAX_REPLY_BYTES:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", "ignore") or None
    except OSError:
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _read_root(connect: Callable, timeout: float, host: str, port: int) -> Optional[List[str]]:
    """Abre una sesión sin credenciales y lista los hijos de ``/``.

    Args:
        connect: El ``(address, timeout) -> socket`` con el que conectar.
        timeout: El plazo de conexión y lectura, en segundos.
        host: El objetivo.
        port: El puerto de ZooKeeper.

    Returns:
        list | None: Los nombres de los hijos de ``/``, o ``None`` si no hubo
        sesión, el servidor contestó un error (``NoAuth`` incluido) o la
        respuesta está truncada.
    """
    try:
        sock = connect((host, port), timeout)
    except OSError as err:
        logger.debug("ZooKeeper: conexión fallida a %s:%s: %s", host, port, err)
        return None
    try:
        sock.settimeout(timeout)
        sock.sendall(build_connect_request())
        connect_frame = _read_frame(sock)
        if connect_frame is None or not parse_connect_response(connect_frame):
            return None
        sock.sendall(build_get_children_request("/", xid=1))
        children_frame = _read_frame(sock)
        children = parse_get_children_response(children_frame) if children_frame else None
        try:
            sock.sendall(build_close_session_request())
        except OSError:
            pass
        return children
    except OSError as err:
        logger.debug("ZooKeeper: intercambio fallido con %s:%s: %s", host, port, err)
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


class ZookeeperProbe:  # pylint: disable=too-few-public-methods
    """Pregunta ``srvr`` por una conexión y lee ``/`` por otra.

    Son dos conexiones porque las palabras de cuatro letras las contesta el
    servidor y cierra: no se pueden encadenar con una sesión binaria.

    Args:
        timeout: El plazo de conexión y lectura, en segundos. Por defecto 5.
        connect: Callable ``(address, timeout) -> socket`` inyectable, para que
            un test use un socket falso. Por defecto, ``socket.create_connection``.
    """

    def __init__(self, timeout: float = 5.0, connect: Optional[Callable] = None) -> None:
        self._timeout = timeout
        self._connect = connect or socket.create_connection

    def fetch(self, host: str, port: int = 2181) -> Optional[Tuple[str, Optional[List[str]]]]:
        """Hace las dos preguntas contra ``host:port``.

        Args:
            host: El objetivo.
            port: El puerto de ZooKeeper. Por defecto 2181.

        Returns:
            tuple | None: Un par ``(respuesta a srvr, hijos de "/")``, con la
            primera vacía si el servidor no contestó a ``srvr`` y los segundos
            ``None`` si no abrió sesión o contestó un error; ``None`` entero
            si no hubo ni conexión.
        """
        srvr_reply = _four_letter_word(self._connect, self._timeout, host, port, b"srvr")
        children = _read_root(self._connect, self._timeout, host, port)
        if srvr_reply is None and children is None:
            return None
        return srvr_reply or "", children


@register_dissector
class ZookeeperDissector(Dissector):
    """``srvr`` para la versión, una sesión sin credenciales para saber si hay puerta."""

    label = "ZooKeeper"

    def __init__(self, probe: Optional[ZookeeperProbe] = None) -> None:
        self._probe = probe or ZookeeperProbe()

    def applies(self, service) -> bool:
        return is_zookeeper_service(service)

    def probe(self, target, service, rate_limiter):
        rate_limiter.acquire(target)
        readings = self._probe.fetch(target, service.port or 2181)
        if readings is None:
            return None
        fingerprint = fingerprint_zookeeper(*readings)
        if not fingerprint.product:
            return None
        return DissectorResult(fingerprint.product, fingerprint.version, self.label)
