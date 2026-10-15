"""El dissector de MongoDB.

Completa el trío de dissectors de bases de datos, y trae el hallazgo más
famoso de la lista: durante años las instalaciones por defecto escuchaban en
todas las interfaces sin autenticación.

El bloque que más importa aquí es el que distingue **contestar** de **dejar
entrar**. Ver el docstring del módulo: `hello` responde siempre, así que un
check construido sobre "ha contestado" marcaría como expuesto todo MongoDB
alcanzable, incluidos los correctamente cerrados.
"""

import struct

import pytest

from src.modules.features.themis.lybra.checks import is_mongodb_service
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.mongo import (
    BUILD_INFO_COMMAND,
    HELLO_COMMAND,
    LEGACY_BUILD_INFO_COMMAND,
    LEGACY_HELLO_COMMAND,
    LEGACY_LIST_DATABASES_COMMAND,
    LIST_DATABASES_COMMAND,
    MESSAGE_HEADER_SIZE,
    OP_MSG,
    OP_QUERY,
    OP_REPLY,
    MongoDissector,
    MongoProbe,
    build_bson_document,
    build_op_msg,
    build_op_query,
    fingerprint_mongo,
    parse_bson_document,
    parse_op_msg,
)

pytestmark = pytest.mark.unit


def _op_msg_reply(fields):
    """Una respuesta OP_MSG con el documento dado."""
    document = build_bson_document(fields)
    body = struct.pack("<I", 0) + b"\x00" + document
    return struct.pack("<iiii", MESSAGE_HEADER_SIZE + len(body), 1, 1, OP_MSG) + body


HELLO_REPLY = _op_msg_reply([
    ("helloOk", True), ("maxWireVersion", 21), ("version", "7.0.5"), ("ok", 1),
])
OPEN_LISTING = _op_msg_reply([("databases", "admin,config,local"), ("ok", 1)])
BUILD_INFO_REPLY = _op_msg_reply([("version", "7.0.5"), ("ok", 1)])
DENIED_LISTING = _op_msg_reply([
    ("ok", 0),
    ("errmsg", "command listDatabases requires authentication"),
    ("code", 13),
])


# ==================================================================== BSON


def test_a_document_survives_the_round_trip():
    document = build_bson_document([("hello", 1), ("$db", "admin")])
    assert parse_bson_document(document) == {"hello": 1, "$db": "admin"}


def test_the_command_name_stays_first():
    """MongoDB exige que el nombre del comando sea el primer campo del
    documento. De ahí que se serialice una lista de pares y no un diccionario:
    el orden es parte del protocolo, no una preferencia."""
    document = build_bson_document(HELLO_COMMAND)
    assert document[4] == 0x10                      # tipo int32
    assert document[5:5 + 6] == b"hello\x00"


@pytest.mark.parametrize("data", [b"", b"\x05\x00", b"\x05\x00\x00\x00"])
def test_a_truncated_document_reads_as_empty(data):
    assert parse_bson_document(data) == {}


def test_an_unsupported_type_yields_nothing_rather_than_a_partial_read():
    """Avanzar a ciegas con un desplazamiento equivocado produce basura que
    *parece* datos, y eso es peor que no leer nada."""
    body = b"\x7f" + b"raro\x00" + b"\x01\x02"
    document = struct.pack("<i", len(body) + 5) + body + b"\x00"
    assert parse_bson_document(document) == {}


# ================================================================== OP_MSG


def test_the_message_declares_its_own_length_and_opcode():
    message = build_op_msg(HELLO_COMMAND)
    length, _request, _response, opcode = struct.unpack_from("<iiii", message, 0)
    assert length == len(message)
    assert opcode == OP_MSG


def test_a_reply_with_another_opcode_is_ignored():
    body = struct.pack("<I", 0) + b"\x00" + build_bson_document([("ok", 1)])
    other = struct.pack("<iiii", MESSAGE_HEADER_SIZE + len(body), 1, 1, 2012) + body
    assert parse_op_msg(other) == {}


@pytest.mark.parametrize("data", [b"", b"\x00" * 16, b"HTTP/1.1 400 Bad Request"])
def test_a_reply_that_is_not_op_msg_reads_as_empty(data):
    assert parse_op_msg(data) == {}


# ============================================ contestar no es dejar entrar


def test_hello_alone_identifies_the_product_and_its_version():
    fingerprint = fingerprint_mongo(HELLO_REPLY)
    assert fingerprint.product == "MongoDB"
    assert fingerprint.version == "7.0.5"
    assert fingerprint.max_wire_version == 21


def test_a_server_that_serves_its_catalogue_without_credentials_is_flagged():
    fingerprint = fingerprint_mongo(HELLO_REPLY, OPEN_LISTING)
    assert fingerprint.allows_unauthenticated_access


