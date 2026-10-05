"""Memcached, ZooKeeper y Cassandra: servicios de datos con protocolo propio.

Los tres comparten la pregunta que ya se hace a Redis, MongoDB y PostgreSQL:
¿deja entrar sin credenciales? Y la misma trampa: **contestar no es dejar
entrar**. Memcached contesta ``version`` aunque esté restringido, ZooKeeper
contesta ``srvr`` sin dar acceso al árbol y Cassandra contesta ``OPTIONS``
siempre. Cada bloque de abajo fija esa distinción con su señuelo: el mismo
servicio con la autenticación exigida no debe generar el aviso.
"""

import struct

import pytest

from src.modules.features.themis.lybra.checks import (
    is_cassandra_service,
    is_memcached_service,
    is_zookeeper_service,
    load_checks,
)
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting import default_dissectors
from src.modules.features.themis.lybra.fingerprinting import cassandra as cql
from src.modules.features.themis.lybra.fingerprinting import zookeeper as zk
from src.modules.features.themis.lybra.fingerprinting.cassandra import (
    CassandraDissector,
    CassandraProbe,
    fingerprint_cassandra,
    parse_release_version,
    parse_supported,
)
from src.modules.features.themis.lybra.fingerprinting.memcached import (
    MemcachedDissector,
    MemcachedProbe,
    fingerprint_memcached,
    parse_memcached_version,
)
from src.modules.features.themis.lybra.fingerprinting.zookeeper import (
    ZookeeperDissector,
    ZookeeperProbe,
    fingerprint_zookeeper,
    parse_get_children_response,
    parse_srvr_version,
)
from src.modules.features.themis.lybra.script_checks import (
    CassandraUnauthenticatedAccessPlugin,
    MemcachedUnauthenticatedAccessPlugin,
    ZookeeperUnauthenticatedAccessPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit


class _NullLimiter:
    def acquire(self, _host):
        pass


class _Context:
    def __init__(self, port):
        self.target = "10.0.0.5"
        self.service = Service(port, "tcp", "")

    def acquire(self):
        pass


class _ScriptedSocket:
    """Un socket cuyos ``recv`` devuelven, en orden, lo que se le dio.

    Cada elemento es lo que un ``recv`` entrega; los trozos se sirven partidos
    cuando el llamador pide menos bytes, como hace un socket de verdad.
    """

    def __init__(self, replies, sent):
        self._replies = list(replies)
        self._sent = sent

    def settimeout(self, _timeout):
        pass

    def sendall(self, payload):
        self._sent.append(payload)

    def recv(self, size):
        if not self._replies:
            return b""
        chunk = self._replies[0]
        if len(chunk) > size:
            self._replies[0] = chunk[size:]
            return chunk[:size]
        self._replies.pop(0)
        return chunk

    def close(self):
        pass


def _connector(*connections):
    """Un ``connect`` que entrega un socket por conexión, en el orden dado."""
    sent = []
    queue = list(connections)

    def connect(_address, _timeout):
        if not queue:
            raise ConnectionRefusedError("sin más conexiones")
        return _ScriptedSocket(queue.pop(0), sent)

    return connect, sent


def _refuse(_address, _timeout):
    raise ConnectionRefusedError("cerrado")


# ======================================================================
# Memcached
# ======================================================================

OPEN_STATS = b"STAT pid 1\r\nSTAT uptime 100\r\nSTAT curr_items 7\r\nEND\r\n"


def test_memcached_version_is_read_from_the_version_reply():
    assert parse_memcached_version("VERSION 1.6.21\r\n") == "1.6.21"
    assert parse_memcached_version("ERROR\r\n") is None


def test_an_open_memcached_is_told_apart_from_one_that_only_answers_version():
    assert fingerprint_memcached("VERSION 1.6.21\r\n", OPEN_STATS.decode()).allows_unauthenticated_access
    restricted = fingerprint_memcached("VERSION 1.6.21\r\n", "ERROR\r\n")
    assert restricted.product == "Memcached" and not restricted.allows_unauthenticated_access


def test_something_that_is_not_memcached_is_not_identified():
    assert fingerprint_memcached("+OK POP3 ready\r\n").product is None


def test_the_memcached_probe_only_sends_read_commands():
    connect, sent = _connector([b"VERSION 1.6.21\r\n"] + [OPEN_STATS])
    MemcachedProbe(connect=connect).fetch("10.0.0.5")
    assert sent == [b"version\r\n", b"stats\r\n"]


def test_the_memcached_probe_does_not_ask_stats_of_something_else():
    connect, sent = _connector([b"-ERR unknown command\r\n"])
    reply = MemcachedProbe(connect=connect).fetch("10.0.0.5")
    assert reply == ("-ERR unknown command\r\n", "")
    assert sent == [b"version\r\n"]


def test_the_memcached_probe_yields_nothing_when_refused_or_silent():
    assert MemcachedProbe(connect=_refuse).fetch("10.0.0.5") is None
    connect, _sent = _connector([b""])
    assert MemcachedProbe(connect=connect).fetch("10.0.0.5") is None


def _memcached_plugin(*replies):
    connect, _sent = _connector(list(replies))
    return MemcachedUnauthenticatedAccessPlugin(probe=MemcachedProbe(connect=connect))


def test_the_memcached_check_fires_only_when_stats_come_back():
    assert _memcached_plugin(b"VERSION 1.6.21\r\n", OPEN_STATS).run(_Context(11211)) is True
    # Señuelo: contesta version, pero stats no devuelve nada (SASL / restringido).
    assert _memcached_plugin(b"VERSION 1.6.21\r\n", b"ERROR\r\n").run(_Context(11211)) is False


def test_the_memcached_dissector_reports_product_and_version():
    connect, _sent = _connector([b"VERSION 1.6.21\r\n", OPEN_STATS])
    result = MemcachedDissector(probe=MemcachedProbe(connect=connect)).probe(
        "10.0.0.5", Service(11211, "tcp", "memcached"), _NullLimiter())
    assert (result.product, result.version, result.label) == ("Memcached", "1.6.21", "Memcached")


# ======================================================================
# ZooKeeper
# ======================================================================

SRVR_REPLY = ("Zookeeper version: 3.7.1-a2fb57c55f1ee8ce9bc9d9bd5ec0e4bc6e1a0c85, "
              "built on 2022-05-07 06:45 UTC\nLatency min/avg/max: 0/0.0/0\n")


def _frame(body):
    return struct.pack(">i", len(body)) + body


def _connect_response(timeout=10000, session_id=0x1000A):
    return _frame(struct.pack(">iiqi", 0, timeout, session_id, 16) + bytes(16))


def _children_response(names, error=0):
    body = struct.pack(">iqi", 1, 5, error)
    if error == 0:
        body += struct.pack(">i", len(names))
        for name in names:
            encoded = name.encode()
            body += struct.pack(">i", len(encoded)) + encoded
    return _frame(body)


def test_the_zookeeper_version_is_the_numeric_part_of_srvr():
    assert parse_srvr_version(SRVR_REPLY) == "3.7.1"
    assert parse_srvr_version("srvr is not executed because it is not in the whitelist.") is None


def test_the_children_of_the_root_are_read():
    frame = _children_response(["zookeeper", "kafka"])[4:]
    assert parse_get_children_response(frame) == ["zookeeper", "kafka"]


def test_a_noauth_error_yields_no_children():
    assert parse_get_children_response(_children_response([], error=-102)[4:]) is None


def test_a_truncated_children_reply_yields_nothing():
    frame = _children_response(["zookeeper", "kafka"])[4:]
    assert parse_get_children_response(frame[:-3]) is None


def test_an_open_zookeeper_is_told_apart_from_one_that_only_answers_srvr():
    assert fingerprint_zookeeper(SRVR_REPLY, ["zookeeper"]).allows_unauthenticated_access
    closed = fingerprint_zookeeper(SRVR_REPLY, None)
    assert closed.product == "ZooKeeper" and closed.version == "3.7.1"
    assert not closed.allows_unauthenticated_access


def test_nothing_that_looks_like_zookeeper_is_not_identified():
    assert fingerprint_zookeeper("", None).product is None


def test_the_zookeeper_probe_opens_a_session_reads_the_root_and_closes_it():
    connect, sent = _connector(
        [SRVR_REPLY.encode()],
        [_connect_response(), _children_response(["zookeeper"])],
    )
    srvr_reply, children = ZookeeperProbe(connect=connect).fetch("10.0.0.5")
    assert parse_srvr_version(srvr_reply) == "3.7.1" and children == ["zookeeper"]
    assert sent == [b"srvr", zk.build_connect_request(), zk.build_get_children_request("/", xid=1),
                    zk.build_close_session_request()]


def test_the_zookeeper_probe_never_writes_a_node():
    connect, sent = _connector([SRVR_REPLY.encode()],
                               [_connect_response(), _children_response([])])
    ZookeeperProbe(connect=connect).fetch("10.0.0.5")
    # Las operaciones que usa son getChildren (8) y closeSession (-11); ninguna escribe.
    types = [struct.unpack(">ii", frame[4:12])[1] for frame in sent[2:]]
    assert types == [zk.OP_GET_CHILDREN, zk.OP_CLOSE_SESSION]


def test_the_zookeeper_probe_gives_up_on_a_refused_session():
    connect, _sent = _connector([SRVR_REPLY.encode()], [_connect_response(timeout=0, session_id=0)])
    srvr_reply, children = ZookeeperProbe(connect=connect).fetch("10.0.0.5")
    assert children is None and parse_srvr_version(srvr_reply) == "3.7.1"


def test_the_zookeeper_probe_yields_nothing_when_refused():
    assert ZookeeperProbe(connect=_refuse).fetch("10.0.0.5") is None


def _zookeeper_plugin(srvr, session_frames):
    connect, _sent = _connector([srvr], session_frames)
    return ZookeeperUnauthenticatedAccessPlugin(probe=ZookeeperProbe(connect=connect))


def test_the_zookeeper_check_fires_only_when_the_tree_can_be_read():
    assert _zookeeper_plugin(SRVR_REPLY.encode(),
                             [_connect_response(), _children_response(["zookeeper"])]
                             ).run(_Context(2181)) is True
    # Señuelo: la sesión se abre pero la raíz exige credenciales (NoAuth).
    assert _zookeeper_plugin(SRVR_REPLY.encode(),
                             [_connect_response(), _children_response([], error=-102)]
                             ).run(_Context(2181)) is False
    # Señuelo: contesta srvr y cierra la sesión binaria.
    assert _zookeeper_plugin(SRVR_REPLY.encode(), [b""]).run(_Context(2181)) is False


# ======================================================================
# Cassandra
# ======================================================================

def _response(opcode, body=b"", version=4):
    return struct.pack(">BBhBi", version | 0x80, 0, 1, opcode, len(body)) + body


def _string(text):
    return struct.pack(">H", len(text)) + text.encode()


def _supported(extra=()):
    options = [("CQL_VERSION", ["3.4.7"]), ("COMPRESSION", ["lz4", "snappy"])] + list(extra)
    body = struct.pack(">H", len(options))
    for key, values in options:
        body += _string(key) + struct.pack(">H", len(values)) + b"".join(_string(v) for v in values)
    return _response(cql.OPCODE_SUPPORTED, body)


def _version_result(version):
    body = struct.pack(">iii", 2, 0x0001, 1) + _string("system") + _string("local")
    body += _string("release_version") + struct.pack(">H", 0x000D)
    encoded = version.encode()
    body += struct.pack(">i", 1) + struct.pack(">i", len(encoded)) + encoded
    return _response(cql.OPCODE_RESULT, body)


def _authenticate():
    return _response(cql.OPCODE_AUTHENTICATE,
                     _string("org.apache.cassandra.auth.PasswordAuthenticator"))


def test_the_supported_options_are_read():
    body = _supported()[9:]
    assert parse_supported(body)["COMPRESSION"] == ["lz4", "snappy"]
    assert parse_supported(body[:5]) == {}


def test_the_release_version_is_read_from_a_single_varchar_row():
    assert parse_release_version(_version_result("4.1.3")[9:]) == "4.1.3"


def test_a_result_that_is_not_the_expected_shape_gives_no_version():
    assert parse_release_version(b"") is None
    assert parse_release_version(struct.pack(">iii", 1, 0, 0)) is None     # kind Void


def test_a_ready_startup_means_no_authentication_and_authenticate_means_it_is_required():
    supported = parse_supported(_supported()[9:])
    open_server = fingerprint_cassandra(supported, cql.OPCODE_READY, b"", _version_result("4.1.3")[9:])
    assert (open_server.product, open_server.version) == ("Cassandra", "4.1.3")
    assert open_server.allows_unauthenticated_access

    closed = fingerprint_cassandra(supported, cql.OPCODE_AUTHENTICATE, _authenticate()[9:])
    assert closed.product == "Cassandra" and closed.version is None
    assert not closed.allows_unauthenticated_access
    assert closed.authenticator == "org.apache.cassandra.auth.PasswordAuthenticator"


def test_scylladb_is_told_apart_and_never_given_the_cassandra_version():
    """Su release_version es el de compatibilidad con Cassandra; cruzarlo con
    las CVE de Cassandra produciría hallazgos que no son suyos."""
    supported = parse_supported(_supported([("SCYLLA_SHARD", ["0"])])[9:])
    scylla = fingerprint_cassandra(supported, cql.OPCODE_READY, b"", _version_result("3.0.8")[9:])
    assert scylla.product == "ScyllaDB" and scylla.version is None


def test_something_that_is_not_cql_is_not_identified():
    assert fingerprint_cassandra({}, None).product is None


def _cassandra_probe(*dialogues):
    connect, sent = _connector(*dialogues)
    return CassandraProbe(connect=connect), sent


def test_the_cassandra_probe_stops_at_startup_when_authentication_is_required():
    probe, sent = _cassandra_probe([_supported(), _authenticate()])
    fingerprint = probe.fetch("10.0.0.5")
    assert not fingerprint.allows_unauthenticated_access
    # OPTIONS y STARTUP; no se manda ninguna consulta contra un servidor cerrado.
    assert [frame[4] for frame in sent] == [cql.OPCODE_OPTIONS, cql.OPCODE_STARTUP]


def test_the_cassandra_probe_reads_the_version_only_after_ready():
    probe, sent = _cassandra_probe([_supported(), _response(cql.OPCODE_READY), _version_result("4.1.3")])
    fingerprint = probe.fetch("10.0.0.5")
    assert (fingerprint.version, fingerprint.allows_unauthenticated_access) == ("4.1.3", True)
    assert [frame[4] for frame in sent] == [cql.OPCODE_OPTIONS, cql.OPCODE_STARTUP, cql.OPCODE_QUERY]


def test_the_cassandra_probe_falls_back_to_protocol_v3():
    unsupported = _response(cql.OPCODE_ERROR, struct.pack(">i", 0x000A) + _string("Invalid or unsupported protocol version"))
    probe, sent = _cassandra_probe([unsupported],
                                   [_supported(), _response(cql.OPCODE_READY, version=3), _version_result("2.1.20")])
    fingerprint = probe.fetch("10.0.0.5")
    assert fingerprint.allows_unauthenticated_access
    assert sent[0][0] == 4 and sent[1][0] == 3


def test_the_cassandra_probe_yields_nothing_when_refused_or_not_cql():
    assert CassandraProbe(connect=_refuse).fetch("10.0.0.5") is None
    probe, _sent = _cassandra_probe([b"HTTP/1.1 400 Bad Request\r\n\r\n"])
    assert probe.fetch("10.0.0.5") is None


def test_the_cassandra_dissector_reports_product_and_version():
    probe, _sent = _cassandra_probe([_supported(), _response(cql.OPCODE_READY), _version_result("4.1.3")])
    result = CassandraDissector(probe=probe).probe(
        "10.0.0.5", Service(9042, "tcp", "cassandra"), _NullLimiter())
    assert (result.product, result.version, result.label) == ("Cassandra", "4.1.3", "Cassandra")


def test_the_cassandra_check_fires_only_for_a_server_that_says_ready():
    probe, _sent = _cassandra_probe([_supported(), _response(cql.OPCODE_READY), _version_result("4.1.3")])
    assert CassandraUnauthenticatedAccessPlugin(probe=probe).run(_Context(9042)) is True
    # Señuelo: el mismo servidor exigiendo autenticación.
    probe, _sent = _cassandra_probe([_supported(), _authenticate()])
    assert CassandraUnauthenticatedAccessPlugin(probe=probe).run(_Context(9042)) is False
    assert CassandraUnauthenticatedAccessPlugin(probe=CassandraProbe(connect=_refuse)).run(_Context(9042)) is False


# ======================================================================
# Selección de servicios y registro
# ======================================================================

@pytest.mark.parametrize("service, predicate, dissector_label", [
    (Service(11211, "tcp", ""), is_memcached_service, "Memcached"),
    (Service(2181, "tcp", ""), is_zookeeper_service, "ZooKeeper"),
    (Service(9042, "tcp", ""), is_cassandra_service, "Cassandra"),
    (Service(31000, "tcp", "memcached"), is_memcached_service, "Memcached"),
    (Service(31001, "tcp", "zookeeper"), is_zookeeper_service, "ZooKeeper"),
    (Service(31002, "tcp", "cassandra"), is_cassandra_service, "Cassandra"),
])
def test_each_service_is_claimed_by_exactly_its_own_dissector(service, predicate, dissector_label):
    assert predicate(service)
    claimed = [d.label for d in default_dissectors() if d.applies(service)]
    assert claimed == [dissector_label]


def test_the_dissectors_do_not_claim_each_others_services():
    assert not is_memcached_service(Service(9042, "tcp", "cassandra"))
    assert not is_zookeeper_service(Service(11211, "tcp", "memcached"))
    assert not is_cassandra_service(Service(2181, "tcp", "zookeeper"))
    assert not MemcachedDissector().applies(Service(80, "tcp", "http"))
    assert not ZookeeperDissector().applies(Service(80, "tcp", "http"))


def test_the_three_ports_are_swept_by_default_and_named():
    from src.modules.features.themis.lybra.transport import DEFAULT_PORTS, WELL_KNOWN_PORTS

    assert (WELL_KNOWN_PORTS[11211], WELL_KNOWN_PORTS[2181], WELL_KNOWN_PORTS[9042]) == \
        ("memcached", "zookeeper", "cassandra")
    assert all(port in DEFAULT_PORTS for port in (11211, 2181, 9042))
    # Ninguno aparece dos veces: un puerto repetido se sondearía dos veces.
    assert len(DEFAULT_PORTS) == len(set(DEFAULT_PORTS))


@pytest.mark.parametrize("check_id, severity, service", [
    ("memcached-unauthenticated-access", "HIGH", "memcached"),
    ("zookeeper-unauthenticated-access", "HIGH", "zookeeper"),
    ("cassandra-unauthenticated-access", "CRITICAL", "cassandra"),
])
def test_each_check_is_registered_and_wired_to_its_feed_entry(check_id, severity, service):
    check = next(c for c in load_checks() if c.id == check_id)
    assert (check.severity, check.mode, check.service) == (severity, "safe", service)
    assert check.category == "exposed_service"
    assert check.script in default_script_plugins()
