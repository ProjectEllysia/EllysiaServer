"""Cliente mínimo de las llamadas remotas de administración de Windows (DCE/RPC).

Lybra ya identifica un equipo Windows por SMB (:mod:`smb`) y por LDAP
(:mod:`ldap`), pero ninguno de los dos protocolos deja ver qué carpetas
comparte un equipo sin autenticarse, ni si sus servicios de impresión o de
llamadas remotas de procedimiento (RPC) están expuestos: eso vive en un
protocolo distinto —DCE/RPC (MS-RPCE), transportado sobre una tubería con
nombre de SMB (``\\\\PIPE\\\\srvsvc``, ``\\\\PIPE\\\\spoolss``) o directamente sobre
TCP en el caso del localizador de puntos finales (*endpoint mapper*, puerto
135)— que el motor no hablaba en absoluto.

Este módulo construye ese cliente, con el mismo criterio que ya llevó a
construir SMB, LDAP o el ``PRELOGIN`` de SQL Server a mano: parseo de bytes por
desplazamiento, sin traer una librería de RPC completa para dos llamadas.
No es un dissector —no identifica un producto ni una versión— sino la base de
la que dependen L110 (carpetas compartidas visibles sin usuario) y L111
(servicios de impresión y de RPC expuestos en un controlador de dominio).

**Tres capacidades, sin autenticar cuando el equipo lo permite**:

1. :func:`fetch_shares` — lista los nombres de las carpetas compartidas
   (``NetrShareEnum``, interfaz ``srvsvc``) con una sesión SMB anónima.
2. :func:`probe_named_pipe_rpc` — comprueba si una interfaz RPC servida por
   una tubería con nombre (el spooler de impresión, ``spoolss``) acepta un
   saludo (*bind*) sin credenciales.
3. :func:`probe_endpoint_mapper` — comprueba si el localizador de puntos
   finales, que escucha directamente en el puerto 135 sin pasar por SMB,
   acepta un saludo sin credenciales.

**La sesión SMB es anónima, no autenticada de verdad** (MS-NLMP §3.2.5.1.2):
tras el ``NEGOTIATE`` de SMB2 (reutilizado de :mod:`smb`), el
``SESSION_SETUP`` completa un NTLM de tipo 3 con usuario, dominio y respuestas
todos vacíos — el "null session" clásico. Un equipo que no lo permita (la
configuración por defecto desde Windows Vista) rechaza el segundo
``SESSION_SETUP`` y las funciones de este módulo devuelven, según el caso,
``[]`` o ``None``: nunca se manda una credencial real.

**Una sola llamada por conexión.** El transporte no reutiliza la sesión entre
llamadas —abre, hace lo que necesita y cierra el socket—, que es lo que pide
un cliente mínimo: nada que mantener vivo, nada que limpiar si algo falla a
medio camino.

**Formato** (MS-RPCE §2.2.6, MS-SRVS §2.2 y §3.1.4.8, MS-SMB2 §2.2.31/§2.2.32
para el transporte). Un PDU de DCE/RPC son 16 bytes de cabecera común (tipo de
PDU, banderas de fragmento, representación de datos, longitud) seguidos del
cuerpo propio de ese tipo. Un ``bind`` propone una interfaz (UUID + versión) y
una sintaxis de transferencia (NDR); el servidor contesta con un ``bind_ack``
que la acepta o un ``bind_nak`` que la rechaza — esa aceptación, por sí sola,
ya es la señal de "expuesto sin credenciales" que L111 necesita, antes de
llamar a ningún método. Los parámetros de una llamada van codificados en NDR
(*Network Data Representation*): enteros alineados a su tamaño, cadenas como
un contador seguido de caracteres UTF-16LE, y un puntero como un
identificador de cuatro bytes cuyo cuerpo, si no es ``0`` (nulo), llega
**después** de toda la estructura que lo contiene (MS-RPCE §14.3.12,
"puntero diferido").

No hay forma de comprobar este módulo contra un controlador de dominio real
desde este entorno: la implementación sigue la especificación byte a byte y
se prueba con fixtures escritas a mano (como el resto de ``fingerprinting/``
antes de tener un banco de concordancia), no contra un Windows o un Samba en
marcha. Verificarlo contra uno real queda pendiente, igual que quedó pendiente
para SMB hasta que hubo un ``dperson/samba`` a mano.
"""

from __future__ import annotations

import logging
import socket
import struct
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .smb import build_negotiate_request, build_ntlm_negotiate

logger = logging.getLogger(__name__)

# =========================================================================
# UUIDS DE INTERFAZ Y CONSTANTES DE DCE/RPC
# =========================================================================

# srvsvc (MS-SRVS): el servicio de administración de recursos compartidos.
SRVSVC_INTERFACE_UUID = "4b324fc8-1670-01d3-1278-5a47bf6ee188"
SRVSVC_INTERFACE_VERSION = (3, 0)
SRVSVC_PIPE = "srvsvc"

# spoolss (MS-RPRN): el spooler de impresión — el protocolo tras PrintNightmare.
SPOOLSS_INTERFACE_UUID = "12345678-1234-abcd-ef00-0123456789ab"
SPOOLSS_INTERFACE_VERSION = (1, 0)
SPOOLSS_PIPE = "spoolss"

# El localizador de puntos finales (MS-RPCE §2.2.5.2): escucha directamente en
# el puerto 135, sin tubería SMB de por medio.
EPMAP_INTERFACE_UUID = "e1af8308-5d1f-11c9-91a4-08002b14a0fa"
EPMAP_INTERFACE_VERSION = (3, 0)
EPMAP_PORT = 135

