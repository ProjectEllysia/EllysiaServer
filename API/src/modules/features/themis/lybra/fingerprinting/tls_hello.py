"""El saludo inicial de TLS, hablado a mano sobre el socket.

El módulo :mod:`tls` pregunta a un servidor por su versión y su cifrado a través
de la librería TLS de Python, que sólo puede pedir lo que el sistema donde corre
todavía sabe hablar: para preguntar por TLS 1.0 o por una familia de cifrado que
ya no ofrece por defecto hay que forzar un contexto especial por cada pregunta.
Este módulo hace lo contrario: **construye el ``ClientHello`` byte a byte y lee
la respuesta del servidor sin completar el apretón de manos**, así que puede
anunciar cualquier combinación de versiones y de cifrados en una sola petición
y ver cuál elige el servidor, sin depender de qué soporte la librería instalada.

Es una pieza de bajo nivel, sin ningún check encima. Devuelve lo que el servidor
contesta tal cual —el ``ServerHello``, la alerta con la que rechaza, y el resto
de mensajes del primer vuelo (``Certificate``, ``ServerKeyExchange``…) sin
interpretar— para que quien la use decida qué preguntar y qué concluir.

**Formato** (RFC 5246 §6.2 y §7.4, RFC 8446 §4). Todo mensaje viaja en un
*registro*: un byte de tipo, dos de versión y dos de longitud, seguidos de esa
cantidad de bytes. Los registros de tipo ``handshake`` llevan mensajes de
apretón de manos —un byte de tipo y tres de longitud— y **un mensaje puede
partirse en varios registros**, así que se reensambla antes de leerlo. Desde
TLS 1.3 la versión que el servidor elige ya no va en el campo de versión del
``ServerHello`` (que se queda en TLS 1.2 por compatibilidad) sino en la
extensión ``supported_versions``; equivocarse en eso es el error clásico al leer
esto a mano, y de ahí que se resuelva aquí y no en quien consume el resultado.

Tras el ``ServerHello`` de TLS 1.3 todo va cifrado, así que la lectura se corta
ahí: lo que se pregunta a un servidor es qué versión y qué cifrado elige, no lo
que dice después.

Todo se construye y se parsea a mano, sin librería de TLS, por el mismo criterio
que llevó a hacer SNMP, SMB o el ``PRELOGIN`` de SQL Server sin librería de
protocolo.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Tipos de registro TLS (RFC 5246 §6.2.1).
RECORD_TYPE_CHANGE_CIPHER_SPEC = 20
RECORD_TYPE_ALERT = 21
RECORD_TYPE_HANDSHAKE = 22
RECORD_TYPE_APPLICATION_DATA = 23
RECORD_HEADER_SIZE = 5

# Tipos de mensaje de apretón de manos que este módulo distingue.
HANDSHAKE_CLIENT_HELLO = 1
HANDSHAKE_SERVER_HELLO = 2
HANDSHAKE_CERTIFICATE = 11
HANDSHAKE_SERVER_KEY_EXCHANGE = 12
HANDSHAKE_SERVER_HELLO_DONE = 14
HANDSHAKE_HEADER_SIZE = 4

# Códigos de versión del protocolo (los que viajan por el cable).
VERSION_SSL_3_0 = 0x0300
VERSION_TLS_1_0 = 0x0301
VERSION_TLS_1_1 = 0x0302
VERSION_TLS_1_2 = 0x0303
VERSION_TLS_1_3 = 0x0304

#: Cómo llama :class:`~.tls.TlsInfo` a cada versión, para que los dos módulos
#: hablen igual de lo mismo.
VERSION_NAMES: Dict[int, str] = {
    VERSION_SSL_3_0: "SSLv3",
    VERSION_TLS_1_0: "TLSv1",
    VERSION_TLS_1_1: "TLSv1.1",
    VERSION_TLS_1_2: "TLSv1.2",
    VERSION_TLS_1_3: "TLSv1.3",
}

# Extensiones del ``ClientHello`` (registro IANA «TLS ExtensionType Values»).
_EXT_SERVER_NAME = 0x0000
_EXT_SUPPORTED_GROUPS = 0x000A
_EXT_EC_POINT_FORMATS = 0x000B
_EXT_SIGNATURE_ALGORITHMS = 0x000D
_EXT_SUPPORTED_VERSIONS = 0x002B
_EXT_KEY_SHARE = 0x0033
_EXT_RENEGOTIATION_INFO = 0xFF01

# Los grupos que se anuncian: las curvas habituales y los grupos de Diffie-Hellman
# finito, para que un servidor con DHE y un primo pequeño pueda elegirlo.
_GROUP_X25519 = 0x001D
_SUPPORTED_GROUPS = (_GROUP_X25519, 0x0017, 0x0018, 0x0019, 0x0100, 0x0101)

# Algoritmos de firma que se aceptan; incluye los viejos (SHA-1, RSA PKCS#1) para
# que un servidor antiguo no rechace el saludo por no tener con qué firmar.
_SIGNATURE_ALGORITHMS = (
    0x0403, 0x0503, 0x0603, 0x0804, 0x0805, 0x0806, 0x0401, 0x0501, 0x0601,
    0x0201, 0x0203,
)

# Tope de bytes que se leen del servidor en un intercambio: el primer vuelo con
# una cadena de certificados larga cabe de sobra, y una respuesta sin fin no
# puede agotar la memoria.
_MAX_READ_BYTES = 65536

# El «random» fijo con el que un servidor marca un ``HelloRetryRequest`` (RFC
# 8446 §4.1.3): es el SHA-256 de «HelloRetryRequest».
_HELLO_RETRY_REQUEST_RANDOM = bytes.fromhex(
    "cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c")


@dataclass(frozen=True)
class CipherSuite:
    """Un conjunto de cifrado que el saludo puede anunciar.

    Attributes:
        code: El identificador de dos bytes del registro IANA.
        iana_name: El nombre IANA (``TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256``).
        openssl_name: El nombre que le da OpenSSL, y por tanto
            ``ssl.SSLSocket.cipher()`` y :class:`~.tls.TlsInfo`. Vacío cuando
            OpenSSL no lo nombra (los de TLS 1.3 usan el mismo que IANA).
    """
    code: int
    iana_name: str
    openssl_name: str = ""


def _suite(code: int, iana_name: str, openssl_name: str = "") -> CipherSuite:
    """Construye un :class:`CipherSuite` (atajo para la tabla de abajo)."""
    return CipherSuite(code, iana_name, openssl_name or iana_name)


#: Los cifrados que el módulo sabe nombrar, por identificador. No es el registro
#: IANA entero: son las familias que interesa distinguir al auditar un servidor
#: (modernas, con CBC, con 3DES, RC4, de exportación, anónimas y sin cifrado).
CIPHER_SUITES: Dict[int, CipherSuite] = {suite.code: suite for suite in (
    # TLS 1.3
    _suite(0x1301, "TLS_AES_128_GCM_SHA256"),
    _suite(0x1302, "TLS_AES_256_GCM_SHA384"),
    _suite(0x1303, "TLS_CHACHA20_POLY1305_SHA256"),
    # TLS 1.2 con autenticación de cifrado
    _suite(0xC02F, "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256", "ECDHE-RSA-AES128-GCM-SHA256"),
    _suite(0xC030, "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384", "ECDHE-RSA-AES256-GCM-SHA384"),
    _suite(0xC02B, "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256", "ECDHE-ECDSA-AES128-GCM-SHA256"),
    _suite(0xC02C, "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384", "ECDHE-ECDSA-AES256-GCM-SHA384"),
    _suite(0xCCA8, "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256", "ECDHE-RSA-CHACHA20-POLY1305"),
    _suite(0xCCA9, "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
           "ECDHE-ECDSA-CHACHA20-POLY1305"),
    _suite(0x009E, "TLS_DHE_RSA_WITH_AES_128_GCM_SHA256", "DHE-RSA-AES128-GCM-SHA256"),
    _suite(0x009F, "TLS_DHE_RSA_WITH_AES_256_GCM_SHA384", "DHE-RSA-AES256-GCM-SHA384"),
    _suite(0x009C, "TLS_RSA_WITH_AES_128_GCM_SHA256", "AES128-GCM-SHA256"),
    _suite(0x009D, "TLS_RSA_WITH_AES_256_GCM_SHA384", "AES256-GCM-SHA384"),
    # Con CBC (TLS 1.0 en adelante)
    _suite(0xC013, "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA", "ECDHE-RSA-AES128-SHA"),
    _suite(0xC014, "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA", "ECDHE-RSA-AES256-SHA"),
    _suite(0xC009, "TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA", "ECDHE-ECDSA-AES128-SHA"),
    _suite(0x0033, "TLS_DHE_RSA_WITH_AES_128_CBC_SHA", "DHE-RSA-AES128-SHA"),
    _suite(0x0039, "TLS_DHE_RSA_WITH_AES_256_CBC_SHA", "DHE-RSA-AES256-SHA"),
    _suite(0x002F, "TLS_RSA_WITH_AES_128_CBC_SHA", "AES128-SHA"),
    _suite(0x0035, "TLS_RSA_WITH_AES_256_CBC_SHA", "AES256-SHA"),
    _suite(0x003C, "TLS_RSA_WITH_AES_128_CBC_SHA256", "AES128-SHA256"),
    # Débiles: 3DES, RC4, exportación, anónimos y sin cifrado
    _suite(0x000A, "TLS_RSA_WITH_3DES_EDE_CBC_SHA", "DES-CBC3-SHA"),
    _suite(0xC012, "TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA", "ECDHE-RSA-DES-CBC3-SHA"),
    _suite(0x0016, "TLS_DHE_RSA_WITH_3DES_EDE_CBC_SHA", "EDH-RSA-DES-CBC3-SHA"),
    _suite(0x0005, "TLS_RSA_WITH_RC4_128_SHA", "RC4-SHA"),
    _suite(0x0004, "TLS_RSA_WITH_RC4_128_MD5", "RC4-MD5"),
    _suite(0xC011, "TLS_ECDHE_RSA_WITH_RC4_128_SHA", "ECDHE-RSA-RC4-SHA"),
    _suite(0x0003, "TLS_RSA_EXPORT_WITH_RC4_40_MD5", "EXP-RC4-MD5"),
    _suite(0x0008, "TLS_RSA_EXPORT_WITH_DES40_CBC_SHA", "EXP-DES-CBC-SHA"),
    _suite(0x0009, "TLS_RSA_WITH_DES_CBC_SHA", "DES-CBC-SHA"),
    _suite(0x0018, "TLS_DH_anon_WITH_RC4_128_MD5", "ADH-RC4-MD5"),
    _suite(0x0034, "TLS_DH_anon_WITH_AES_128_CBC_SHA", "ADH-AES128-SHA"),
    _suite(0xC018, "TLS_ECDH_anon_WITH_AES_128_CBC_SHA", "AECDH-AES128-SHA"),
    _suite(0x0001, "TLS_RSA_WITH_NULL_MD5", "NULL-MD5"),
    _suite(0x0002, "TLS_RSA_WITH_NULL_SHA", "NULL-SHA"),
)}

#: Los cifrados de TLS 1.3, que sólo se ofrecen cuando se anuncia esa versión.
SUITES_TLS13: Tuple[int, ...] = (0x1301, 0x1302, 0x1303)

#: Todos los de TLS 1.2 y anteriores que el módulo conoce, de los modernos a los
#: débiles: la lista con la que se pregunta «qué eliges» sin sesgar la respuesta
#: hacia lo débil ni hacia lo fuerte.
SUITES_LEGACY: Tuple[int, ...] = tuple(
    code for code in CIPHER_SUITES if code not in SUITES_TLS13)

#: Sólo los débiles (3DES, RC4, exportación, anónimos, NULL): la lista con la que
#: se pregunta «¿aceptas esto?».
SUITES_WEAK: Tuple[int, ...] = (
    0x000A, 0xC012, 0x0016, 0x0005, 0x0004, 0xC011, 0x0003, 0x0008, 0x0009,
    0x0018, 0x0034, 0xC018, 0x0001, 0x0002,
)


@dataclass(frozen=True)
class TlsAlert:
    """La alerta con la que un servidor rechaza un saludo.

    Attributes:
        level: ``1`` (aviso) o ``2`` (fatal).
        description: El código de la alerta; los que interesan son ``40``
            (``handshake_failure``: no hay cifrado en común), ``70``
            (``protocol_version``: no habla la versión ofrecida) y ``86``
            (``inappropriate_fallback``).
    """
    level: int
    description: int


@dataclass(frozen=True)
class ServerHello:
    """Lo que el servidor eligió en su ``ServerHello``.

    Attributes:
        version: El código de la versión **negociada**: la de la extensión
            ``supported_versions`` si el servidor la trae (TLS 1.3), o el campo
            de versión del mensaje en caso contrario.
        cipher_suite: El identificador del cifrado elegido.
        compression_method: El método de compresión (``0`` es ninguno; otro
            valor es un servidor que comprime, la base del ataque CRIME).
        session_id_length: La longitud del identificador de sesión que devolvió.
        extension_types: Los tipos de extensión que el servidor devolvió, en su
            orden.
        is_hello_retry_request: Si en realidad es un ``HelloRetryRequest`` de
            TLS 1.3: el servidor pide otro grupo de intercambio de claves y aún
            no ha elegido nada definitivo.
    """
    version: int
    cipher_suite: int
    compression_method: int = 0
    session_id_length: int = 0
    extension_types: tuple = ()
    is_hello_retry_request: bool = False

    @property
    def version_name(self) -> str:
        """El nombre de la versión negociada, con el formato de :class:`~.tls.TlsInfo` (``"TLSv1.2"``)."""
        return VERSION_NAMES.get(self.version, f"0x{self.version:04x}")

    @property
    def cipher_name(self) -> Optional[str]:
        """El nombre OpenSSL del cifrado elegido, o ``None`` si el módulo no lo conoce."""
        suite = CIPHER_SUITES.get(self.cipher_suite)
        return suite.openssl_name if suite else None


@dataclass(frozen=True)
class ServerFlight:
    """El primer vuelo del servidor tras un ``ClientHello``, leído sin completar el apretón.

    Attributes:
        server_hello: El ``ServerHello``, o ``None`` si el servidor contestó con
            una alerta o con nada utilizable.
        alert: La alerta con la que rechazó el saludo, o ``None``.
        messages: Los demás mensajes de apretón de manos que llegaron en claro
            tras el ``ServerHello``, como pares ``(tipo, cuerpo)`` y en su
            orden: ``Certificate`` (11), ``ServerKeyExchange`` (12),
            ``ServerHelloDone`` (14)… Sin interpretar: quien los consuma sabe
            qué busca. Vacío en TLS 1.3, donde van cifrados.
    """
    server_hello: Optional[ServerHello] = None
    alert: Optional[TlsAlert] = None
    messages: tuple = ()

    def get_message(self, handshake_type: int) -> Optional[bytes]:
        """Devuelve el cuerpo del primer mensaje de un tipo, o ``None`` si no llegó.

        Args:
            handshake_type: El tipo de mensaje de apretón de manos, p. ej.
                :data:`HANDSHAKE_CERTIFICATE`.

        Returns:
            Optional[bytes]: El cuerpo del mensaje, sin la cabecera de cuatro
                bytes; ``None`` si el servidor no envió ninguno de ese tipo.
        """
        for message_type, body in self.messages:
            if message_type == handshake_type:
                return body
        return None


def _extension(extension_type: int, data: bytes) -> bytes:
    """Empaqueta una extensión: tipo, longitud y datos, cada número en dos bytes."""
    return struct.pack("!HH", extension_type, len(data)) + data


def _server_name_extension(server_name: str) -> bytes:
    """Construye la extensión SNI (RFC 6066 §3) para un nombre de host."""
    name = server_name.encode("idna")
    entry = b"\x00" + struct.pack("!H", len(name)) + name
    return _extension(_EXT_SERVER_NAME, struct.pack("!H", len(entry)) + entry)


def build_client_hello(
    versions: Iterable[int] = (VERSION_TLS_1_2,),
    cipher_suites: Optional[Iterable[int]] = None,
    server_name: Optional[str] = None,
) -> bytes:
    """Construye un registro TLS con un ``ClientHello`` que anuncia lo que se pide.

    El saludo ofrece varias versiones y varias familias de cifrado **a la vez**,
    para leer cuál elige el servidor sin repetir la conexión una vez por
    versión. Cómo se anuncian las versiones sigue la regla del protocolo: el
    campo de versión del mensaje lleva la más alta de TLS 1.2 o anteriores, y,
    si se pide TLS 1.3, la extensión ``supported_versions`` lleva la lista
    entera.

    Args:
        versions: Los códigos de versión que se anuncian (``VERSION_TLS_1_0``…
            ``VERSION_TLS_1_3``). Por defecto sólo TLS 1.2. Debe haber al menos
            uno.
        cipher_suites: Los identificadores de cifrado que se ofrecen, por orden
            de preferencia. Por defecto, los de TLS 1.3 si se anuncia esa
            versión seguidos de :data:`SUITES_LEGACY` si se anuncia alguna
            anterior. Si se pide TLS 1.3 y la lista no lleva ninguno de sus
            cifrados, no se añaden: se ofrece exactamente lo pedido.
        server_name: El nombre para la extensión SNI, o ``None`` para no enviar
            ninguna (conexión por IP). Por defecto ``None``.

    Returns:
        bytes: El registro completo, listo para escribir en el socket.

    Raises:
        ValueError: Si ``versions`` está vacío.
    """
    version_list = sorted(set(versions), reverse=True)
    if not version_list:
        raise ValueError("Hace falta anunciar al menos una versión de TLS")
    wants_tls13 = version_list[0] >= VERSION_TLS_1_3
    legacy_versions = [version for version in version_list if version <= VERSION_TLS_1_2]
    # El campo de versión del mensaje nunca lleva 1.3: para eso está la extensión.
    client_version = legacy_versions[0] if legacy_versions else VERSION_TLS_1_2
    record_version = min(client_version, VERSION_TLS_1_0)

    if cipher_suites is None:
        suites: List[int] = list(SUITES_TLS13) if wants_tls13 else []
        if legacy_versions:
            suites += list(SUITES_LEGACY)
    else:
        suites = list(cipher_suites)

    extensions = b""
    if server_name:
        extensions += _server_name_extension(server_name)
    groups = b"".join(struct.pack("!H", group) for group in _SUPPORTED_GROUPS)
    extensions += _extension(_EXT_SUPPORTED_GROUPS, struct.pack("!H", len(groups)) + groups)
    extensions += _extension(_EXT_EC_POINT_FORMATS, b"\x01\x00")
    algorithms = b"".join(struct.pack("!H", algorithm) for algorithm in _SIGNATURE_ALGORITHMS)
    extensions += _extension(
        _EXT_SIGNATURE_ALGORITHMS, struct.pack("!H", len(algorithms)) + algorithms)
    extensions += _extension(_EXT_RENEGOTIATION_INFO, b"\x00")
    if wants_tls13:
        offered = b"".join(struct.pack("!H", version) for version in version_list)
        extensions += _extension(_EXT_SUPPORTED_VERSIONS, bytes([len(offered)]) + offered)
        # Una clave X25519 cualquiera: 32 bytes son siempre un punto válido, y
        # como el apretón no se completa nadie llega a usarla.
        share = struct.pack("!HH", _GROUP_X25519, 32) + os.urandom(32)
        extensions += _extension(_EXT_KEY_SHARE, struct.pack("!H", len(share)) + share)

    suite_bytes = b"".join(struct.pack("!H", suite) for suite in suites)
    body = (
        struct.pack("!H", client_version)
        + os.urandom(32)
        + b"\x00"                                   # sin identificador de sesión
        + struct.pack("!H", len(suite_bytes)) + suite_bytes
        + b"\x01\x00"                               # sólo «sin compresión»
        + struct.pack("!H", len(extensions)) + extensions
    )
    handshake = bytes([HANDSHAKE_CLIENT_HELLO]) + len(body).to_bytes(3, "big") + body
    return bytes([RECORD_TYPE_HANDSHAKE]) + struct.pack("!HH", record_version, len(handshake)) \
        + handshake


def _parse_server_hello(body: bytes) -> Optional[ServerHello]:
    """Lee el cuerpo de un mensaje ``ServerHello``.

    Args:
        body: El cuerpo del mensaje, sin la cabecera de cuatro bytes.

    Returns:
        Optional[ServerHello]: El resultado, o ``None`` si el mensaje está
            truncado o mal formado.
    """
    if len(body) < 2 + 32 + 1:
        return None
    version = struct.unpack("!H", body[0:2])[0]
    random = body[2:34]
    session_id_length = body[34]
    position = 35 + session_id_length
    if len(body) < position + 3:
        return None
    cipher_suite = struct.unpack("!H", body[position:position + 2])[0]
    compression_method = body[position + 2]
    position += 3
    extension_types: List[int] = []
    negotiated_version = version
    if len(body) >= position + 2:
        extensions_end = position + 2 + struct.unpack("!H", body[position:position + 2])[0]
        position += 2
        while position + 4 <= min(extensions_end, len(body)):
            extension_type, length = struct.unpack("!HH", body[position:position + 4])
            data = body[position + 4:position + 4 + length]
            extension_types.append(extension_type)
            if extension_type == _EXT_SUPPORTED_VERSIONS and len(data) == 2:
                negotiated_version = struct.unpack("!H", data)[0]
            position += 4 + length
    return ServerHello(
        version=negotiated_version,
        cipher_suite=cipher_suite,
        compression_method=compression_method,
        session_id_length=session_id_length,
        extension_types=tuple(extension_types),
        is_hello_retry_request=random == _HELLO_RETRY_REQUEST_RANDOM,
    )


def _split_handshake_messages(stream: bytes) -> Tuple[List[Tuple[int, bytes]], bool]:
    """Separa un flujo de bytes de apretón de manos en mensajes completos.

    Args:
        stream: Los cuerpos de los registros ``handshake`` recibidos, ya
            concatenados (un mensaje puede haber llegado partido en varios).

    Returns:
        tuple: ``(mensajes, está_completo)``. Los mensajes son pares
            ``(tipo, cuerpo)`` de los que llegaron enteros; ``está_completo`` es
            ``False`` si el último quedó a medias y faltan bytes por leer.
    """
    messages: List[Tuple[int, bytes]] = []
    position = 0
    while position + HANDSHAKE_HEADER_SIZE <= len(stream):
        length = int.from_bytes(stream[position + 1:position + 4], "big")
        end = position + HANDSHAKE_HEADER_SIZE + length
        if end > len(stream):
            return messages, False
        messages.append((stream[position], stream[position + HANDSHAKE_HEADER_SIZE:end]))
        position = end
    return messages, position == len(stream)


def parse_server_flight(data: bytes) -> ServerFlight:
    """Interpreta lo que un servidor contestó a un ``ClientHello``.

    Reensambla los registros ``handshake`` (un mensaje puede partirse en varios),
    separa sus mensajes, lee el ``ServerHello`` y recoge una alerta si el
    servidor rechazó el saludo. Todo lo que no entiende lo ignora: una respuesta
    que no es TLS da un vuelo vacío, no una excepción.

    Args:
        data: Los bytes recibidos del servidor, empezando por un registro.

    Returns:
        ServerFlight: El vuelo leído; con todos los campos vacíos si los bytes
            no contienen ningún registro TLS reconocible.
    """
    handshake_stream = b""
    alert: Optional[TlsAlert] = None
    position = 0
    while position + RECORD_HEADER_SIZE <= len(data):
        record_type = data[position]
        length = struct.unpack("!H", data[position + 3:position + 5])[0]
        payload = data[position + RECORD_HEADER_SIZE:position + RECORD_HEADER_SIZE + length]
        position += RECORD_HEADER_SIZE + length
        if record_type == RECORD_TYPE_ALERT and len(payload) >= 2 and alert is None:
            alert = TlsAlert(level=payload[0], description=payload[1])
        elif record_type == RECORD_TYPE_HANDSHAKE:
            handshake_stream += payload
        else:
            break                       # ChangeCipherSpec o datos: lo demás va cifrado
    messages, _ = _split_handshake_messages(handshake_stream)
    server_hello: Optional[ServerHello] = None
    others: List[Tuple[int, bytes]] = []
    for message_type, body in messages:
        if message_type == HANDSHAKE_SERVER_HELLO and server_hello is None:
            server_hello = _parse_server_hello(body)
        else:
            others.append((message_type, body))
    return ServerFlight(server_hello=server_hello, alert=alert, messages=tuple(others))


def parse_certificate_message(body: Optional[bytes]) -> List[bytes]:
    """Lee la lista de certificados DER de un mensaje ``Certificate`` (RFC 5246 §7.4.2).

    Sólo entiende la forma de TLS 1.2 y anteriores (una lista plana de
    certificados, cada uno con su longitud de tres bytes delante) — la de TLS
    1.3 añade un contexto y extensiones por certificado, y este lector no se
    usa nunca sobre un vuelo de esa versión (quien lo llama anuncia como mucho
    TLS 1.2 en el ``ClientHello``, así que el servidor no puede contestar en
    la forma de 1.3).

    Args:
        body: El cuerpo del mensaje ``Certificate`` (ver
            :meth:`ServerFlight.get_message`), o ``None`` si el servidor no
            mandó ninguno.

    Returns:
        List[bytes]: Los certificados, en el orden en que el servidor los
            mandó (el de hoja primero). Vacía si ``body`` es ``None`` o no
            tiene la forma esperada.
    """
    if not body or len(body) < 3:
        return []
    total_length = int.from_bytes(body[0:3], "big")
    end = min(3 + total_length, len(body))
    certificates: List[bytes] = []
    offset = 3
    while offset + 3 <= end:
        certificate_length = int.from_bytes(body[offset:offset + 3], "big")
        offset += 3
        certificate = body[offset:offset + certificate_length]
        if len(certificate) < certificate_length:
            break
        certificates.append(certificate)
        offset += certificate_length
    return certificates


def parse_dhe_server_key_exchange(body: Optional[bytes]) -> Optional[int]:
    """Lee el tamaño del módulo Diffie-Hellman de un ``ServerKeyExchange`` DHE (RFC 5246 §7.4.3).

    Sólo lee ``dh_p`` —el primer campo de ``ServerDHParams``, que es lo que
    decide la fuerza del grupo—; ``dh_g`` y la parte pública ``dh_Ys`` que le
    siguen, y la firma que cierra el mensaje, no hacen falta para esto.

    Args:
        body: El cuerpo del mensaje ``ServerKeyExchange``, o ``None`` si el
            servidor no mandó ninguno (no eligió un cifrado DHE).

    Returns:
        Optional[int]: El tamaño de ``dh_p`` en bits, redondeado al byte
            (``len(dh_p) * 8``); ``None`` si ``body`` es ``None`` o viene
            truncado.
    """
    if not body or len(body) < 2:
        return None
    length = struct.unpack_from("!H", body, 0)[0]
    if length == 0 or 2 + length > len(body):
        return None
    return length * 8


def _is_flight_finished(data: bytes) -> bool:
    """Dice si ya se ha leído lo bastante del servidor para dejar de esperar.

    Args:
        data: Los bytes recibidos hasta ahora.

    Returns:
        bool: ``True`` cuando llegó una alerta, el ``ServerHelloDone`` de TLS
            1.2 y anteriores, o un ``ServerHello`` de TLS 1.3 (o un
            ``HelloRetryRequest``), tras el cual todo va cifrado.
    """
    flight = parse_server_flight(data)
    if flight.alert is not None:
        return True
    if flight.server_hello is not None and flight.server_hello.version >= VERSION_TLS_1_3:
        return True
    return flight.get_message(HANDSHAKE_SERVER_HELLO_DONE) is not None


class TlsHelloProbe:  # pylint: disable=too-few-public-methods
    """Pregunta a un servidor qué elige ante un saludo, sin completar el apretón.

    Abre una conexión TCP, escribe un ``ClientHello`` construido a mano, lee el
    primer vuelo de la respuesta y cierra. No hay verificación de certificado
    porque no hay apretón que verificar: lo que se lee es la elección del
    servidor, no su identidad.

    Args:
        timeout: El plazo de conexión y de cada lectura, en segundos. Por
            defecto ``5.0``.
        connect: Un ``(dirección, plazo) -> socket`` inyectable, con el mismo
            patrón que :class:`~.tls.TlsProbe`. Por defecto
            ``socket.create_connection``.
    """

    def __init__(self, timeout: float = 5.0, connect: Optional[Callable] = None) -> None:
        self._timeout = timeout
        self._connect = connect or socket.create_connection

    def query(
        self,
        host: str,
        port: int,
        versions: Iterable[int] = (VERSION_TLS_1_2,),
        cipher_suites: Optional[Iterable[int]] = None,
        server_name: Optional[str] = None,
    ) -> Optional[ServerFlight]:
        """Envía un ``ClientHello`` y devuelve lo que el servidor contesta.

        Args:
            host: El host destino.
            port: El puerto destino.
            versions: Las versiones que se anuncian (ver
                :func:`build_client_hello`). Por defecto sólo TLS 1.2.
            cipher_suites: Los cifrados que se ofrecen (ver
                :func:`build_client_hello`). Por defecto, los que corresponden a
                las versiones anunciadas.
            server_name: El nombre para el SNI, o ``None`` para no enviar
                ninguno. Por defecto ``None``.

        Returns:
            Optional[ServerFlight]: El primer vuelo del servidor, con
                ``server_hello`` o ``alert`` rellenos si contestó algo
                entendible; ``None`` si no se pudo conectar o el servidor se
                calló sin devolver un solo byte.
        """
        hello = build_client_hello(versions, cipher_suites, server_name)
        try:
            sock = self._connect((host, port), self._timeout)
        except OSError as err:
            logger.debug("TLS hello connect failed for %s:%s: %s", host, port, err)
            return None
        received = b""
        try:
            sock.settimeout(self._timeout)
            sock.sendall(hello)
            deadline = time.monotonic() + self._timeout
            while len(received) < _MAX_READ_BYTES and time.monotonic() < deadline:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                received += chunk
                if _is_flight_finished(received):
                    break
        except OSError as err:
            logger.debug("TLS hello exchange failed for %s:%s: %s", host, port, err)
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return parse_server_flight(received) if received else None
