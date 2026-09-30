"""El lector del saludo TLS en crudo: construye el ``ClientHello`` y lee la elección del servidor.

Se prueba contra dos tipos de servidor. Uno **real** —el de la librería TLS de
Python, en loopback, con una configuración conocida— para comprobar que el
lector identifica lo mismo que el módulo basado en esa librería. Otro **de
guion**, que contesta bytes escritos a mano, para lo que ninguna librería moderna
ofrece (TLS 1.0) y para los casos límite del formato (un mensaje partido en dos
registros, una alerta, una respuesta que no es TLS).
"""

import datetime
import socket
import ssl
import struct
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.modules.features.themis.lybra.fingerprinting.tls import TlsProbe
from src.modules.features.themis.lybra.fingerprinting.tls_hello import (
    CIPHER_SUITES,
    HANDSHAKE_CERTIFICATE,
    HANDSHAKE_SERVER_HELLO_DONE,
    SUITES_LEGACY,
    SUITES_TLS13,
    SUITES_WEAK,
    VERSION_NAMES,
    VERSION_TLS_1_0,
    VERSION_TLS_1_1,
    VERSION_TLS_1_2,
    VERSION_TLS_1_3,
    TlsHelloProbe,
    build_client_hello,
    parse_server_flight,
)

pytestmark = pytest.mark.unit

_ALERT_PROTOCOL_VERSION = 70


# ============================================================ servidores de prueba


@pytest.fixture(scope="module")
def certificate_files(tmp_path_factory):
    """Un certificado autofirmado, en disco, para el servidor TLS real."""
    directory = tmp_path_factory.mktemp("tls-hello")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return str(certificate_path), str(key_path)


class _Server:
    """Un servidor en loopback que atiende conexiones una tras otra, en un hilo."""

    def __init__(self, handle):
        self._handle = handle
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            try:
                connection.settimeout(3)
                self._handle(connection)
            except (OSError, ssl.SSLError):
                pass
            finally:
                connection.close()

    def close(self):
        self._listener.close()