# La sintaxis de transferencia NDR (versión 2.0), la única que este cliente
# ofrece: es la que hablan todas las interfaces de administración de Windows.
_NDR_TRANSFER_SYNTAX_UUID = "8a885d04-1ceb-11c9-9fe8-08002b104860"
_NDR_TRANSFER_SYNTAX_VERSION = (2, 0)

# Tipos de PDU de DCE/RPC que este cliente construye o reconoce (MS-RPCE §2.2.1.1.1).
PDU_TYPE_REQUEST = 0
PDU_TYPE_RESPONSE = 2
PDU_TYPE_FAULT = 3
PDU_TYPE_BIND = 11
PDU_TYPE_BIND_ACK = 12
PDU_TYPE_BIND_NAK = 13

# PFC_FIRST_FRAG | PFC_LAST_FRAG: un único fragmento, primero y último a la
# vez — este cliente nunca fragmenta ni reensambla.
_PFC_FIRST_AND_LAST_FRAG = 0x03
# Representación de datos: little-endian, ASCII, IEEE de coma flotante —
# la que anuncia cualquier cliente Windows.
_DATA_REPRESENTATION = b"\x10\x00\x00\x00"
_RPC_HEADER_LEN = 16
_RPC_CALL_ID = 1

# El resultado de aceptación de un elemento de contexto en un bind_ack
# (MS-RPCE §2.2.1.2.4): ``0`` es la única aceptación; el resto son variantes
# de rechazo o de negociación que este cliente trata todas como "no aceptado".
_BIND_RESULT_ACCEPTANCE = 0

# NetrShareEnum (MS-SRVS §3.1.4.8), en la interfaz srvsvc.
_OPNUM_NETR_SHARE_ENUM = 15
# Nivel de información: sólo nombre, tipo y comentario — el mínimo que
# identifica una carpeta compartida sin pedir nada que exija más privilegio.
_SHARE_INFO_LEVEL = 1
# "Sin límite": el idiomatismo con el que se pide la lista entera de una vez.
_PREFERRED_MAX_LENGTH = 0xFFFFFFFF

# NET_API_STATUS (MS-SRVS §2.2.1 remite a MS-ERREF): éxito, y "hay más datos de
# los que cupieron" — que sigue trayendo la lista que sí llegó.
_NERR_SUCCESS = 0
_ERROR_MORE_DATA = 234


@dataclass(frozen=True)
class ShareInfo:
    """Una carpeta compartida, tal como la describe ``NetrShareEnum`` en su nivel 1.

    Attributes:
        name: El nombre de la carpeta compartida (``"Publico"``).
        share_type: El tipo, tal cual lo declara el servidor (MS-SRVS
            §2.2.2.4): ``0`` disco, ``1`` cola de impresión, ``3`` IPC, y con
            el bit alto puesto (``0x80000000``) para las compartidas
            "ocultas" (``ADMIN$``, ``C$``…), que terminan en ``$``.
        remark: El comentario que el servidor le puso, o cadena vacía.
    """
    name: str
    share_type: int
    remark: str

    @property
    def is_hidden(self) -> bool:
        """Si es una compartida administrativa/oculta (nombre acabado en ``$``)."""
        return bool(self.share_type & 0x80000000) or self.name.endswith("$")


# =========================================================================
# NDR — lectura y escritura de lo justo del formato (enteros, punteros, cadenas)
# =========================================================================

def _ndr_pad(length: int, alignment: int) -> bytes:
    """Bytes de relleno para alinear ``length`` al siguiente múltiplo de ``alignment``."""
    remainder = length % alignment
    return b"\x00" * (alignment - remainder) if remainder else b""


def _ndr_string(text: str) -> bytes:
    """Codifica una cadena como una NDR *conformant varying string* de ``wchar_t``.

    Formato (MS-RPCE §14.3.4.2): ``max_count``, ``offset`` (siempre ``0`` aquí:
    no se manda una subcadena) y ``actual_count`` — los tres como ``DWORD``, y
    los tres iguales al número de unidades UTF-16 **incluido** el terminador
    nulo—, seguidos de esas unidades y del relleno hasta el siguiente múltiplo
    de cuatro bytes.

    Args:
        text: El texto a codificar.

    Returns:
        bytes: La cadena ya lista para ir en el cuerpo de una petición.
    """
    encoded = text.encode("utf-16-le") + b"\x00\x00"
    count = len(encoded) // 2
    body = struct.pack("<III", count, 0, count) + encoded
    return body + _ndr_pad(len(body), 4)


def _read_ndr_string(buffer: bytes, offset: int) -> Tuple[str, int]:
    """Lee una cadena NDR (ver :func:`_ndr_string`) desde ``offset``.

    Args:
        buffer: El cuerpo NDR completo.
        offset: Dónde empieza la cadena (ya alineado a cuatro bytes).

    Returns:
        tuple: ``(texto, siguiente_desplazamiento)``, con el terminador nulo
            quitado. El desplazamiento que se devuelve ya incluye el relleno.

    Raises:
        ValueError: Si no quedan bytes suficientes para leer la cabecera o el
            contenido declarado — una respuesta truncada o mal formada.
    """
    if offset + 12 > len(buffer):
        raise ValueError("Cadena NDR truncada: falta la cabecera")
    max_count, string_offset, actual_count = struct.unpack_from("<III", buffer, offset)
    start = offset + 12 + string_offset * 2
    end = start + actual_count * 2
    if string_offset != 0 or actual_count > max_count or end > len(buffer):
        raise ValueError("Cadena NDR truncada o con una forma que este cliente no espera")
    text = buffer[start:end].decode("utf-16-le", errors="replace").rstrip("\x00")
    body_len = 12 + actual_count * 2
    next_offset = offset + body_len + len(_ndr_pad(body_len, 4))
    return text, next_offset


