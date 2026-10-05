"""El dissector de Apache Cassandra (y ScyllaDB), por el protocolo nativo CQL.

Cassandra no tiene autenticación por defecto: el ``AllowAllAuthenticator`` con
el que se instala deja entrar a cualquiera que alcance el puerto 9042, y
desde ahí se lee y se borra cualquier tabla. El protocolo nativo (binario, por
marcos) permite saber si hay puerta **sin iniciar sesión**:

* ``OPTIONS`` pregunta qué soporta el servidor. Contesta ``SUPPORTED`` siempre,
  con o sin autenticación. ScyllaDB —que habla el mismo protocolo— añade claves
  ``SCYLLA_*`` a esa respuesta, y es lo que lo distingue.
* ``STARTUP`` abre la conexión. Un servidor **sin** autenticación contesta
  ``READY``; uno que la exige contesta ``AUTHENTICATE`` con el nombre de su
  autenticador. Esa es la evidencia, binaria y sin ambigüedad.
* Con ``READY``, una consulta ``SELECT release_version FROM system.local``
  (una lectura de catálogo) da la versión. Un servidor con autenticación no la
  da: la versión solo se conoce cuando la puerta está abierta.

La versión no se pregunta a ScyllaDB: su ``release_version`` es la de
compatibilidad con Cassandra, no la suya, y cruzarla con las CVE de Cassandra
produciría hallazgos falsos.

El parseo es a mano, sin ``cassandra-driver``. Se negocia el protocolo v4
(Cassandra 2.2 en adelante) y se retrocede a v3 (2.1) si el servidor no lo
entiende.
"""

from __future__ import annotations

import logging
import socket
import struct
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from ..checks import is_cassandra_service
from .dispatch import Dissector, DissectorResult
from .registry import register_dissector

logger = logging.getLogger(__name__)

OPCODE_ERROR = 0x00
OPCODE_STARTUP = 0x01
OPCODE_READY = 0x02
OPCODE_AUTHENTICATE = 0x03
OPCODE_OPTIONS = 0x05
OPCODE_SUPPORTED = 0x06
OPCODE_QUERY = 0x07
OPCODE_RESULT = 0x08

#: Versiones del protocolo nativo que se intentan, de la más moderna a la más
#: antigua. v5 se omite a propósito: exige negociar el formato de marco nuevo.
_PROTOCOL_VERSIONS = (4, 3)

_RESPONSE_FLAG = 0x80
_HEADER_SIZE = 9
_MAX_BODY_BYTES = 262144
_RESULT_KIND_ROWS = 0x0002
_COLUMN_TYPE_VARCHAR = 0x000D
_QUERY_VERSION = b"SELECT release_version FROM system.local"
_CONSISTENCY_ONE = 0x0001


@dataclass(frozen=True)
class CassandraFingerprint:
    """Lo que se sabe de un servidor CQL tras ``OPTIONS``, ``STARTUP`` y la consulta de versión.

    Attributes:
        product: ``"Cassandra"`` o ``"ScyllaDB"``, o ``None`` si lo que
            contestó no era un servidor CQL.
        version: La ``release_version`` de Cassandra, solo si el servidor la
            entregó sin credenciales; ``None`` en ScyllaDB (su versión de
            compatibilidad no es la suya) y en cualquier servidor con
            autenticación.
        allows_unauthenticated_access: ``True`` si ``STARTUP`` obtuvo
            ``READY``, es decir, si el servidor deja operar sin credenciales.
        authenticator: El autenticador que anunció un ``AUTHENTICATE``
            (``org.apache.cassandra.auth.PasswordAuthenticator``...), o
            ``None``.
    """
    product: Optional[str]
    version: Optional[str]
    allows_unauthenticated_access: bool = False
    authenticator: Optional[str] = None


# =========================================================================
# CODIFICACIÓN Y LECTURA DEL PROTOCOLO
# =========================================================================

def _string(value: str) -> bytes:
    """Codifica un ``[string]`` del protocolo: longitud corta y el texto en UTF-8."""
    encoded = value.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def build_frame(protocol_version: int, opcode: int, body: bytes = b"", stream: int = 1) -> bytes:
    """Construye un marco de petición.

    Args:
        protocol_version: La versión del protocolo (3 o 4).
        opcode: El código de operación (``OPCODE_*``).
        body: El cuerpo ya codificado. Por defecto, vacío.
        stream: El identificador de flujo, que el servidor repite en su
            respuesta. Por defecto 1.

    Returns:
        bytes: El marco completo: cabecera de nueve bytes y cuerpo.
    """
    return struct.pack(">BBhBi", protocol_version, 0, stream, opcode, len(body)) + body


