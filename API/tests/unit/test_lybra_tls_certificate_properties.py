"""Propiedades del certificado TLS que el saludo ya descarga: clave, firma y caducidad.

El saludo TLS de Lybra ya recibe el certificado entero, pero sólo miraba si
era autofirmado, si cubría el nombre y si había caducado. Aquí se prueban los
tres avisos que salen de leer tres datos más del mismo certificado: el tamaño
de su clave, el resumen con el que está firmado y cuántos días le quedan. Los
certificados se generan en memoria, sin red.
"""

import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509.oid import NameOID

from src.modules.features.themis.lybra.checks import CheckRuntime, Service, load_checks
from src.modules.features.themis.lybra.fingerprinting.tls import TlsInfo, TlsProbe

pytestmark = pytest.mark.unit

_HTTPS = Service(443, "tcp", "https", "", "", None)
_TLS_CHECKS = [check for check in load_checks() if check.type == "tls"]


def _certificate_der(key, signature_hash=hashes.SHA256(), days_valid=365):
    """Un certificado autofirmado para ``key``, firmado con ``signature_hash``, en DER."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "servidor.example.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .sign(key, signature_hash)
    )
    return certificate.public_bytes(serialization.Encoding.DER)


def _parse(der):
    # pylint: disable=protected-access
    return TlsProbe._parse_cert(der, "TLSv1.3", "TLS_AES_256_GCM_SHA384")


def _fired(info):
    findings = CheckRuntime(_TLS_CHECKS, lambda *a: None,
                            tls_fetch=lambda host, port, starttls=None: info).run("h", [_HTTPS])
    return {finding["check_id"].split(":")[1].split("@")[0] for finding in findings}


# ======================================================== lo que se lee


def test_the_key_type_size_and_signature_hash_are_read_from_the_certificate():
    info = _parse(_certificate_der(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    assert (info.public_key_type, info.public_key_bits, info.signature_hash) == ("rsa", 2048, "sha256")


def test_an_elliptic_curve_key_reports_its_curve_size():
    info = _parse(_certificate_der(ec.generate_private_key(ec.SECP384R1())))
    assert (info.public_key_type, info.public_key_bits) == ("ec", 384)


def test_an_ed25519_certificate_has_no_separate_signature_hash():
    info = _parse(_certificate_der(ed25519.Ed25519PrivateKey.generate(), signature_hash=None))
    assert info.public_key_type == "ed25519"
    assert info.public_key_bits is None and info.signature_hash is None


# ============================================================ los avisos


def test_a_1024_bit_rsa_key_fires_and_a_2048_bit_one_does_not():
    short = _parse(_certificate_der(rsa.generate_private_key(public_exponent=65537, key_size=1024)))
    assert "tls-weak-key" in _fired(short)
    # Señuelo: la clave del tamaño recomendado.
    enough = _parse(_certificate_der(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    assert "tls-weak-key" not in _fired(enough)


def test_a_p256_key_is_not_short():
    info = _parse(_certificate_der(ec.generate_private_key(ec.SECP256R1())))
    assert "tls-weak-key" not in _fired(info)


@pytest.mark.parametrize("signature_hash", ["sha1", "md5"])
def test_an_obsolete_signature_hash_fires(signature_hash):
    # El OpenSSL de hoy ya no firma con SHA-1 ni MD5, así que el certificado no
    # se puede generar aquí: se prueba la regla sobre lo que el parser leería.
    info = TlsInfo(protocol="TLSv1.2", cipher="x", subject_cn="a", issuer_cn="b",
                   self_signed=False, expired=False, days_until_expiry=300,
                   public_key_type="rsa", public_key_bits=2048, signature_hash=signature_hash)
    assert "tls-weak-signature" in _fired(info)


def test_a_sha256_signature_does_not_fire():
    """Señuelo: un certificado real firmado con un resumen moderno."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert "tls-weak-signature" not in _fired(_parse(_certificate_der(key, hashes.SHA256())))


def test_a_certificate_close_to_expiry_fires_and_a_distant_one_does_not():
    key = ec.generate_private_key(ec.SECP256R1())
    assert "tls-expiring-soon" in _fired(_parse(_certificate_der(key, days_valid=10)))
    # Señuelo: una caducidad lejana.
    assert "tls-expiring-soon" not in _fired(_parse(_certificate_der(key, days_valid=200)))


def test_an_expired_certificate_is_expired_not_expiring():
    """Un certificado ya caducado tiene su propio aviso, más grave; no los dos."""
    info = TlsInfo(protocol="TLSv1.2", cipher="x", subject_cn="a", issuer_cn="b",
                   self_signed=False, expired=True, days_until_expiry=-3)
    fired = _fired(info)
    assert "tls-expired-cert" in fired and "tls-expiring-soon" not in fired


def test_an_unreadable_key_or_signature_asserts_nothing():
    """Sin el dato no se afirma que sea débil."""
    info = TlsInfo(protocol="TLSv1.2", cipher="x", subject_cn="a", issuer_cn="b",
                   self_signed=False, expired=False, days_until_expiry=300)
    fired = _fired(info)
    assert "tls-weak-key" not in fired and "tls-weak-signature" not in fired


def test_the_three_checks_are_tls_checks_in_safe_mode():
    by_id = {check.id: check for check in _TLS_CHECKS}
    for check_id, rule in (("tls-weak-key", "weak_key"), ("tls-weak-signature", "weak_signature"),
                           ("tls-expiring-soon", "expiring_soon")):
        assert by_id[check_id].tls_rule == rule
        assert by_id[check_id].mode == "safe"