def _read_ndr_pointer(buffer: bytes, offset: int) -> Tuple[int, int]:
    """Lee un identificador de puntero NDR (cuatro bytes) desde ``offset``.

    Returns:
        tuple: ``(referente, siguiente_desplazamiento)``. El referente es
            ``0`` para un puntero nulo; cualquier otro valor sólo dice "hay
            cuerpo diferido", nunca una dirección real.
    """
    if offset + 4 > len(buffer):
        raise ValueError("Puntero NDR truncado")
    return struct.unpack_from("<I", buffer, offset)[0], offset + 4


def _uuid_wire_bytes(text: str) -> bytes:
    """Los 16 bytes de un UUID en el orden que DCE/RPC pone en el cable.

    Args:
        text: El UUID en su forma con guiones (``"4b324fc8-1670-..."``).

    Returns:
        bytes: Los tres primeros campos en little-endian y los dos últimos tal
            cual (``uuid.UUID.bytes_le``, que es exactamente esta forma).
    """
    return uuid.UUID(text).bytes_le


# =========================================================================
# CABECERA COMÚN DE DCE/RPC Y LOS PDU DE BIND
# =========================================================================

def _rpc_header(pdu_type: int, body_length: int) -> bytes:
    """Construye la cabecera común de 16 bytes de un PDU de DCE/RPC (MS-RPCE §2.2.6.2)."""
    frag_length = _RPC_HEADER_LEN + body_length
    return struct.pack(
        "<BBBB", 5, 0, pdu_type, _PFC_FIRST_AND_LAST_FRAG,
    ) + _DATA_REPRESENTATION + struct.pack("<HHI", frag_length, 0, _RPC_CALL_ID)


def build_bind_request(interface_uuid: str, interface_version: Tuple[int, int]) -> bytes:
    """Construye un PDU ``bind`` que propone una interfaz sobre NDR (MS-RPCE §2.2.6.3).

    Propone exactamente un elemento de contexto (``p_cont_id=0``), con la
    interfaz pedida como sintaxis abstracta y NDR como única sintaxis de
    transferencia — lo justo para que el servidor pueda aceptar o rechazar.

    Args:
        interface_uuid: El UUID de la interfaz, con guiones.
        interface_version: Su versión, como ``(mayor, menor)``.

    Returns:
        bytes: El PDU completo, cabecera incluida.
    """
    major, minor = interface_version
    context_element = (
        struct.pack("<HBB", 0, 1, 0)                        # p_cont_id, n_transfer_syn, reserved
        + _uuid_wire_bytes(interface_uuid) + struct.pack("<HH", major, minor)
        + _uuid_wire_bytes(_NDR_TRANSFER_SYNTAX_UUID)
        + struct.pack("<HH", *_NDR_TRANSFER_SYNTAX_VERSION)
    )
    body = struct.pack("<HHIBBH", 4280, 4280, 0, 1, 0, 0) + context_element
    return _rpc_header(PDU_TYPE_BIND, len(body)) + body


@dataclass(frozen=True)
class BindAck:
    """Lo que un servidor contestó a un ``bind`` (MS-RPCE §2.2.1.2.4 y §2.2.6.4).

    Attributes:
        pdu_type: :data:`PDU_TYPE_BIND_ACK` o :data:`PDU_TYPE_BIND_NAK`.
        accepted: Si el primer (y único) elemento de contexto se aceptó. Sólo
            tiene sentido cuando ``pdu_type`` es ``bind_ack``: un ``bind_nak``
            es un rechazo explícito a nivel de asociación, antes de mirar
            elementos de contexto.
    """
    pdu_type: int
    accepted: bool


def parse_bind_ack(data: bytes) -> Optional[BindAck]:
    """Interpreta la respuesta a un ``bind``.

    Args:
        data: El PDU completo recibido, cabecera incluida.

    Returns:
        Optional[BindAck]: ``None`` si los bytes no son un PDU de DCE/RPC
            reconocible o no caben; en cualquier otro caso, incluido un
            ``bind_nak``, un resultado con ``pdu_type`` y ``accepted``.
    """
    if len(data) < _RPC_HEADER_LEN or data[0] != 5:
        return None
    pdu_type = data[2]
    if pdu_type == PDU_TYPE_BIND_NAK:
        return BindAck(pdu_type=pdu_type, accepted=False)
    if pdu_type != PDU_TYPE_BIND_ACK:
        return None
    try:
        # sec_addr: una cadena de una sola línea (longitud de dos bytes +
        # bytes), con relleno hasta el siguiente múltiplo de cuatro antes de
        # num_results.
        sec_addr_length = struct.unpack_from("<H", data, _RPC_HEADER_LEN + 8)[0]
        offset = _RPC_HEADER_LEN + 10 + sec_addr_length
        offset += len(_ndr_pad(offset, 4))
        num_results = data[offset]
        if num_results < 1:
            return BindAck(pdu_type=pdu_type, accepted=False)
        result = struct.unpack_from("<H", data, offset + 4)[0]
    except (struct.error, IndexError):
        return None
    return BindAck(pdu_type=pdu_type, accepted=result == _BIND_RESULT_ACCEPTANCE)


def build_request_pdu(opnum: int, stub: bytes) -> bytes:
    """Construye un PDU ``request`` con una llamada ya codificada en NDR (MS-RPCE §2.2.6.5)."""
    body = struct.pack("<IHH", len(stub), 0, opnum) + stub
    return _rpc_header(PDU_TYPE_REQUEST, len(body)) + body