def test_a_server_with_auth_answers_hello_but_is_not_flagged():
    """**El test central de este módulo.**

    `hello` es el handshake del protocolo y contesta siempre, con `--auth` y
    sin él — tiene que hacerlo, porque el cliente necesita saber con quién
    habla antes de poder autenticarse. Si la evidencia de exposición fuera "ha
    contestado", este caso —un servidor correctamente cerrado— saldría marcado
    como CRITICAL.
    """
    fingerprint = fingerprint_mongo(HELLO_REPLY, DENIED_LISTING)
    assert fingerprint.product == "MongoDB"          # identificado igualmente
    assert fingerprint.version == "7.0.5"
    assert not fingerprint.allows_unauthenticated_access


def test_no_listing_reply_at_all_is_not_taken_as_open():
    """Sin respuesta al segundo comando no hay evidencia, y sin evidencia no
    hay hallazgo — nunca al revés."""
    assert not fingerprint_mongo(HELLO_REPLY, b"").allows_unauthenticated_access


def test_an_ok_reply_without_the_database_list_is_not_taken_as_open():
    partial = _op_msg_reply([("ok", 1)])
    assert not fingerprint_mongo(HELLO_REPLY, partial).allows_unauthenticated_access


def test_something_that_is_not_mongodb_is_not_identified():
    assert fingerprint_mongo(b"+OK POP3 ready\r\n").product is None
    assert fingerprint_mongo(_op_msg_reply([("ok", 1)])).product is None


# ============================================================== la sonda


class _ScriptedSocket:
    def __init__(self, replies, sent):
        self._replies = list(replies)
        self._sent = sent

    def settimeout(self, _timeout):
        pass

    def sendall(self, payload):
        self._sent.append(payload)

    def recv(self, _size):
        return self._replies.pop(0) if self._replies else b""

    def close(self):
        pass


def _probe_with(replies):
    sent = []
    return MongoProbe(connect=lambda _a, _t: _ScriptedSocket(replies, sent)), sent


def test_the_probe_asks_its_commands_over_one_connection():
    probe, sent = _probe_with([HELLO_REPLY, OPEN_LISTING, BUILD_INFO_REPLY])
    hello_reply, list_reply, build_info_reply = probe.fetch("10.0.0.5")
    assert (hello_reply, list_reply, build_info_reply) == (
        HELLO_REPLY, OPEN_LISTING, BUILD_INFO_REPLY)
    assert sent == [build_op_msg(HELLO_COMMAND, request_id=1),
                    build_op_msg(LIST_DATABASES_COMMAND, request_id=2),
                    build_op_msg(BUILD_INFO_COMMAND, request_id=3)]


def test_the_probe_never_writes_anything():
    """Los dos comandos son lecturas: `hello` es el handshake y
    `listDatabases` una consulta de catálogo."""
    probe, sent = _probe_with([HELLO_REPLY, OPEN_LISTING])
    probe.fetch("10.0.0.5")
    combined = b"".join(sent).lower()
    for writing_command in (b"insert", b"update", b"delete", b"drop"):
        assert writing_command not in combined


def test_a_server_that_says_nothing_yields_nothing():
    probe, _sent = _probe_with([b""])
    assert probe.fetch("10.0.0.5") is None


def test_a_refused_connection_yields_nothing():
    def refuse(_address, _timeout):
        raise ConnectionRefusedError("cerrado")

    assert MongoProbe(connect=refuse).fetch("10.0.0.5") is None


# =========================================================== el dissector


class _NullLimiter:
    def acquire(self, _host):
        pass


def test_the_dissector_claims_the_sharded_ports_too():
    """27018 y 27019 son los puertos de un `mongos` y de un servidor de
    configuración: ahí vive el catálogo entero del clúster."""
    dissector = MongoDissector()
    for port in (27017, 27018, 27019):
        assert dissector.applies(Service(port, "tcp", ""))
    assert dissector.applies(Service(37017, "tcp", "mongodb"))
    assert not dissector.applies(Service(5432, "tcp", "postgresql"))
    assert is_mongodb_service(Service(27017, "tcp", ""))


def test_the_dissector_reports_product_and_version():
    probe, _sent = _probe_with([HELLO_REPLY, DENIED_LISTING])
    result = MongoDissector(probe=probe).probe(
        "10.0.0.5", Service(27017, "tcp", "mongodb"), _NullLimiter())
    assert (result.product, result.version, result.label) == ("MongoDB", "7.0.5", "MongoDB")


# ============================================ el check y su registro


class _Context:
    def __init__(self, port=27017):
        self.target = "10.0.0.5"
        self.service = Service(port, "tcp", "mongodb")

    def acquire(self):
        pass


