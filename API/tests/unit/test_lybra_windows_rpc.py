"""El cliente mínimo de llamadas remotas de Windows: DCE/RPC sobre una tubería con nombre.

Lybra identificaba un equipo Windows por SMB y por LDAP, pero ninguno de los
dos deja ver qué carpetas comparte sin autenticarse, ni si sus servicios de
impresión o de RPC están expuestos: eso vive en el protocolo de llamadas
remotas de administración, que el motor no hablaba. Aquí se prueban las tres
piezas por separado —el formato NDR, los PDU de DCE/RPC, y el transporte SMB2
anónimo— y luego de punta a punta contra un servidor de guion.
"""

import struct

import pytest

from src.modules.features.themis.lybra.fingerprinting import windows_rpc as rpc

pytestmark = pytest.mark.unit


# ============================================================ NDR: cadenas y punteros


def test_a_string_round_trips_through_encode_and_decode():
    encoded = rpc._ndr_string("PUBLICO")  # pylint: disable=protected-access

    text, next_offset = rpc._read_ndr_string(encoded, 0)  # pylint: disable=protected-access

    assert text == "PUBLICO"
    assert next_offset == len(encoded)
    assert len(encoded) % 4 == 0


def test_an_empty_string_round_trips():
    encoded = rpc._ndr_string("")  # pylint: disable=protected-access

    text, _ = rpc._read_ndr_string(encoded, 0)  # pylint: disable=protected-access

    assert text == ""


def test_a_string_of_odd_length_is_padded_to_four_bytes():
    """"abc" son 4 unidades UTF-16 con el terminador: la cabecera ya es múltiplo
    de cuatro y el cuerpo (8 bytes) también, así que no debería sobrar relleno;
    con una letra de más el cuerpo deja de serlo y sí lo necesita."""
    even = rpc._ndr_string("abc")     # pylint: disable=protected-access
    odd = rpc._ndr_string("abcde")    # pylint: disable=protected-access

    assert len(even) % 4 == 0
    assert len(odd) % 4 == 0


def test_a_truncated_string_header_is_reported():
    with pytest.raises(ValueError):
        rpc._read_ndr_string(b"\x01\x00\x00\x00", 0)  # pylint: disable=protected-access


def test_a_string_offset_that_is_not_zero_is_rejected():
    """Este cliente sólo entiende cadenas completas, nunca una subcadena."""
    malformed = struct.pack("<III", 1, 1, 1) + "x\x00".encode("utf-16-le")

    with pytest.raises(ValueError):
        rpc._read_ndr_string(malformed, 0)  # pylint: disable=protected-access


def test_a_null_pointer_has_no_deferred_body():
    referent, next_offset = rpc._read_ndr_pointer(b"\x00\x00\x00\x00", 0)  # pylint: disable=protected-access

    assert referent == 0 and next_offset == 4


def test_a_uuid_matches_the_known_wire_form_of_srvsvc():
    """Valor de referencia: los tres primeros campos en little-endian, los dos
    últimos tal cual — lo que cualquier captura de un bind a srvsvc trae."""
    wire = rpc._uuid_wire_bytes(rpc.SRVSVC_INTERFACE_UUID)  # pylint: disable=protected-access

    assert wire == bytes.fromhex("c84f324b7016d30112785a47bf6ee188")


# ============================================================ el PDU de bind


def test_a_bind_request_names_the_interface_and_ndr_as_the_only_transfer_syntax():
    request = rpc.build_bind_request(rpc.SRVSVC_INTERFACE_UUID, rpc.SRVSVC_INTERFACE_VERSION)

    assert request[0:4] == bytes((5, 0, rpc.PDU_TYPE_BIND, 0x03))
    assert struct.unpack_from("<H", request, 8)[0] == len(request)   # frag_length
    assert rpc._uuid_wire_bytes(rpc.SRVSVC_INTERFACE_UUID) in request  # pylint: disable=protected-access
    assert rpc._uuid_wire_bytes(rpc._NDR_TRANSFER_SYNTAX_UUID) in request  # pylint: disable=protected-access