def parse_response_pdu(data: bytes) -> Optional[bytes]:
    """Extrae el cuerpo (*stub data*) de un PDU ``response``.

    Args:
        data: El PDU completo recibido.

    Returns:
        Optional[bytes]: El cuerpo NDR de la respuesta. ``None`` si los bytes
            no son un PDU reconocible, si es un ``fault`` (MS-RPCE §2.2.6.6:
            la llamada falló a nivel de RPC — permiso denegado, opnum
            inválido…) o si viene truncado.
    """
    if len(data) < _RPC_HEADER_LEN or data[0] != 5:
        return None
    pdu_type = data[2]
    if pdu_type == PDU_TYPE_FAULT:
        return None
    if pdu_type != PDU_TYPE_RESPONSE:
        return None
    stub_start = _RPC_HEADER_LEN + 8    # alloc_hint(4)+p_cont_id(2)+cancel_count(1)+reserved(1)
    if stub_start > len(data):
        return None
    return data[stub_start:]


# =========================================================================
# srvsvc — NetrShareEnum
# =========================================================================

def build_netr_share_enum_request() -> bytes:
    """Codifica en NDR una llamada ``NetrShareEnum`` de nivel 1 (MS-SRVS §3.1.4.8).

    Pide el nombre del servidor como puntero nulo (el servidor identifica el
    objetivo por la propia conexión, no hace falta nombrarlo) y no da un
    identificador de reanudación (puntero nulo también): una sola llamada
    basta para el tamaño de lista que interesa aquí.

    Returns:
        bytes: El cuerpo NDR de la llamada, listo para
            :func:`build_request_pdu`.
    """
    server_name = struct.pack("<I", 0)                          # ServerName: puntero nulo
    info_struct = (
        struct.pack("<I", _SHARE_INFO_LEVEL)                    # InfoStruct.Level
        + struct.pack("<I", _SHARE_INFO_LEVEL)                  # union switch (repite el nivel)
        + struct.pack("<I", 0x00020000)                         # puntero al contenedor (no nulo)
        + struct.pack("<I", 0)                                  # contenedor.EntriesRead = 0
        + struct.pack("<I", 0)                                  # contenedor.Buffer: puntero nulo
    )
    preferred_max_length = struct.pack("<I", _PREFERRED_MAX_LENGTH)
    resume_handle = struct.pack("<I", 0)                        # ResumeHandle: puntero nulo
    return server_name + info_struct + preferred_max_length + resume_handle


def parse_netr_share_enum_response(  # pylint: disable=too-many-locals
        stub: bytes) -> List[ShareInfo]:
    """Interpreta la respuesta de un ``NetrShareEnum`` de nivel 1.

    Lee el array de ``SHARE_INFO_1`` —cada entrada son tres campos fijos
    (puntero al nombre, tipo, puntero al comentario) seguidos, tras el array
    entero, de los cuerpos de esos punteros en el orden en que aparecieron
    (MS-RPCE §14.3.12: los punteros de un array se difieren en bloque).

    Args:
        stub: El cuerpo NDR de la respuesta (ver :func:`parse_response_pdu`).

    Returns:
        List[ShareInfo]: Las carpetas compartidas listadas. Vacía si el nivel
            devuelto no es el pedido, si el servidor denegó la llamada
            (``NET_API_STATUS`` distinto de éxito y de "más datos"), o si la
            respuesta viene truncada o con una forma inesperada — un fallo al
            leer nunca se distingue de "no hay ninguna", porque a quien
            consume esta lista sólo le importa el caso positivo.
    """
    try:
        level = struct.unpack_from("<I", stub, 0)[0]
        if level != _SHARE_INFO_LEVEL:
            return []
        container_referent, offset = _read_ndr_pointer(stub, 8)
        if container_referent == 0:
            return []
        entries_read = struct.unpack_from("<I", stub, offset)[0]
        offset += 4
        buffer_referent, offset = _read_ndr_pointer(stub, offset)
        if buffer_referent == 0 or entries_read == 0:
            entries: List[ShareInfo] = []
        else:
            max_count = struct.unpack_from("<I", stub, offset)[0]
            offset += 4
            if max_count < entries_read:
                return []
            raw_entries = []
            for _ in range(entries_read):
                name_ref, type_value, remark_ref = struct.unpack_from("<III", stub, offset)
                raw_entries.append((name_ref, type_value, remark_ref))
                offset += 12
            entries = []
            for name_ref, type_value, remark_ref in raw_entries:
                name = ""
                remark = ""
                if name_ref:
                    name, offset = _read_ndr_string(stub, offset)
                if remark_ref:
                    remark, offset = _read_ndr_string(stub, offset)
                entries.append(ShareInfo(name=name, share_type=type_value, remark=remark))
        # El NET_API_STATUS final va tras TotalEntries (4) y ResumeHandle
        # ([out], puntero + valor si no es nulo).
        offset += 4                                             # TotalEntries
        resume_referent, offset = _read_ndr_pointer(stub, offset)
        if resume_referent:
            offset += 4
        status = struct.unpack_from("<I", stub, offset)[0]
        if status not in (_NERR_SUCCESS, _ERROR_MORE_DATA):
            return []
        return entries
    except (struct.error, ValueError, IndexError):
        return []


# =========================================================================
# TRANSPORTE: sesión SMB anónima sobre una tubería con nombre
# =========================================================================

