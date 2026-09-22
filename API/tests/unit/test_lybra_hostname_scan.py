"""Escanear por nombre de host: nombre en SNI y en Host, conexiones a la IP validada.

Un servidor con varias webs en la misma IP decide cuál responde por el nombre
que el cliente dice en el saludo TLS (SNI) y en la cabecera ``Host``. Lybra sólo
aceptaba IPs, así que auditaba el sitio por defecto del servidor: en el
contraste de campo, un certificado autofirmado y caducado y dos cabeceras
«ausentes» que el sitio real sí enviaba.
"""

import socket

import pytest

from src.modules.features.themis.exceptions import IPValidationError, PrivateIPRequested
from src.modules.features.themis.lybra import pinned_resolution
from src.modules.features.themis.lybra.fingerprinting.tls import TlsInfo
from src.modules.features.themis.services import parsing

pytestmark = pytest.mark.unit


def _fake_dns(table):
    """Un ``getaddrinfo`` que responde con ``table`` y falla con lo demás."""
    def getaddrinfo(host, *_args, **_kwargs):
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)) for address in table[host]]
        if host.replace(".", "").isdigit():
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 0))]
        raise socket.gaierror("no resuelve")
    return getaddrinfo


# ================================================================== validación


@pytest.mark.parametrize("target,expected", [
    ("ejemplo.test", True),
    ("www.ejemplo.co.uk", True),
    ("203.0.113.9", False),
    ("203.0.113.0/24", False),
    ("203.0.113.1,203.0.113.2", False),
    ("localhost", False),          # sin punto: un nombre de la red local
    ("a..b.test", False),
])
def test_is_hostname(target, expected):
    assert parsing.is_hostname(target) is expected


def test_a_public_name_resolves_to_its_first_ipv4(monkeypatch):
    monkeypatch.setattr(parsing.socket, "getaddrinfo", _fake_dns({"ejemplo.test": ["8.8.8.8"]}))
    assert parsing.resolve_public_address("ejemplo.test") == "8.8.8.8"


def test_a_name_with_any_private_address_is_rejected(monkeypatch):
    monkeypatch.setattr(parsing.socket, "getaddrinfo",
                        _fake_dns({"ejemplo.test": ["8.8.8.8", "10.0.0.5"]}))
    with pytest.raises(PrivateIPRequested):
        parsing.resolve_public_address("ejemplo.test")


def test_a_name_that_does_not_resolve_is_rejected(monkeypatch):
    monkeypatch.setattr(parsing.socket, "getaddrinfo", _fake_dns({}))
    with pytest.raises(IPValidationError):
        parsing.resolve_public_address("ejemplo.test")


# ====================================================================== el pin


def test_a_pinned_name_resolves_only_to_the_validated_address(monkeypatch):
    """Aunque el DNS cambie de respuesta a mitad (rebinding), el escaneo sigue en la IP validada."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns({"ejemplo.test": ["10.0.0.5"]}))

    with pinned_resolution("ejemplo.test", "203.0.113.10"):
        pinned = socket.getaddrinfo("ejemplo.test", 443)[0][4][0]
        other = socket.getaddrinfo("198.51.100.1", 80)[0][4][0]

    assert pinned == "203.0.113.10"
    assert other == "198.51.100.1"
    assert socket.getaddrinfo("ejemplo.test", 443)[0][4][0] == "10.0.0.5"   # soltado


def test_two_scans_of_the_same_name_share_the_pin(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns({"ejemplo.test": ["10.0.0.5"]}))

    with pinned_resolution("ejemplo.test", "203.0.113.10"):
        with pinned_resolution("EJEMPLO.test.", "203.0.113.10"):
            pass
        still_pinned = socket.getaddrinfo("ejemplo.test", 443)[0][4][0]

    assert still_pinned == "203.0.113.10"


# ============================================================== el certificado


def _tls(names, requested):
    return TlsInfo(protocol="TLSv1.3", cipher=None, subject_cn=None, issuer_cn=None,
                   self_signed=False, expired=False, days_until_expiry=90,
                   names=names, requested_name=requested)


@pytest.mark.parametrize("names,requested,mismatch", [
    (("ejemplo.test",), "ejemplo.test", False),
    (("*.ejemplo.test", "ejemplo.test"), "www.ejemplo.test", False),
    (("*.ejemplo.test",), "a.b.ejemplo.test", True),     # el comodín cubre un solo nivel
    (("plesk.proveedor.test",), "ejemplo.test", True),   # el sitio por defecto
    (("plesk.proveedor.test",), None, False),            # por IP: no hay con qué comparar
])
def test_the_certificate_is_compared_with_the_requested_name(names, requested, mismatch):
    assert _tls(names, requested).is_name_mismatch is mismatch