def _bind_ack(accepted: bool, num_results: int = 1) -> bytes:
    """Un ``bind_ack`` de un solo resultado, aceptado o rechazado.

    ``p_result_list`` va alineado a cuatro bytes desde el principio del PDU
    (MS-RPCE §2.2.6.4): con un ``sec_addr`` vacío, el hueco entre su campo de
    longitud (que termina en el byte 26) y ``num_results`` son dos bytes de
    relleno explícitos, no una casualidad del formato.
    """
    sec_addr = struct.pack("<H", 0)                                  # longitud 0, sin datos
    pad = b"\x00" * ((4 - (16 + 8 + len(sec_addr)) % 4) % 4)
    body = (
        struct.pack("<HHI", 4280, 4280, 0)                          # max_xmit, max_recv, assoc_group
        + sec_addr + pad
        + struct.pack("<BBH", num_results, 0, 0)                    # num_results, reserved, reserved2
        + struct.pack("<HH", 0 if accepted else 2, 0)                # result, reason
        + rpc._uuid_wire_bytes(rpc._NDR_TRANSFER_SYNTAX_UUID)        # pylint: disable=protected-access
        + struct.pack("<HH", *rpc._NDR_TRANSFER_SYNTAX_VERSION)      # pylint: disable=protected-access
    )
    header = struct.pack("<BBBB", 5, 0, rpc.PDU_TYPE_BIND_ACK, 0x03) + b"\x10\x00\x00\x00" \
        + struct.pack("<HHI", 16 + len(body), 0, 1)
    return header + body


def test_an_accepted_bind_is_read_as_accepted():
    ack = rpc.parse_bind_ack(_bind_ack(accepted=True))

    assert ack.pdu_type == rpc.PDU_TYPE_BIND_ACK and ack.accepted is True


def test_a_rejected_context_is_read_as_not_accepted():
    ack = rpc.parse_bind_ack(_bind_ack(accepted=False))

    assert ack.pdu_type == rpc.PDU_TYPE_BIND_ACK and ack.accepted is False


def test_a_bind_nak_is_a_rejection_without_looking_at_results():
    header = struct.pack("<BBBB", 5, 0, rpc.PDU_TYPE_BIND_NAK, 0x03) + b"\x10\x00\x00\x00" \
        + struct.pack("<HHI", 18, 0, 1) + struct.pack("<H", 2)  # reject_reason

    ack = rpc.parse_bind_ack(header)

    assert ack.pdu_type == rpc.PDU_TYPE_BIND_NAK and ack.accepted is False


def test_zero_results_is_not_accepted():
    assert rpc.parse_bind_ack(_bind_ack(accepted=True, num_results=0)).accepted is False


def test_a_non_dce_rpc_response_is_none():
    assert rpc.parse_bind_ack(b"HTTP/1.1 400\r\n") is None
    assert rpc.parse_bind_ack(b"") is None


def test_a_truncated_bind_ack_is_none_not_a_crash():
    assert rpc.parse_bind_ack(_bind_ack(accepted=True)[:20]) is None


# ============================================================ request/response


def test_a_request_pdu_carries_the_opnum_and_the_stub_untouched():
    pdu = rpc.build_request_pdu(15, b"stub-de-prueba")

    assert pdu[2] == rpc.PDU_TYPE_REQUEST
    assert struct.unpack_from("<H", pdu, 16 + 6)[0] == 15    # opnum
    assert pdu.endswith(b"stub-de-prueba")


def _response_pdu(stub: bytes) -> bytes:
    body = struct.pack("<IHBB", len(stub), 0, 0, 0) + stub
    header = struct.pack("<BBBB", 5, 0, rpc.PDU_TYPE_RESPONSE, 0x03) + b"\x10\x00\x00\x00" \
        + struct.pack("<HHI", 16 + len(body), 0, 1)
    return header + body


def test_a_response_pdu_gives_back_its_stub():
    assert rpc.parse_response_pdu(_response_pdu(b"resultado")) == b"resultado"


def test_a_fault_pdu_is_none():
    header = struct.pack("<BBBB", 5, 0, rpc.PDU_TYPE_FAULT, 0x03) + b"\x10\x00\x00\x00" \
        + struct.pack("<HHI", 24, 0, 1) + struct.pack("<IHBBI", 0, 0, 0, 0, 5)  # status: denegado

    assert rpc.parse_response_pdu(header) is None


# ============================================================ NetrShareEnum: ida y vuelta


def _share_info_1_response(entries):
    """El cuerpo NDR de una respuesta ``NetrShareEnum`` de nivel 1.

    ``entries`` es una lista de ``(nombre, tipo, comentario)``.
    """
    header = (
        struct.pack("<I", 1)                    # Level
        + struct.pack("<I", 1)                  # union switch
        + struct.pack("<I", 0x00020000)         # puntero al contenedor
        + struct.pack("<I", len(entries))       # EntriesRead
        + struct.pack("<I", 0x00020004 if entries else 0)  # Buffer
    )
    if not entries:
        array = b""
        strings = b""
    else:
        array = struct.pack("<I", len(entries))  # max_count
        strings = b""
        referent = 0x00030000
        fixed_entries = b""
        for name, share_type, remark in entries:
            fixed_entries += struct.pack("<III", referent, share_type, referent + 1)
            referent += 2
        for name, _share_type, remark in entries:
            strings += rpc._ndr_string(name)     # pylint: disable=protected-access
            strings += rpc._ndr_string(remark)   # pylint: disable=protected-access
        array += fixed_entries
    tail = struct.pack("<I", len(entries)) + struct.pack("<I", 0) + struct.pack("<I", 0)
    return header + array + strings + tail