# Códigos de estado de SMB2 (MS-SMB2 §2.2.2) que este módulo distingue.
_STATUS_SUCCESS = 0x00000000
_STATUS_MORE_PROCESSING_REQUIRED = 0xC0000016
_STATUS_BUFFER_OVERFLOW = 0x80000005

_FSCTL_PIPE_TRANSCEIVE = 0x0011C017
_SMB2_0_IOCTL_IS_FSCTL = 0x00000001

_SMB2_COMMAND_SESSION_SETUP = 0x0001
_SMB2_COMMAND_TREE_CONNECT = 0x0003
_SMB2_COMMAND_CREATE = 0x0005
_SMB2_COMMAND_IOCTL = 0x000B

_FILE_READ_DATA = 0x00000001
_FILE_WRITE_DATA = 0x00000002
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_OPEN = 0x00000001

# El máximo de bytes que se pide de vuelta en cada llamada RPC: de sobra para
# una lista de carpetas compartidas o un bind_ack, sin arriesgarse a una
# respuesta de un tamaño que este cliente de una sola llamada no va a leer
# en más de una vez.
_MAX_TRANSCEIVE_RESPONSE = 0x00010000


def _smb2_header(command: int, session_id: int = 0, tree_id: int = 0,
                 message_id: int = 0) -> bytes:
    """Cabecera SMB2 de 64 bytes, con la sesión y el árbol ya establecidos.

    A diferencia de :func:`~.smb._smb2_header` (que fija ``SessionId`` y
    ``TreeId`` a cero porque NEGOTIATE es siempre el primer mensaje sin
    sesión), este transporte encadena varios mensajes sobre la misma sesión y
    el mismo árbol, así que los lleva como parámetro.
    """
    return b"".join([
        b"\xfeSMB", struct.pack("<H", 64), struct.pack("<H", 0), struct.pack("<I", 0),
        struct.pack("<H", command), struct.pack("<H", 1), struct.pack("<I", 0),
        struct.pack("<I", 0), struct.pack("<Q", message_id), struct.pack("<I", 0),
        struct.pack("<I", tree_id), struct.pack("<Q", session_id), b"\x00" * 16,
    ])


def build_ntlm_authenticate_anonymous() -> bytes:
    """Construye el mensaje NTLM de tipo 3 de una sesión anónima (MS-NLMP §2.2.1.3, §3.2.5.1.2).

    Usuario, dominio y las dos respuestas de reto van todos vacíos: es el
    "null session" clásico, no una autenticación con una identidad real. Sin
    versión ni MIC —campos opcionales que este cliente no necesita—, así que
    los seis descriptores de campo (longitud, longitud máxima, desplazamiento)
    apuntan todos al final de la cabecera fija de 64 bytes, donde no hay nada.

    Returns:
        bytes: El mensaje completo.
    """
    empty_field = struct.pack("<HHI", 0, 0, 64)
    return b"".join([
        b"NTLMSSP\x00", struct.pack("<I", 3),
        empty_field, empty_field, empty_field, empty_field, empty_field, empty_field,
        struct.pack("<I", 0x00000800 | 0x00000001 | 0x00080000),  # ANONYMOUS|UNICODE|EXT_SECURITY
    ])


def _send_and_receive(sock, message: bytes) -> Optional[bytes]:
    """Manda un mensaje SMB2 con su cabecera NetBIOS y lee la respuesta completa.

    Función de módulo y no método: no toca más estado que el socket que recibe
    por parámetro (CONVENCIONES.md §5.1).
    """
    sock.sendall(bytes((0x00,)) + len(message).to_bytes(3, "big") + message)
    header = sock.recv(4)
    if len(header) < 4:
        return None
    length = int.from_bytes(header[1:4], "big")
    body = b""
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            return None
        body += chunk
    return body


def _session_setup(sock, message_id: int) -> Optional[Tuple[int, int]]:
    """SESSION_SETUP en dos vueltas: NTLM de tipo 1, y de tipo 3 anónimo.

    El cuerpo fijo de la petición (MS-SMB2 §2.2.5) mide 24 bytes, así que el
    token de seguridad —el mensaje NTLM— empieza en ``64 + 24 = 88`` contando
    desde el principio del mensaje, cabecera SMB2 incluida.

    Args:
        sock: El socket ya conectado, tras el ``NEGOTIATE``.
        message_id: El identificador de mensaje con el que empezar.

    Returns:
        Optional[Tuple[int, int]]: ``(id_de_sesión, siguiente_message_id)``, o
            ``None`` si el servidor no completa la sesión anónima (equipo con
            las sesiones anónimas deshabilitadas, la configuración por
            defecto desde Windows Vista).
    """
    def request(token: bytes) -> bytes:
        fixed = b"".join([
            struct.pack("<H", 25),           # StructureSize
            struct.pack("<B", 1),            # Flags
            struct.pack("<B", 1),            # SecurityMode: NEGOTIATE_SIGNING_ENABLED
            struct.pack("<I", 0),            # Capabilities
            struct.pack("<I", 0),            # Channel
            struct.pack("<H", 88),           # SecurityBufferOffset
            struct.pack("<H", len(token)),   # SecurityBufferLength
            struct.pack("<Q", 0),            # PreviousSessionId
        ])
        return fixed + token

    reply = _send_and_receive(
        sock, _smb2_header(_SMB2_COMMAND_SESSION_SETUP, message_id=message_id)
        + request(build_ntlm_negotiate()))
    if reply is None or len(reply) < 48:
        return None
    if struct.unpack_from("<I", reply, 8)[0] != _STATUS_MORE_PROCESSING_REQUIRED:
        return None
    session_id = struct.unpack_from("<Q", reply, 40)[0]

    reply = _send_and_receive(
        sock, _smb2_header(_SMB2_COMMAND_SESSION_SETUP, session_id=session_id,
                          message_id=message_id + 1)
        + request(build_ntlm_authenticate_anonymous()))
    if reply is None or len(reply) < 12:
        return None
    if struct.unpack_from("<I", reply, 8)[0] != _STATUS_SUCCESS:
        return None
    return session_id, message_id + 2