def _plugin(replies):
    from src.modules.features.themis.lybra.script_checks import (
        MongoUnauthenticatedAccessPlugin,
    )
    probe, _sent = _probe_with(replies)
    return MongoUnauthenticatedAccessPlugin(probe=probe)


def test_the_check_fires_only_for_a_server_that_hands_over_its_catalogue():
    assert _plugin([HELLO_REPLY, OPEN_LISTING]).run(_Context()) is True
    assert _plugin([HELLO_REPLY, DENIED_LISTING]).run(_Context()) is False


def test_the_check_stays_quiet_without_evidence():
    from src.modules.features.themis.lybra.script_checks import (
        MongoUnauthenticatedAccessPlugin,
    )

    def refuse(_address, _timeout):
        raise ConnectionRefusedError("cerrado")

    plugin = MongoUnauthenticatedAccessPlugin(probe=MongoProbe(connect=refuse))
    assert plugin.run(_Context()) is False


def test_the_check_is_registered_and_wired_to_its_feed_entry():
    from src.modules.features.themis.lybra.checks import load_checks
    from src.modules.features.themis.lybra.script_checks import default_script_plugins

    check = next(c for c in load_checks() if c.id == "mongodb-unauthenticated-access")
    assert check.severity == "CRITICAL" and check.mode == "safe"
    assert check.service == "mongodb"
    assert check.category == "exposed_service"
    assert check.script in default_script_plugins()


# ======================================== servidores anteriores a 3.6 (OP_QUERY)


def _op_reply(fields):
    """Una respuesta ``OP_REPLY`` —la de un servidor anterior a 3.6— con el documento dado."""
    document = build_bson_document(fields)
    prefix = struct.pack("<iqii", 8, 0, 0, 1)  # flags, cursorID, startingFrom, numberReturned
    body = prefix + document
    return struct.pack("<iiii", MESSAGE_HEADER_SIZE + len(body), 1, 1, OP_REPLY) + body


LEGACY_HELLO_REPLY = _op_reply([("ismaster", True), ("maxWireVersion", 5), ("ok", 1)])
LEGACY_OPEN_LISTING = _op_reply([("databases", "admin,local"), ("ok", 1)])
LEGACY_BUILD_INFO_REPLY = _op_reply([("version", "3.4.24"), ("ok", 1)])


def _two_connections(first_replies, second_replies):
    """Un ``connect`` que entrega dos sockets guionizados, uno por conexión."""
    sent = []
    sockets = [_ScriptedSocket(first_replies, sent), _ScriptedSocket(second_replies, sent)]
    return MongoProbe(connect=lambda _a, _t: sockets.pop(0)), sent


def test_an_op_reply_is_read_like_an_op_msg():
    assert parse_op_msg(LEGACY_HELLO_REPLY)["maxWireVersion"] == 5


def test_an_op_query_names_the_admin_command_collection():
    message = build_op_query(LEGACY_HELLO_COMMAND, request_id=7)
    assert struct.unpack_from("<i", message, 12)[0] == OP_QUERY
    assert message[MESSAGE_HEADER_SIZE + 4:MESSAGE_HEADER_SIZE + 4 + 11] == b"admin.$cmd\x00"


def test_a_server_older_than_3_6_is_asked_again_with_op_query():
    """MongoDB 3.4 contesta a un OP_MSG cerrando la conexión; el sondeo tiene
    que volver a intentarlo en el único idioma que ese servidor habla."""
    probe, sent = _two_connections(
        [b""],
        [LEGACY_HELLO_REPLY, LEGACY_OPEN_LISTING, LEGACY_BUILD_INFO_REPLY],
    )
    fingerprint = fingerprint_mongo(*probe.fetch("10.0.0.5"))
    assert sent[1:] == [build_op_query(LEGACY_HELLO_COMMAND, request_id=1),
                        build_op_query(LEGACY_LIST_DATABASES_COMMAND, request_id=2),
                        build_op_query(LEGACY_BUILD_INFO_COMMAND, request_id=3)]
    assert (fingerprint.product, fingerprint.version) == ("MongoDB", "3.4.24")
    assert fingerprint.allows_unauthenticated_access


def test_a_modern_server_is_not_asked_a_second_time():
    probe, sent = _two_connections([HELLO_REPLY, DENIED_LISTING, BUILD_INFO_REPLY], [b""])
    assert probe.fetch("10.0.0.5") is not None
    assert len(sent) == 3


def test_the_version_comes_from_build_info_when_hello_does_not_carry_it():
    """``hello`` no publica la versión; ``buildInfo`` sí."""
    hello_without_version = _op_msg_reply([("helloOk", True), ("maxWireVersion", 21), ("ok", 1)])
    fingerprint = fingerprint_mongo(hello_without_version, DENIED_LISTING, BUILD_INFO_REPLY)
    assert fingerprint.version == "7.0.5"
