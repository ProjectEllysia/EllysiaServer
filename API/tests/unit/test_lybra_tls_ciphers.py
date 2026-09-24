"""Qué familias de cifrado TLS 1.2 acepta un servidor, más allá de la que elige.

Un cliente moderno elige el mejor conjunto que el servidor acepta, así que la
conexión normal casi nunca enseña los débiles. Estos tests levantan un servidor
TLS de verdad en ``127.0.0.1`` (el conftest permite el bucle local) restringido
a un único conjunto, y comprueban que la sonda sólo lo da por aceptado cuando
de verdad lo acepta.
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

from src.modules.features.themis.lybra.checks import ScriptContext
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.tls import TlsProbe
from src.modules.features.themis.lybra.script_checks import (
    TlsWeakCipherFamilyPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_NO_FORWARD_SECRECY = "kRSA:!aNULL:!eNULL"


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
    folder = tmp_path_factory.mktemp("tls")
    certificate_path, key_path = folder / "cert.pem", folder / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return str(certificate_path), str(key_path)


def _serve_only(cipher: str, certificate_files) -> int:
    """Levanta un servidor TLS 1.2 que sólo acepta ``cipher`` y devuelve su puerto."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(cipher)
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


def test_a_server_that_accepts_rsa_key_exchange_is_caught(certificate_files):
    port = _serve_only("AES128-GCM-SHA256", certificate_files)

    accepted = TlsProbe(timeout=5).fetch_accepted_tls12_cipher("127.0.0.1", port, _NO_FORWARD_SECRECY)

    assert accepted == "AES128-GCM-SHA256"


def test_a_server_with_only_forward_secret_ciphers_is_not_flagged(certificate_files):
    port = _serve_only("ECDHE-RSA-AES128-GCM-SHA256", certificate_files)

    accepted = TlsProbe(timeout=5).fetch_accepted_tls12_cipher("127.0.0.1", port, _NO_FORWARD_SECRECY)

    assert accepted == ""


def test_an_unreachable_service_is_unknown_not_clean():
    probe = TlsProbe(timeout=1, connect=lambda *_args: (_ for _ in ()).throw(OSError("refused")))
    assert probe.fetch_accepted_tls12_cipher("127.0.0.1", 443, _NO_FORWARD_SECRECY) is None


class _FakeProbe:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def fetch_accepted_tls12_cipher(self, host, port, ciphers):
        self.calls.append((host, port, ciphers))
        return self.answer


def test_the_plugin_fires_only_on_an_accepted_cipher_and_keeps_it_as_evidence():
    https = Service(port=443, protocol="tcp", name="https")
    accepting = TlsWeakCipherFamilyPlugin("tls-no-forward-secrecy", probe=_FakeProbe("AES128-GCM-SHA256"))
    context = ScriptContext(target="203.0.113.10", service=https)

    assert accepting.applies(https) is True
    assert accepting.applies(Service(port=22, protocol="tcp", name="ssh")) is False
    assert accepting.run(context) is True
    assert context.evidence == {"acceptedCipher": "AES128-GCM-SHA256"}

    for answer in ("", None):
        plugin = TlsWeakCipherFamilyPlugin("tls-no-forward-secrecy", probe=_FakeProbe(answer))
        assert plugin.run(ScriptContext(target="203.0.113.10", service=https)) is False


def test_both_families_are_registered():
    plugins = default_script_plugins()
    assert {"tls-no-forward-secrecy", "tls-cbc-ciphers"} <= set(plugins)