def _tree_connect(sock, session_id: int, message_id: int) -> Optional[Tuple[int, int]]:
    """TREE_CONNECT a ``\\\\<lo que sea>\\\\IPC$``.

    El nombre de host en la ruta UNC es irrelevante para el servidor
    —identifica el árbol por el nombre del recurso—, así que se manda un
    marcador fijo en vez de resolver el nombre real de la conexión.

    Returns:
        Optional[Tuple[int, int]]: ``(id_de_árbol, siguiente_message_id)``, o
            ``None`` si la conexión falla.
    """
    path = "\\\\host\\IPC$".encode("utf-16-le")
    path_offset = 64 + 8                                     # cabecera + cuerpo fijo (8 bytes)
    body = struct.pack("<HHHH", 9, 0, path_offset, len(path)) + path
    reply = _send_and_receive(
        sock, _smb2_header(_SMB2_COMMAND_TREE_CONNECT, session_id=session_id,
                          message_id=message_id) + body)
    if reply is None or len(reply) < 40:
        return None
    if struct.unpack_from("<I", reply, 8)[0] != _STATUS_SUCCESS:
        return None
    # El TreeId asignado viaja en la propia cabecera de la respuesta
    # (MS-SMB2 §3.3.5.7), no en su cuerpo.
    tree_id = struct.unpack_from("<I", reply, 36)[0]
    return tree_id, message_id + 1


def _create_pipe(sock, session_id: int, tree_id: int, message_id: int,
                 pipe_name: str) -> Optional[Tuple[bytes, int]]:
    """CREATE (abrir) la tubería con nombre por su nombre, sin credenciales.

    Returns:
        Optional[Tuple[bytes, int]]: ``(id_de_fichero, siguiente_message_id)``,
            o ``None`` si la apertura falla (la tubería no existe, o el
            equipo no la deja abrir sin autenticar de verdad).
    """
    name = pipe_name.encode("utf-16-le")
    name_offset = 64 + 56                                    # cabecera + cuerpo fijo (56 bytes)
    body = b"".join([
        struct.pack("<H", 57),                                # StructureSize
        struct.pack("<B", 0),                                 # SecurityFlags
        struct.pack("<B", 0),                                 # RequestedOplockLevel
        struct.pack("<I", 2),                                 # ImpersonationLevel: Impersonation
        struct.pack("<Q", 0),                                 # SmbCreateFlags
        struct.pack("<Q", 0),                                 # Reserved
        struct.pack("<I", _FILE_READ_DATA | _FILE_WRITE_DATA),  # DesiredAccess
        struct.pack("<I", 0),                                 # FileAttributes
        struct.pack("<I", _FILE_SHARE_READ | _FILE_SHARE_WRITE),  # ShareAccess
        struct.pack("<I", _FILE_OPEN),                        # CreateDisposition
        struct.pack("<I", 0),                                 # CreateOptions
        struct.pack("<H", name_offset),                       # NameOffset
        struct.pack("<H", len(name)),                         # NameLength
        struct.pack("<I", 0),                                 # CreateContextsOffset
        struct.pack("<I", 0),                                 # CreateContextsLength
    ]) + name
    reply = _send_and_receive(
        sock, _smb2_header(_SMB2_COMMAND_CREATE, session_id=session_id,
                          tree_id=tree_id, message_id=message_id) + body)
    if reply is None or len(reply) < 12:
        return None
    if struct.unpack_from("<I", reply, 8)[0] != _STATUS_SUCCESS:
        return None
    if len(reply) < 64 + 80:
        return None
    # El FileId son 16 bytes al desplazamiento 64 **del cuerpo** (MS-SMB2
    # §2.2.14); ``reply`` lleva delante los 64 de la cabecera SMB2.
    return reply[64 + 64:64 + 80], message_id + 1


def _pipe_transceive(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        sock, session_id: int, tree_id: int, file_id: bytes,
        message_id: int, data: bytes) -> Optional[bytes]:
    """Manda ``data`` a la tubería y devuelve lo que conteste, en una sola vuelta.

    Usa ``FSCTL_PIPE_TRANSCEIVE`` (MS-SMB2 §2.2.31), pensado justo para esto:
    una tubería con nombre en modo mensaje no se puede escribir y leer por
    separado sin arriesgarse a partir un mensaje por la mitad.

    Args:
        sock: El socket ya conectado.
        session_id: El identificador de sesión.
        tree_id: El identificador del árbol (``IPC$``).
        file_id: El identificador de la tubería ya abierta (16 bytes).
        message_id: El identificador de este mensaje.
        data: El PDU de DCE/RPC a mandar.

    Returns:
        Optional[bytes]: La respuesta, o ``None`` si la operación falló con un
            estado que no sea "éxito" ni "hay más de lo que cupo".
    """
    input_offset = 64 + 56                                    # cabecera + cuerpo fijo (56 bytes)
    body = b"".join([
        struct.pack("<H", 57),                                # StructureSize
        struct.pack("<H", 0),                                 # Reserved
        struct.pack("<I", _FSCTL_PIPE_TRANSCEIVE),            # CtlCode
        file_id,                                              # FileId (16 bytes)
        struct.pack("<I", input_offset),                      # InputOffset
        struct.pack("<I", len(data)),                         # InputCount
        struct.pack("<I", 0),                                 # MaxInputResponse
        struct.pack("<I", input_offset),                      # OutputOffset
        struct.pack("<I", 0),                                 # OutputCount
        struct.pack("<I", _MAX_TRANSCEIVE_RESPONSE),          # MaxOutputResponse
        struct.pack("<I", _SMB2_0_IOCTL_IS_FSCTL),            # Flags
        struct.pack("<I", 0),                                 # Reserved2
    ]) + data
    reply = _send_and_receive(
        sock, _smb2_header(_SMB2_COMMAND_IOCTL, session_id=session_id,
                          tree_id=tree_id, message_id=message_id) + body)
    if reply is None or len(reply) < 12:
        return None
    status = struct.unpack_from("<I", reply, 8)[0]
    if status not in (_STATUS_SUCCESS, _STATUS_BUFFER_OVERFLOW):
        return None
    if len(reply) < 64 + 40:
        return None
    # OutputOffset/OutputCount caen en el cuerpo de la respuesta IOCTL
    # (MS-SMB2 §2.2.32), a los desplazamientos 32 y 36 de ese cuerpo.
    output_offset, output_count = struct.unpack_from("<II", reply, 64 + 32)
    return (reply[output_offset:output_offset + output_count]
            if output_offset + output_count <= len(reply) else None)