def build_startup(protocol_version: int) -> bytes:
    """Construye el ``STARTUP`` con la única opción obligatoria, ``CQL_VERSION``.

    Args:
        protocol_version: La versión del protocolo (3 o 4).

    Returns:
        bytes: El marco, con el mapa ``{"CQL_VERSION": "3.0.0"}`` como cuerpo.
    """
    body = struct.pack(">H", 1) + _string("CQL_VERSION") + _string("3.0.0")
    return build_frame(protocol_version, OPCODE_STARTUP, body)


def build_version_query(protocol_version: int) -> bytes:
    """Construye la consulta que lee ``release_version`` de ``system.local``.

    Args:
        protocol_version: La versión del protocolo (3 o 4).

    Returns:
        bytes: El marco ``QUERY``: la consulta como ``[long string]``,
        consistencia ``ONE`` y ningún indicador.
    """
    body = (struct.pack(">i", len(_QUERY_VERSION)) + _QUERY_VERSION
            + struct.pack(">HB", _CONSISTENCY_ONE, 0))
    return build_frame(protocol_version, OPCODE_QUERY, body)


def parse_frame_header(header: bytes) -> Optional[Tuple[int, int, int]]:
    """Lee la cabecera de un marco de respuesta.

    Args:
        header: Los nueve primeros bytes del marco.

    Returns:
        tuple | None: ``(versión, código de operación, longitud del cuerpo)``,
        o ``None`` si la cabecera no es de una respuesta CQL (bit de respuesta
        apagado), es más corta de lo debido o declara un cuerpo absurdo.
    """
    if len(header) < _HEADER_SIZE:
        return None
    version_byte, _flags, _stream, opcode, length = struct.unpack(">BBhBi", header[:_HEADER_SIZE])
    if not version_byte & _RESPONSE_FLAG or length < 0 or length > _MAX_BODY_BYTES:
        return None
    return version_byte & 0x7F, opcode, length


def parse_supported(body: bytes) -> Dict[str, List[str]]:
    """Lee el cuerpo de un ``SUPPORTED``: un ``[string multimap]``.

    Args:
        body: El cuerpo del marco.

    Returns:
        dict: ``{opción: [valores]}``. Vacío si el cuerpo está truncado.
    """
    options: Dict[str, List[str]] = {}
    try:
        (count,) = struct.unpack_from(">H", body, 0)
        offset = 2
        for _ in range(count):
            (key_length,) = struct.unpack_from(">H", body, offset)
            offset += 2
            key = body[offset:offset + key_length].decode("utf-8", "replace")
            offset += key_length
            (value_count,) = struct.unpack_from(">H", body, offset)
            offset += 2
            values = []
            for _ in range(value_count):
                (value_length,) = struct.unpack_from(">H", body, offset)
                offset += 2
                values.append(body[offset:offset + value_length].decode("utf-8", "replace"))
                offset += value_length
            options[key] = values
    except struct.error:
        return {}
    return options


def parse_authenticator(body: bytes) -> Optional[str]:
    """Lee el nombre del autenticador de un ``AUTHENTICATE``.

    Args:
        body: El cuerpo del marco: un ``[string]`` con el nombre de la clase.

    Returns:
        str | None: El nombre, o ``None`` si el cuerpo está truncado.
    """
    if len(body) < 2:
        return None
    (length,) = struct.unpack_from(">H", body, 0)
    if len(body) < 2 + length:
        return None
    return body[2:2 + length].decode("utf-8", "replace")


