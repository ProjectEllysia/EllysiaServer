"""Si un servidor acepta versiones obsoletas de TLS o cifrados débiles, aunque no los elija.

El saludo normal negocia lo mejor que comparten cliente y servidor, así que un
servidor que acepta TLS 1.0 y 1.2 parece sano. Los checks preguntan por cada
versión obsoleta ofreciendo sólo esa. Los tests del plugin usan una sonda
falsa; los de la sonda real levantan un servidor en ``127.0.0.1`` (el conftest
permite el bucle local) y se saltan si el OpenSSL local no puede hablar la
versión.
"""

import datetime
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.modules.features.themis.lybra.checks import CheckRuntime, ScriptContext, load_checks
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.tls import TlsProbe, _legacy_protocol_context
from src.modules.features.themis.lybra.script_checks import (
    TlsDeprecatedProtocolPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_HTTPS = Service(port=443, protocol="tcp", name="https")
_FTP = Service(port=21, protocol="tcp", name="ftp")


class _FakeProbe:
    """Sonda que contesta por versión lo que se le diga; ``None`` = no se sabe."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def fetch_accepts_protocol(self, host, port, protocol, starttls=None):
        self.calls.append((port, protocol, starttls))
        return self.answers.get(protocol)


def test_a_server_that_accepts_tls10_besides_tls12_fires():
    probe = _FakeProbe({"SSLv3": False, "TLSv1": True, "TLSv1.1": False})
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsDeprecatedProtocolPlugin(probe=probe).run(context) is True
    assert context.evidence == {"acceptedProtocols": ["TLSv1"]}
    assert [protocol for _port, protocol, _starttls in probe.calls] == ["SSLv3", "TLSv1", "TLSv1.1"]


def test_a_server_that_only_speaks_tls12_and_up_does_not_fire():
    probe = _FakeProbe({"SSLv3": False, "TLSv1": False, "TLSv1.1": False})
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsDeprecatedProtocolPlugin(probe=probe).run(context) is False
    assert context.evidence == {}


def test_a_version_the_local_build_cannot_offer_asserts_nothing():
    # None es «no se sabe»: ni dispara ni cuenta como rechazada.
    probe = _FakeProbe({"SSLv3": None, "TLSv1": None, "TLSv1.1": None})
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsDeprecatedProtocolPlugin(probe=probe).run(context) is False
    assert context.evidence == {}


def test_plain_ftp_is_asked_after_auth_tls():
    probe = _FakeProbe({})
    plugin = TlsDeprecatedProtocolPlugin(probe=probe)

    assert plugin.applies(_FTP) is True
    assert plugin.applies(Service(port=22, protocol="tcp", name="ssh")) is False
    plugin.run(ScriptContext(target="h", service=_FTP))
    assert {starttls for _port, _protocol, starttls in probe.calls} == {"ftp"}


def test_the_runtime_emits_the_finding_through_the_plugin():
    plugins = default_script_plugins()
    plugins["tls-deprecated-protocol"] = TlsDeprecatedProtocolPlugin(
        probe=_FakeProbe({"TLSv1": True}))
    checks = [check for check in load_checks() if check.id == "tls-deprecated-protocol"]

    findings = CheckRuntime(checks, lambda *a: None, script_plugins=plugins).run("10.0.0.5", [_HTTPS])

    assert [finding["check_id"] for finding in findings] == ["lybra:tls-deprecated-protocol@2"]


def test_both_checks_are_script_checks_now():
    by_id = {check.id: check for check in load_checks()}
    assert by_id["tls-deprecated-protocol"].type == "script"
    assert by_id["tls-weak-cipher"].type == "script"
    assert {"tls-deprecated-protocol", "tls-weak-cipher"} <= set(default_script_plugins())


def test_an_unknown_version_cannot_be_offered():
    assert _legacy_protocol_context("SSLv2") is None


# ---- Sonda real contra un servidor de bucle local ---------------------------


@pytest.fixture(scope="module")
def certificate_files(tmp_path_factory):
    """Un certificado autofirmado RSA de 2048 bits, en dos ficheros PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(1)
                   .not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=1))
                   .sign(key, hashes.SHA256()))
    folder = tmp_path_factory.mktemp("tls-legacy")
    certificate_path, key_path = folder / "cert.pem", folder / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return str(certificate_path), str(key_path)


def _serve(minimum, maximum, certificate_files) -> int:
    """Levanta un servidor TLS entre ``minimum`` y ``maximum`` y devuelve su puerto."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.set_ciphers("ALL:@SECLEVEL=0")
    context.minimum_version = minimum
    context.maximum_version = maximum
    context.load_cert_chain(*certificate_files)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def serve():
        while True:
            connection, _address = listener.accept()
            try:
                with context.wrap_socket(connection, server_side=True):
                    pass
            except (ssl.SSLError, OSError):
                pass

    threading.Thread(target=serve, daemon=True).start()
    return listener.getsockname()[1]


def test_the_real_probe_sees_tls10_on_a_server_that_prefers_tls12(certificate_files):
    if _legacy_protocol_context("TLSv1") is None:
        pytest.skip("El OpenSSL local no puede ofrecer TLS 1.0")
    try:
        port = _serve(ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_2, certificate_files)
    except (ValueError, ssl.SSLError):
        pytest.skip("El OpenSSL local no puede servir TLS 1.0")
    probe = TlsProbe(timeout=5)

    assert probe.fetch("127.0.0.1", port).protocol == "TLSv1.2"
    assert probe.fetch_accepts_protocol("127.0.0.1", port, "TLSv1") is True


def test_the_real_probe_reports_a_rejection_on_a_modern_server(certificate_files):
    if _legacy_protocol_context("TLSv1") is None:
        pytest.skip("El OpenSSL local no puede ofrecer TLS 1.0")
    port = _serve(ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3, certificate_files)

    assert TlsProbe(timeout=5).fetch_accepts_protocol("127.0.0.1", port, "TLSv1") is False