class _NamedPipeSession:
    """Una sesión SMB2 anónima abierta sobre una tubería con nombre bajo ``IPC$``.

    Encapsula la secuencia NEGOTIATE → SESSION_SETUP (anónimo) → TREE_CONNECT
    → CREATE (cada fase, una función de módulo privada que recibe el estado
    que necesita por parámetro — CONVENCIONES.md §5.1), y a partir de ahí
    ofrece :meth:`transceive` sobre la tubería abierta. Una sola llamada por
    instancia: no hay reconexión ni reintento, y ``close`` es incondicional.
    """

    def __init__(self, sock) -> None:
        self._sock = sock
        self._session_id = 0
        self._tree_id = 0
        self._file_id = b"\x00" * 16
        self._message_id = 0

    def open(self, pipe_name: str) -> bool:
        """Negocia, abre sesión anónima, conecta a ``IPC$`` y abre la tubería.

        Args:
            pipe_name: El nombre de la tubería, sin barra inicial (``"srvsvc"``).

        Returns:
            bool: Si las cuatro fases completaron con éxito.
        """
        if _send_and_receive(self._sock, build_negotiate_request()) is None:
            return False
        setup = _session_setup(self._sock, self._message_id + 1)
        if setup is None:
            return False
        self._session_id, message_id = setup
        connected = _tree_connect(self._sock, self._session_id, message_id)
        if connected is None:
            return False
        self._tree_id, message_id = connected
        created = _create_pipe(self._sock, self._session_id, self._tree_id, message_id, pipe_name)
        if created is None:
            return False
        self._file_id, self._message_id = created
        return True

    def transceive(self, data: bytes) -> Optional[bytes]:
        """Manda ``data`` a la tubería y devuelve lo que conteste, en una sola vuelta.

        Args:
            data: El PDU de DCE/RPC a mandar.

        Returns:
            Optional[bytes]: La respuesta, o ``None`` si la operación falló.
        """
        result = _pipe_transceive(
            self._sock, self._session_id, self._tree_id, self._file_id, self._message_id, data)
        self._message_id += 1
        return result

    def close(self) -> None:
        """Cierra el socket. No manda ``CLOSE``/``TREE_DISCONNECT``/``LOGOFF``.

        Un cliente de una sola llamada no necesita dejar la tubería ni la
        sesión en un estado limpio para el servidor: cerrar el socket basta,
        y ahorra tres mensajes que nadie va a leer la respuesta de.
        """
        try:
            self._sock.close()
        except OSError:
            pass


def _bind_and_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        sock, pipe_name: str, interface_uuid: str,
        interface_version: Tuple[int, int],
        opnum: Optional[int] = None,
                   stub: bytes = b"") -> Tuple[Optional[bool], Optional[bytes]]:
    """Abre la tubería, hace el ``bind`` y, si se pide, una llamada.

    Args:
        sock: El socket ya conectado.
        pipe_name: La tubería a abrir bajo ``IPC$``.
        interface_uuid: La interfaz a proponer en el ``bind``.
        interface_version: Su versión.
        opnum: El número de operación a llamar tras el ``bind``, o ``None``
            para sólo comprobar si el ``bind`` se acepta. Por defecto ``None``.
        stub: El cuerpo NDR de la llamada, si ``opnum`` no es ``None``. Por
            defecto vacío.

    Returns:
        tuple: ``(aceptado, respuesta)``. ``aceptado`` es ``None`` si no se
            pudo ni conectar la sesión o abrir la tubería, y en ese caso
            ``respuesta`` es siempre ``None``; si no, ``aceptado`` dice si el
            ``bind`` se aceptó, y ``respuesta`` es el cuerpo NDR de la llamada
            pedida (``None`` si no se pidió ninguna, o si falló).
    """
    session = _NamedPipeSession(sock)
    if not session.open(pipe_name):
        session.close()
        return None, None
    try:
        bind_reply = session.transceive(build_bind_request(interface_uuid, interface_version))
        if bind_reply is None:
            return None, None
        bind_ack = parse_bind_ack(bind_reply)
        if bind_ack is None:
            return None, None
        if not bind_ack.accepted or opnum is None:
            return bind_ack.accepted, None
        response = session.transceive(build_request_pdu(opnum, stub))
        stub_out = parse_response_pdu(response) if response is not None else None
        return True, stub_out
    finally:
        session.close()