def parse_release_version(body: bytes) -> Optional[str]:  # pylint: disable=too-many-return-statements
    """Lee la ``release_version`` del ``RESULT`` de la consulta a ``system.local``.

    Solo entiende la forma que tiene esa consulta: un resultado de filas con
    una única columna ``varchar``. Cualquier otra forma devuelve ``None`` en
    vez de adivinar con un desplazamiento equivocado.

    Args:
        body: El cuerpo del marco ``RESULT``.

    Returns:
        str | None: La versión, o ``None`` si no es un resultado de filas, la
        columna no es ``varchar``, no hay filas o el cuerpo está truncado.
    """
    try:
        kind, flags, column_count = struct.unpack_from(">iii", body, 0)
        if kind != _RESULT_KIND_ROWS or column_count != 1:
            return None
        offset = 12
        if flags & 0x0002:                       # has_more_pages
            (paging_length,) = struct.unpack_from(">i", body, offset)
            offset += 4 + max(paging_length, 0)
        if flags & 0x0004:                       # no_metadata
            return None
        # Keyspace y tabla: una vez en la cabecera si hay ``global_tables_spec``
        # y, si no, delante de cada columna; con una sola columna es lo mismo.
        for _ in range(2):
            (length,) = struct.unpack_from(">H", body, offset)
            offset += 2 + length
        (name_length,) = struct.unpack_from(">H", body, offset)
        offset += 2 + name_length
        (type_id,) = struct.unpack_from(">H", body, offset)
        offset += 2
        if type_id != _COLUMN_TYPE_VARCHAR:
            return None
        (row_count,) = struct.unpack_from(">i", body, offset)
        offset += 4
        if row_count < 1:
            return None
        (value_length,) = struct.unpack_from(">i", body, offset)
        offset += 4
        if value_length <= 0 or len(body) < offset + value_length:
            return None
        return body[offset:offset + value_length].decode("utf-8", "replace")
    except struct.error:
        return None


def fingerprint_cassandra(supported: Dict[str, List[str]], startup_opcode: Optional[int],
                          startup_body: bytes = b"",
                          result_body: bytes = b"") -> CassandraFingerprint:
    """Construye el fingerprint a partir de lo que contestó el servidor.

    Args:
        supported: Las opciones de su ``SUPPORTED`` (``{}`` si no contestó).
        startup_opcode: El código de operación con el que contestó a
            ``STARTUP`` (``OPCODE_READY``, ``OPCODE_AUTHENTICATE``...), o
            ``None`` si no hubo respuesta.
        startup_body: El cuerpo de esa respuesta. Por defecto, vacío.
        result_body: El cuerpo del ``RESULT`` de la consulta de versión, si se
            hizo. Por defecto, vacío.

    Returns:
        CassandraFingerprint: Con ``product`` a ``None`` si no hay forma de
        saber que se habló con un servidor CQL.
    """
    is_cql = bool(supported) or startup_opcode in (OPCODE_READY, OPCODE_AUTHENTICATE)
    if not is_cql:
        return CassandraFingerprint(None, None)
    is_scylla = any(option.upper().startswith("SCYLLA") for option in supported)
    is_open = startup_opcode == OPCODE_READY
    is_authenticating = startup_opcode == OPCODE_AUTHENTICATE
    authenticator = parse_authenticator(startup_body) if is_authenticating else None
    version = None if is_scylla or not is_open else parse_release_version(result_body)
    return CassandraFingerprint(
        product="ScyllaDB" if is_scylla else "Cassandra",
        version=version,
        allows_unauthenticated_access=is_open,
        authenticator=authenticator,
    )


# =========================================================================
# SONDA (el borde de red: socket crudo, sin cassandra-driver)
# =========================================================================

def _read_response(sock) -> Optional[Tuple[int, int, bytes]]:
    """Lee un marco de respuesta entero.

    Args:
        sock: El socket conectado y con su plazo puesto.

    Returns:
        tuple | None: ``(versión, código de operación, cuerpo)``, o ``None`` si
        el socket se cerró, la cabecera no era de una respuesta CQL o hubo un
        fallo de red.
    """
    try:
        header = b""
        while len(header) < _HEADER_SIZE:
            chunk = sock.recv(_HEADER_SIZE - len(header))
            if not chunk:
                return None
            header += chunk
        parsed = parse_frame_header(header)
        if parsed is None:
            return None
        version, opcode, length = parsed
        body = b""
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                return None
            body += chunk
        return version, opcode, body
    except OSError:
        return None


def _finish(supported: Dict[str, List[str]], startup_opcode: Optional[int], startup_body: bytes,
            result_body: bytes) -> Optional[CassandraFingerprint]:
    """Devuelve el fingerprint, o ``None`` si lo leído no era de un servidor CQL.

    Args:
        supported: Las opciones de su ``SUPPORTED``.
        startup_opcode: El código con el que contestó a ``STARTUP``, o ``None``.
        startup_body: El cuerpo de esa respuesta.
        result_body: El cuerpo del ``RESULT`` de la consulta de versión.

    Returns:
        CassandraFingerprint | None: El fingerprint, o ``None`` si no hay
        producto que reconocer.
    """
    fingerprint = fingerprint_cassandra(supported, startup_opcode, startup_body, result_body)
    return fingerprint if fingerprint.product else None