def test_no_shares_gives_an_empty_list():
    assert rpc.parse_netr_share_enum_response(_share_info_1_response([])) == []


def test_the_listed_shares_come_back_with_their_name_type_and_remark():
    stub = _share_info_1_response([
        ("Publico", 0, "Carpeta publica"),
        ("ADMIN$", 0x80000000, ""),
    ])

    shares = rpc.parse_netr_share_enum_response(stub)

    assert [share.name for share in shares] == ["Publico", "ADMIN$"]
    assert shares[0].remark == "Carpeta publica"
    assert shares[0].is_hidden is False
    assert shares[1].is_hidden is True                 # por el bit alto Y por el "$"


def test_a_wrong_level_is_rejected():
    stub = struct.pack("<I", 2) + b"\x00" * 20   # Level=2: no es el que este cliente pide

    assert rpc.parse_netr_share_enum_response(stub) == []


def test_a_denied_call_gives_no_shares():
    """Señuelo del criterio de cierre: carpetas restringidas a usuarios
    autenticados no deben listarse, aunque el PDU llegara a construirse."""
    stub = _share_info_1_response([("Secreta", 0, "")])
    denied = stub[:-4] + struct.pack("<I", 5)   # NET_API_STATUS: acceso denegado

    assert rpc.parse_netr_share_enum_response(denied) == []


def test_error_more_data_still_returns_what_arrived():
    stub = _share_info_1_response([("Publico", 0, "")])
    more_data = stub[:-4] + struct.pack("<I", 234)   # ERROR_MORE_DATA

    assert [share.name for share in rpc.parse_netr_share_enum_response(more_data)] == ["Publico"]


def test_truncated_ndr_is_an_empty_list_not_a_crash():
    assert rpc.parse_netr_share_enum_response(b"\x01\x00\x00\x00") == []


def test_the_request_asks_for_level_one_with_no_server_name_and_no_resume_handle():
    request = rpc.build_netr_share_enum_request()

    assert struct.unpack_from("<I", request, 0)[0] == 0          # ServerName: puntero nulo
    assert struct.unpack_from("<I", request, 4)[0] == 1          # InfoStruct.Level
    assert struct.unpack_from("<I", request, -4)[0] == 0         # ResumeHandle: puntero nulo


# ============================================================ transporte SMB2 (de punta a punta)


class _FakeSocket:
    """Un socket falso: contesta con la respuesta que le toque, en orden.

    Cada elemento de ``replies`` es el cuerpo SMB2 completo (sin cabecera
    NetBIOS) de la respuesta a la petición correspondiente, en el mismo orden
    en que ``_NamedPipeSession`` las manda.
    """

    def __init__(self, replies):
        self._replies = list(replies)
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _n):
        if not self._pending:
            self._pending = self._replies.pop(0) if self._replies else b""
        chunk, self._pending = self._pending[:_n], self._pending[_n:]
        return chunk

    _pending = b""

    def settimeout(self, _seconds):
        pass

    def close(self):
        pass


def _wrap(body: bytes) -> bytes:
    return bytes((0x00,)) + len(body).to_bytes(3, "big") + body


def _smb2_header_bytes(command, status=0, session_id=0, tree_id=0):
    return b"".join([
        b"\xfeSMB", struct.pack("<H", 64), struct.pack("<H", 0), struct.pack("<I", status),
        struct.pack("<H", command), struct.pack("<H", 1), struct.pack("<I", 0),
        struct.pack("<I", 0), struct.pack("<Q", 0), struct.pack("<I", 0),
        struct.pack("<I", tree_id), struct.pack("<Q", session_id), b"\x00" * 16,
    ])


_NEGOTIATE_REPLY = _wrap(_smb2_header_bytes(0) + b"\x00" * 64)


def _session_setup_replies(session_id=99):
    more_processing = _wrap(_smb2_header_bytes(1, status=0xC0000016, session_id=session_id) + b"\x00" * 8)
    success = _wrap(_smb2_header_bytes(1, status=0, session_id=session_id) + b"\x00" * 8)
    return [more_processing, success]


def _tree_connect_reply(tree_id=7):
    return _wrap(_smb2_header_bytes(3, status=0, tree_id=tree_id) + b"\x00" * 16)


def _create_reply(file_id=b"\xAB" * 16, session_id=99, tree_id=7):
    body = b"\x00" * 64 + file_id + b"\x00" * 8
    return _wrap(_smb2_header_bytes(5, status=0, session_id=session_id, tree_id=tree_id) + body)


def _ioctl_reply(output: bytes, session_id=99, tree_id=7):
    output_offset = 64 + 48
    fixed = b"\x00" * 32 + struct.pack("<II", output_offset, len(output)) + b"\x00" * 8
    return _wrap(_smb2_header_bytes(0x0B, status=0, session_id=session_id, tree_id=tree_id)
                 + fixed + output)