# =========================================================================
# API PÚBLICA
# =========================================================================

def fetch_shares(host: str, port: int = 445, timeout: float = 5.0,
                 connect: Optional[Callable] = None) -> List[ShareInfo]:
    """Lista las carpetas compartidas de un equipo, sin usar ninguna credencial.

    Abre una sesión SMB anónima, hace un ``bind`` a ``srvsvc`` y llama a
    ``NetrShareEnum``. Un equipo con las carpetas compartidas restringidas a
    usuarios autenticados rechaza la sesión anónima o la propia llamada, y en
    los dos casos el resultado es la lista vacía — el mismo caso que "no hay
    ninguna compartida", porque a quien use esta lista sólo le importa si hay
    alguna visible sin credenciales.

    Args:
        host: El objetivo.
        port: El puerto de SMB. Por defecto ``445``.
        timeout: El plazo de conexión y de cada lectura, en segundos. Por
            defecto ``5.0``.
        connect: Un ``(dirección, plazo) -> socket`` inyectable. Por defecto
            ``socket.create_connection``.

    Returns:
        List[ShareInfo]: Las carpetas compartidas visibles; vacía si no hay
            ninguna, si el equipo no permite sesión anónima, o si la conexión
            falló.
    """
    opener = connect or socket.create_connection
    try:
        sock = opener((host, port), timeout)
    except OSError as err:
        logger.debug("Windows RPC connect failed for %s:%s: %s", host, port, err)
        return []
    sock.settimeout(timeout)
    accepted, stub = _bind_and_call(
        sock, SRVSVC_PIPE, SRVSVC_INTERFACE_UUID, SRVSVC_INTERFACE_VERSION,
        opnum=_OPNUM_NETR_SHARE_ENUM, stub=build_netr_share_enum_request())
    if not accepted or stub is None:
        return []
    return parse_netr_share_enum_response(stub)


def probe_named_pipe_rpc(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        host: str, pipe_name: str, interface_uuid: str,
        interface_version: Tuple[int, int], port: int = 445,
        timeout: float = 5.0,
                         connect: Optional[Callable] = None) -> Optional[bool]:
    """Comprueba si una interfaz RPC servida por una tubería con nombre acepta un saludo anónimo.

    No llama a ningún método: sólo abre la sesión anónima, abre la tubería y
    manda el ``bind``. Que el servidor lo acepte ya es la exposición que L111
    necesita ver — el spooler de impresión (:data:`SPOOLSS_PIPE`,
    :data:`SPOOLSS_INTERFACE_UUID`) es el primer consumidor previsto.

    Args:
        host: El objetivo.
        pipe_name: La tubería a abrir (``"spoolss"``).
        interface_uuid: La interfaz a proponer.
        interface_version: Su versión.
        port: El puerto de SMB. Por defecto ``445``.
        timeout: El plazo de conexión y de cada lectura, en segundos. Por
            defecto ``5.0``.
        connect: Un ``(dirección, plazo) -> socket`` inyectable. Por defecto
            ``socket.create_connection``.

    Returns:
        Optional[bool]: ``True`` si el ``bind`` se aceptó, ``False`` si la
            tubería se abrió pero el ``bind`` se rechazó, ``None`` si no se
            pudo ni establecer la sesión anónima o abrir la tubería (equipo
            inalcanzable, sesión anónima no permitida, o la tubería no
            existe).
    """
    opener = connect or socket.create_connection
    try:
        sock = opener((host, port), timeout)
    except OSError as err:
        logger.debug("Windows RPC connect failed for %s:%s: %s", host, port, err)
        return None
    sock.settimeout(timeout)
    accepted, _stub = _bind_and_call(sock, pipe_name, interface_uuid, interface_version)
    return accepted


def probe_endpoint_mapper(host: str, port: int = EPMAP_PORT, timeout: float = 5.0,
                          connect: Optional[Callable] = None) -> Optional[bool]:
    """Comprueba si el localizador de puntos finales acepta un saludo anónimo.

    A diferencia de :func:`probe_named_pipe_rpc`, no hay SMB de por medio: el
    localizador de puntos finales escucha directamente en el puerto 135
    (MS-RPCE §2.2.5.2), así que el ``bind`` se manda tal cual sobre la
    conexión TCP recién abierta.

    Args:
        host: El objetivo.
        port: El puerto del localizador. Por defecto :data:`EPMAP_PORT` (135).
        timeout: El plazo de conexión y de lectura, en segundos. Por defecto
            ``5.0``.
        connect: Un ``(dirección, plazo) -> socket`` inyectable. Por defecto
            ``socket.create_connection``.

    Returns:
        Optional[bool]: ``True`` si el ``bind`` se aceptó, ``False`` si el
            servidor contestó pero lo rechazó, ``None`` si no se pudo
            conectar o el servidor no contestó nada entendible.
    """
    opener = connect or socket.create_connection
    try:
        sock = opener((host, port), timeout)
    except OSError as err:
        logger.debug("Endpoint mapper connect failed for %s:%s: %s", host, port, err)
        return None
    try:
        sock.settimeout(timeout)
        sock.sendall(build_bind_request(EPMAP_INTERFACE_UUID, EPMAP_INTERFACE_VERSION))
        data = sock.recv(4096)
    except OSError as err:
        logger.debug("Endpoint mapper exchange failed for %s:%s: %s", host, port, err)
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if not data:
        return None
    bind_ack = parse_bind_ack(data)
    return bind_ack.accepted if bind_ack is not None else None