def _real_tls_server(certificate_files, minimum, maximum, ciphers=None):
    """Un servidor con la librería TLS de Python, fijado a un rango de versiones."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*certificate_files)
    context.minimum_version = minimum
    context.maximum_version = maximum
    if ciphers:
        context.set_ciphers(ciphers)

    def handle(connection):
        context.wrap_socket(connection, server_side=True).close()
    return _Server(handle)


def _scripted_server(reply):
    """Un servidor que lee el saludo y contesta ``reply`` tal cual."""
    def handle(connection):
        connection.recv(4096)
        connection.sendall(reply)
    return _Server(handle)


@pytest.fixture
def servers():
    opened = []
    yield opened
    for server in opened:
        server.close()


# ============================================================ mensajes a mano


def _record(record_type, payload, version=VERSION_TLS_1_2):
    return bytes([record_type]) + struct.pack("!HH", version, len(payload)) + payload


def _handshake(message_type, body):
    return bytes([message_type]) + len(body).to_bytes(3, "big") + body


def _server_hello_body(version, cipher, extensions=b"", random=b"\x11" * 32):
    body = struct.pack("!H", version) + random + b"\x00" + struct.pack("!H", cipher) + b"\x00"
    if extensions:
        body += struct.pack("!H", len(extensions)) + extensions
    return body


def _tls10_reply():
    """Lo que contesta un servidor que sólo habla TLS 1.0 y elige AES128-SHA."""
    hello = _handshake(2, _server_hello_body(VERSION_TLS_1_0, 0x002F))
    done = _handshake(14, b"")
    return _record(22, hello + done, VERSION_TLS_1_0)


# ============================================================ el ClientHello


def test_the_client_hello_is_a_well_formed_handshake_record():
    data = build_client_hello((VERSION_TLS_1_2,), server_name="example.test")

    assert data[0] == 22                                        # registro handshake
    assert struct.unpack("!H", data[3:5])[0] == len(data) - 5   # longitud del registro
    assert data[5] == 1                                         # ClientHello
    assert int.from_bytes(data[6:9], "big") == len(data) - 9    # longitud del mensaje
    assert b"example.test" in data


def test_a_tls_1_0_only_hello_announces_tls_1_0_in_the_version_field():
    """Lo que la librería de Python ya no ofrece por defecto: se pide con dos bytes."""
    data = build_client_hello((VERSION_TLS_1_0,))

    assert struct.unpack("!H", data[9:11])[0] == VERSION_TLS_1_0


def test_several_legacy_versions_are_offered_through_the_highest_one():
    data = build_client_hello((VERSION_TLS_1_0, VERSION_TLS_1_1, VERSION_TLS_1_2))

    assert struct.unpack("!H", data[9:11])[0] == VERSION_TLS_1_2
    assert b"\x00\x2b" not in _extension_ids(data)              # sin supported_versions


def test_tls_1_3_is_announced_in_the_supported_versions_extension():
    data = build_client_hello((VERSION_TLS_1_2, VERSION_TLS_1_3))

    assert struct.unpack("!H", data[9:11])[0] == VERSION_TLS_1_2  # el campo nunca lleva 1.3
    assert 0x002B in _extension_ids(data)
    assert 0x0033 in _extension_ids(data)                          # y una clave para el intercambio


def test_the_default_cipher_offer_follows_the_announced_versions():
    tls13_only = build_client_hello((VERSION_TLS_1_3,))
    legacy_only = build_client_hello((VERSION_TLS_1_2,))

    assert struct.pack("!H", SUITES_TLS13[0]) in tls13_only
    assert struct.pack("!H", SUITES_TLS13[0]) not in legacy_only
    assert struct.pack("!H", SUITES_LEGACY[0]) in legacy_only


def test_an_explicit_cipher_offer_is_sent_exactly():
    weak_only = build_client_hello((VERSION_TLS_1_2,), cipher_suites=SUITES_WEAK)

    assert struct.pack("!H", 0x0005) in weak_only               # RC4
    assert struct.pack("!H", 0xC02F) not in weak_only           # nada moderno


def test_announcing_no_version_is_an_error():
    with pytest.raises(ValueError):
        build_client_hello(())


def _extension_ids(hello: bytes) -> set:
    """Los tipos de extensión de un ClientHello, recorriéndolo como un servidor."""
    position = 9 + 2 + 32
    position += 1 + hello[position]                                  # sesión
    position += 2 + struct.unpack("!H", hello[position:position + 2])[0]  # cifrados
    position += 1 + hello[position]                                  # compresión
    end = position + 2 + struct.unpack("!H", hello[position:position + 2])[0]
    position += 2
    found = set()
    while position < end:
        extension_type, length = struct.unpack("!HH", hello[position:position + 4])
        found.add(extension_type)
        position += 4 + length
    return found


# ============================================================ leer la respuesta


def test_a_tls_1_0_server_hello_is_read_without_any_tls_library():
    flight = parse_server_flight(_tls10_reply())

    assert flight.server_hello.version == VERSION_TLS_1_0
    assert flight.server_hello.version_name == "TLSv1"
    assert flight.server_hello.cipher_name == "AES128-SHA"
    assert flight.get_message(HANDSHAKE_SERVER_HELLO_DONE) == b""


def test_the_tls_1_3_version_comes_from_the_extension_not_from_the_version_field():
    extensions = struct.pack("!HH", 0x002B, 2) + struct.pack("!H", VERSION_TLS_1_3)
    reply = _record(22, _handshake(2, _server_hello_body(VERSION_TLS_1_2, 0x1302, extensions)))

    flight = parse_server_flight(reply)

    assert flight.server_hello.version == VERSION_TLS_1_3
    assert flight.server_hello.cipher_name == "TLS_AES_256_GCM_SHA384"
    assert flight.server_hello.extension_types == (0x002B,)


def test_a_hello_retry_request_is_flagged():
    random = bytes.fromhex("cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c")
    reply = _record(22, _handshake(2, _server_hello_body(VERSION_TLS_1_2, 0x1301, random=random)))

    assert parse_server_flight(reply).server_hello.is_hello_retry_request is True


def test_a_message_split_across_two_records_is_reassembled():
    message = _handshake(2, _server_hello_body(VERSION_TLS_1_2, 0xC02F)) + _handshake(14, b"")
    reply = _record(22, message[:20]) + _record(22, message[20:])

    flight = parse_server_flight(reply)

    assert flight.server_hello.cipher_suite == 0xC02F
    assert flight.get_message(HANDSHAKE_SERVER_HELLO_DONE) is not None


def test_an_alert_is_reported_with_its_description():
    flight = parse_server_flight(_record(21, bytes([2, _ALERT_PROTOCOL_VERSION])))

    assert flight.server_hello is None
    assert (flight.alert.level, flight.alert.description) == (2, _ALERT_PROTOCOL_VERSION)


@pytest.mark.parametrize("garbage", [b"", b"HTTP/1.1 400 Bad Request\r\n\r\n", b"\x16\x03"])
def test_bytes_that_are_not_tls_give_an_empty_flight(garbage):
    flight = parse_server_flight(garbage)

    assert flight.server_hello is None and flight.alert is None and flight.messages == ()


def test_a_truncated_server_hello_is_ignored():
    reply = _record(22, _handshake(2, b"\x03\x03" + b"\x00" * 10))

    assert parse_server_flight(reply).server_hello is None


def test_an_unknown_cipher_has_no_name_but_keeps_its_code():
    reply = _record(22, _handshake(2, _server_hello_body(VERSION_TLS_1_2, 0xFEFE)))

    hello = parse_server_flight(reply).server_hello

    assert hello.cipher_suite == 0xFEFE and hello.cipher_name is None


def test_every_cipher_family_the_module_names_has_a_unique_code():
    assert len(CIPHER_SUITES) == len({suite.iana_name for suite in CIPHER_SUITES.values()})
    assert set(SUITES_WEAK) <= set(CIPHER_SUITES)
    assert VERSION_NAMES[VERSION_TLS_1_2] == "TLSv1.2"


# ============================================================ contra un servidor real


def test_it_identifies_the_same_version_and_cipher_as_the_python_tls_module(
        servers, certificate_files):
    """El criterio de cierre: mismo resultado que el módulo basado en la librería."""
    server = _real_tls_server(
        certificate_files, ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2,
        ciphers="ECDHE-RSA-AES128-GCM-SHA256")
    servers.append(server)

    reference = TlsProbe(timeout=3).fetch("127.0.0.1", server.port)
    flight = TlsHelloProbe(timeout=3).query("127.0.0.1", server.port)

    assert reference is not None and flight.server_hello is not None
    assert flight.server_hello.version_name == reference.protocol == "TLSv1.2"
    assert flight.server_hello.cipher_name == reference.cipher == "ECDHE-RSA-AES128-GCM-SHA256"


def test_it_reads_the_certificate_and_the_key_exchange_of_a_tls_1_2_flight(
        servers, certificate_files):
    server = _real_tls_server(
        certificate_files, ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2,
        ciphers="ECDHE-RSA-AES128-GCM-SHA256")
    servers.append(server)

    flight = TlsHelloProbe(timeout=3).query("127.0.0.1", server.port)

    assert flight.get_message(HANDSHAKE_CERTIFICATE)
    assert flight.get_message(12)                       # ServerKeyExchange
    assert flight.get_message(HANDSHAKE_SERVER_HELLO_DONE) is not None


def test_it_picks_tls_1_3_when_the_server_allows_it_among_several_offered_versions(
        servers, certificate_files):
    server = _real_tls_server(certificate_files, ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3)
    servers.append(server)

    reference = TlsProbe(timeout=3).fetch("127.0.0.1", server.port)
    flight = TlsHelloProbe(timeout=3).query(
        "127.0.0.1", server.port, versions=(VERSION_TLS_1_2, VERSION_TLS_1_3))

    assert flight.server_hello.version_name == reference.protocol == "TLSv1.3"
    assert flight.server_hello.cipher_suite in SUITES_TLS13


def test_a_server_that_does_not_speak_the_offered_version_answers_with_an_alert(
        servers, certificate_files):
    """Preguntar por TLS 1.0 sin ningún rodeo: un servidor que sólo habla 1.2 lo rechaza."""
    server = _real_tls_server(certificate_files, ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2)
    servers.append(server)

    flight = TlsHelloProbe(timeout=3).query(
        "127.0.0.1", server.port, versions=(VERSION_TLS_1_0,))

    assert flight.server_hello is None
    assert flight.alert.description == _ALERT_PROTOCOL_VERSION


# ============================================================ contra un servidor de guion


def test_it_can_ask_for_a_version_the_python_library_no_longer_offers(servers):
    server = _scripted_server(_tls10_reply())
    servers.append(server)

    flight = TlsHelloProbe(timeout=3).query(
        "127.0.0.1", server.port, versions=(VERSION_TLS_1_0,), server_name="legacy.test")

    assert flight.server_hello.version_name == "TLSv1"
    assert flight.server_hello.cipher_name == "AES128-SHA"


def test_a_server_that_hangs_up_without_answering_gives_none(servers):
    server = _scripted_server(b"")
    servers.append(server)

    assert TlsHelloProbe(timeout=3).query("127.0.0.1", server.port) is None


def test_a_refused_connection_gives_none():
    def refuse(address, timeout):
        raise ConnectionRefusedError()

    assert TlsHelloProbe(connect=refuse).query("127.0.0.1", 1) is None