def test_a_full_session_opens_and_calls_over_a_scripted_transport():
    """De punta a punta: negociar, sesión anónima, IPC$, abrir la tubería,
    bind y una llamada, todo sobre un transporte de guion."""
    shares_stub = _share_info_1_response([("Publico", 0, "")])
    bind_ack_pdu = _bind_ack(accepted=True)
    response_pdu = rpc.build_request_pdu(rpc._OPNUM_NETR_SHARE_ENUM, shares_stub)  # pylint: disable=protected-access
    response_pdu = response_pdu[:2] + bytes((rpc.PDU_TYPE_RESPONSE,)) + response_pdu[3:]

    sock = _FakeSocket([
        _NEGOTIATE_REPLY, *_session_setup_replies(), _tree_connect_reply(), _create_reply(),
        _ioctl_reply(bind_ack_pdu), _ioctl_reply(response_pdu),
    ])

    shares = rpc.fetch_shares("10.0.0.1", connect=lambda *a, **k: sock)

    assert [share.name for share in shares] == ["Publico"]
    assert len(sock.sent) == 7                               # negotiate + 2x setup + tree + create + 2x ioctl


def test_a_server_that_rejects_the_anonymous_session_gives_no_shares():
    denied = _wrap(_smb2_header_bytes(1, status=0xC0000022, session_id=99) + b"\x00" * 8)  # ACCESS_DENIED
    sock = _FakeSocket([_NEGOTIATE_REPLY, _session_setup_replies()[0], denied])

    assert rpc.fetch_shares("10.0.0.1", connect=lambda *a, **k: sock) == []


def test_a_rejected_bind_is_reported_as_not_accepted_not_as_none():
    sock = _FakeSocket([
        _NEGOTIATE_REPLY, *_session_setup_replies(), _tree_connect_reply(), _create_reply(),
        _ioctl_reply(_bind_ack(accepted=False)),
    ])

    assert rpc.probe_named_pipe_rpc(
        "10.0.0.1", rpc.SPOOLSS_PIPE, rpc.SPOOLSS_INTERFACE_UUID, rpc.SPOOLSS_INTERFACE_VERSION,
        connect=lambda *a, **k: sock) is False


def test_a_connection_that_cannot_even_negotiate_gives_none():
    def refuse(_address, _timeout):
        raise ConnectionRefusedError()

    assert rpc.probe_named_pipe_rpc(
        "10.0.0.1", rpc.SRVSVC_PIPE, rpc.SRVSVC_INTERFACE_UUID, rpc.SRVSVC_INTERFACE_VERSION,
        connect=refuse) is None


def test_a_pipe_that_does_not_exist_gives_none():
    """El CREATE falla (STATUS_OBJECT_NAME_NOT_FOUND): la sesión llegó a
    abrirse, pero la tubería no está — sigue sin ser una credencial probada."""
    not_found = _wrap(_smb2_header_bytes(5, status=0xC0000034, session_id=99, tree_id=7) + b"\x00" * 8)
    sock = _FakeSocket([_NEGOTIATE_REPLY, *_session_setup_replies(), _tree_connect_reply(), not_found])

    assert rpc.fetch_shares("10.0.0.1", connect=lambda *a, **k: sock) == []


# ============================================================ el localizador de puntos finales


def test_the_endpoint_mapper_probe_sends_a_raw_bind_with_no_smb_wrapper():
    class _RawSocket:
        def __init__(self):
            self.sent = b""

        def sendall(self, data):
            self.sent += data

        def recv(self, _n):
            return _bind_ack(accepted=True)

        def settimeout(self, _seconds):
            pass

        def close(self):
            pass

    sock = _RawSocket()

    accepted = rpc.probe_endpoint_mapper("10.0.0.1", connect=lambda *a, **k: sock)

    assert accepted is True
    assert sock.sent[0:2] == bytes((5, 0))                    # cabecera de DCE/RPC, no de NetBIOS/SMB
    assert rpc._uuid_wire_bytes(rpc.EPMAP_INTERFACE_UUID) in sock.sent  # pylint: disable=protected-access


def test_the_endpoint_mapper_probe_gives_none_on_silence():
    class _SilentSocket:
        def sendall(self, _data):
            pass

        def recv(self, _n):
            return b""

        def settimeout(self, _seconds):
            pass

        def close(self):
            pass

    assert rpc.probe_endpoint_mapper("10.0.0.1", connect=lambda *a, **k: _SilentSocket()) is None


def test_the_endpoint_mapper_probe_gives_none_on_a_refused_connection():
    def refuse(_address, _timeout):
        raise ConnectionRefusedError()

    assert rpc.probe_endpoint_mapper("10.0.0.1", connect=refuse) is None