def _dialogue(connect: Callable, timeout: float, host: str, port: int, protocol_version: int):
    """Un intento completo con una versión del protocolo.

    Args:
        connect: El ``(address, timeout) -> socket`` con el que conectar.
        timeout: El plazo de conexión y lectura, en segundos.
        host: El objetivo.
        port: El puerto del protocolo nativo.
        protocol_version: La versión del protocolo a ofrecer (3 o 4).

    Returns:
        CassandraFingerprint | str | None: El fingerprint si el servidor
        habló CQL; ``"retry"`` si rechazó esta versión del protocolo (hay
        que probar una anterior); ``None`` si no hubo conexión o no era CQL.
    """
    try:
        sock = connect((host, port), timeout)
    except OSError as err:
        logger.debug("Cassandra: conexión fallida a %s:%s: %s", host, port, err)
        return None
    try:
        sock.settimeout(timeout)
        sock.sendall(build_frame(protocol_version, OPCODE_OPTIONS))
        options_reply = _read_response(sock)
        if options_reply is None:
            return None
        if options_reply[1] == OPCODE_ERROR:
            return "retry"
        supported = (parse_supported(options_reply[2])
                     if options_reply[1] == OPCODE_SUPPORTED else {})
        sock.sendall(build_startup(protocol_version))
        startup_reply = _read_response(sock)
        if startup_reply is None:
            return _finish(supported, None, b"", b"")
        startup_opcode, startup_body = startup_reply[1], startup_reply[2]
        result_body = b""
        if startup_opcode == OPCODE_READY:
            sock.sendall(build_version_query(protocol_version))
            result_reply = _read_response(sock)
            if result_reply is not None and result_reply[1] == OPCODE_RESULT:
                result_body = result_reply[2]
        return _finish(supported, startup_opcode, startup_body, result_body)
    except OSError as err:
        logger.debug("Cassandra: intercambio fallido con %s:%s: %s", host, port, err)
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


class CassandraProbe:  # pylint: disable=too-few-public-methods
    """Hace ``OPTIONS``, ``STARTUP`` y, si hay puerta, la consulta de versión.

    **Ningún mensaje escribe nada**: ``OPTIONS`` es informativo, ``STARTUP`` abre
    la conexión sin credenciales y la consulta es una lectura de catálogo.

    Args:
        timeout: El plazo de conexión y lectura, en segundos. Por defecto 5.
        connect: Callable ``(address, timeout) -> socket`` inyectable, para que
            un test use un socket falso. Por defecto, ``socket.create_connection``.
    """

    def __init__(self, timeout: float = 5.0, connect: Optional[Callable] = None) -> None:
        self._timeout = timeout
        self._connect = connect or socket.create_connection

    def fetch(self, host: str, port: int = 9042) -> Optional[CassandraFingerprint]:
        """Hace el diálogo contra ``host:port``, probando v4 y retrocediendo a v3.

        Args:
            host: El objetivo.
            port: El puerto del protocolo nativo. Por defecto 9042.

        Returns:
            CassandraFingerprint | None: El fingerprint, o ``None`` si no hubo
            conexión o lo que contestó no era un servidor CQL.
        """
        for protocol_version in _PROTOCOL_VERSIONS:
            outcome = _dialogue(self._connect, self._timeout, host, port, protocol_version)
            if outcome is None:
                return None
            if outcome == "retry":
                continue
            return outcome
        return None


@register_dissector
class CassandraDissector(Dissector):
    """``OPTIONS`` y ``STARTUP`` para saber qué es y si hay puerta."""

    label = "Cassandra"

    def __init__(self, probe: Optional[CassandraProbe] = None) -> None:
        self._probe = probe or CassandraProbe()

    def applies(self, service) -> bool:
        return is_cassandra_service(service)

    def probe(self, target, service, rate_limiter):
        rate_limiter.acquire(target)
        fingerprint = self._probe.fetch(target, service.port or 9042)
        if fingerprint is None or not fingerprint.product:
            return None
        return DissectorResult(fingerprint.product, fingerprint.version, self.label)
