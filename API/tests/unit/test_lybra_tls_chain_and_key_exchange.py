"""Cadena de certificados TLS incompleta y grupo Diffie-Hellman débil, con el lector en crudo.

Sobre el lector de saludo TLS en crudo (L104) se leen dos hechos que el
módulo basado en la librería de Python nunca ha mirado: si el servidor manda
el certificado intermedio, y qué tan débil es el grupo Diffie-Hellman que
elige. Los dos son hallazgos reales sin ninguna comprobación hasta ahora.
"""

import datetime
import struct

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.modules.features.themis.lybra.checks import ScriptContext
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.tls_hello import (
    HANDSHAKE_CERTIFICATE,
    HANDSHAKE_SERVER_KEY_EXCHANGE,
    ServerFlight,
    ServerHello,
    parse_certificate_message,
    parse_dhe_server_key_exchange,
)
from src.modules.features.themis.lybra.script_checks import (
    TlsIncompleteCertificateChainPlugin,
    TlsWeakKeyExchangeGroupPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_HTTPS = Service(port=443, protocol="tcp", name="https")
_FTP = Service(port=21, protocol="tcp", name="ftp")


class _FakeProbe:
    """Sonda que contesta el vuelo que se le configure, y registra cómo se la llamó."""

    def __init__(self, flight):
        self.flight = flight
        self.calls = []

    def query(self, host, port, versions=(), cipher_suites=None, server_name=None):
        self.calls.append((host, port, versions, cipher_suites, server_name))
        return self.flight


def _certificate_der(subject_cn: str, issuer_cn: str) -> bytes:
    """Un certificado DER con el sujeto y el emisor pedidos, sin verificar la firma."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.DER)


def _certificate_message(certificates) -> bytes:
    """El cuerpo de un mensaje ``Certificate`` (RFC 5246 §7.4.2) con esos DER."""
    entries = b"".join(len(der).to_bytes(3, "big") + der for der in certificates)
    return len(entries).to_bytes(3, "big") + entries


def _server_key_exchange(dh_p_bits: int) -> bytes:
    """El cuerpo de un ``ServerKeyExchange`` DHE con un ``dh_p`` del tamaño pedido."""
    dh_p = b"\xff" * (dh_p_bits // 8)
    dh_g = b"\x02"
    dh_ys = b"\xab" * 16
    signature = b"firma-de-prueba-irrelevante"
    return (
        struct.pack("!H", len(dh_p)) + dh_p
        + struct.pack("!H", len(dh_g)) + dh_g
        + struct.pack("!H", len(dh_ys)) + dh_ys
        + signature
    )


def _flight(messages=(), server_hello=None) -> ServerFlight:
    return ServerFlight(server_hello=server_hello, messages=tuple(messages))


# ============================================================ parseo del mensaje Certificate


def test_a_single_certificate_round_trips():
    der = _certificate_der("leaf.test", "Fake CA")

    assert parse_certificate_message(_certificate_message([der])) == [der]


def test_a_two_certificate_chain_round_trips_in_order():
    leaf = _certificate_der("leaf.test", "Intermediate CA")
    intermediate = _certificate_der("Intermediate CA", "Root CA")

    assert parse_certificate_message(_certificate_message([leaf, intermediate])) == [leaf, intermediate]


def test_a_missing_certificate_message_is_an_empty_list():
    assert parse_certificate_message(None) == []


def test_a_truncated_certificate_message_stops_at_what_arrived():
    der = _certificate_der("leaf.test", "Fake CA")
    body = _certificate_message([der])

    assert parse_certificate_message(body[:-5]) == []


# ============================================================ parseo del ServerKeyExchange DHE


def test_the_dh_modulus_size_is_read_in_bits():
    assert parse_dhe_server_key_exchange(_server_key_exchange(2048)) == 2048
    assert parse_dhe_server_key_exchange(_server_key_exchange(1024)) == 1024


def test_a_missing_server_key_exchange_is_none():
    assert parse_dhe_server_key_exchange(None) is None


def test_a_truncated_server_key_exchange_is_none():
    assert parse_dhe_server_key_exchange(b"\x00\x10") is None


# ============================================================ cadena de certificados incompleta


def test_a_server_with_only_the_leaf_certificate_fires():
    """El criterio de cierre: sin el intermedio."""
    leaf = _certificate_der("leaf.test", "Intermediate CA")
    flight = _flight([(HANDSHAKE_CERTIFICATE, _certificate_message([leaf]))])
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsIncompleteCertificateChainPlugin(probe=probe).run(context) is True
    assert context.evidence == {"chainLength": 1}


def test_a_server_with_the_full_chain_does_not_fire():
    """Señuelo: la misma hoja, con su intermedio, no dispara."""
    leaf = _certificate_der("leaf.test", "Intermediate CA")
    intermediate = _certificate_der("Intermediate CA", "Root CA")
    flight = _flight([(HANDSHAKE_CERTIFICATE, _certificate_message([leaf, intermediate]))])
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsIncompleteCertificateChainPlugin(probe=probe).run(context) is False


def test_a_self_signed_leaf_alone_does_not_fire_this_check():
    """Un autofirmado no le falta nada que completar; lo cubre otro check."""
    leaf = _certificate_der("self-signed.test", "self-signed.test")
    flight = _flight([(HANDSHAKE_CERTIFICATE, _certificate_message([leaf]))])
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsIncompleteCertificateChainPlugin(probe=probe).run(context) is False


def test_no_certificate_message_at_all_does_not_fire():
    probe = _FakeProbe(_flight())
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsIncompleteCertificateChainPlugin(probe=probe).run(context) is False


def test_an_unreachable_target_does_not_fire():
    probe = _FakeProbe(None)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsIncompleteCertificateChainPlugin(probe=probe).run(context) is False


def test_only_immediate_tls_services_apply():
    """STARTTLS queda fuera a propósito: el lector en crudo aún no lo habla."""
    plugin = TlsIncompleteCertificateChainPlugin()

    assert plugin.applies(_HTTPS) is True
    assert plugin.applies(_FTP) is False


# ============================================================ grupo Diffie-Hellman débil


def test_a_weak_dh_group_fires():
    """El criterio de cierre: grupo débil."""
    hello = ServerHello(version=0x0303, cipher_suite=0x0033)   # DHE-RSA-AES128-SHA
    flight = _flight(
        [(HANDSHAKE_SERVER_KEY_EXCHANGE, _server_key_exchange(1024))], server_hello=hello)
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsWeakKeyExchangeGroupPlugin(probe=probe).run(context) is True
    assert context.evidence == {"groupBits": 1024}


def test_a_recommended_dh_group_does_not_fire():
    """Señuelo: el mismo servidor, con un grupo recomendado, no dispara."""
    hello = ServerHello(version=0x0303, cipher_suite=0x0033)
    flight = _flight(
        [(HANDSHAKE_SERVER_KEY_EXCHANGE, _server_key_exchange(2048))], server_hello=hello)
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsWeakKeyExchangeGroupPlugin(probe=probe).run(context) is False


def test_a_server_that_does_not_offer_dhe_does_not_fire():
    """Sólo ofrece ECDHE: nada que este check pueda medir."""
    hello = ServerHello(version=0x0303, cipher_suite=0xC02F)   # ECDHE-RSA-AES128-GCM-SHA256
    flight = _flight(server_hello=hello)
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsWeakKeyExchangeGroupPlugin(probe=probe).run(context) is False


def test_an_unreachable_target_does_not_fire_the_key_exchange_check():
    probe = _FakeProbe(None)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    assert TlsWeakKeyExchangeGroupPlugin(probe=probe).run(context) is False


def test_the_probe_is_asked_only_for_dhe_cipher_suites():
    hello = ServerHello(version=0x0303, cipher_suite=0x0033)
    flight = _flight(
        [(HANDSHAKE_SERVER_KEY_EXCHANGE, _server_key_exchange(2048))], server_hello=hello)
    probe = _FakeProbe(flight)
    context = ScriptContext(target="203.0.113.10", service=_HTTPS)

    TlsWeakKeyExchangeGroupPlugin(probe=probe).run(context)

    _host, _port, _versions, cipher_suites, _server_name = probe.calls[0]
    assert cipher_suites and all(suite not in (0xC02F, 0xC02B) for suite in cipher_suites)


# ============================================================ el registro


def test_the_two_plugins_are_registered():
    plugins = default_script_plugins()

    assert "tls-incomplete-certificate-chain" in plugins
    assert "tls-weak-key-exchange-group" in plugins
