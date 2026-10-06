"""Tests unitarios de la normalización del registro de objetivos autorizados."""

import pytest

from src.modules.features.themis.managers.authorized_target import (
    AuthorizedTargetManager,
    _canonical_target,
    _domain_covers,
)
from src.modules.features.themis.exceptions import InvalidAuthorizedTargetError, IPValidationError

pytestmark = pytest.mark.unit


def test_ipv6_loopback_forms_normalize_to_the_same_target():
    # ``::1`` y su forma expandida son la misma dirección: si la comparación
    # de autorización fuera por cadena en vez de por valor, un objetivo
    # autorizado con una notación se rechazaría al presentarse con la otra.
    compact = AuthorizedTargetManager._normalize("::1")  # pylint: disable=protected-access
    expanded = AuthorizedTargetManager._normalize("0:0:0:0:0:0:0:1")  # pylint: disable=protected-access
    assert compact == expanded


def test_ipv4_cidr_normalizes_to_its_network_address():
    normalized = AuthorizedTargetManager._normalize("192.168.1.42/24")  # pylint: disable=protected-access
    assert normalized == "192.168.1.0/24"


def test_an_invalid_target_raises_ip_validation_error():
    with pytest.raises(IPValidationError):
        AuthorizedTargetManager._normalize("not-an-ip")  # pylint: disable=protected-access


# ------------------------------------------------------ canonización de objetivos


@pytest.mark.parametrize("raw, expected", [
    ("10.0.0.42/24", "10.0.0.0/24"),          # IP/CIDR: dirección de red
    ("Example.COM.", "example.com"),           # dominio: minúsculas, sin punto final
    ("S3:My-Bucket", "s3:my-bucket"),          # recurso cloud: forma canónica
    ("azure:Account1/Container", "azure:account1/container"),
])
def test_canonicalize_accepts_the_three_shapes(raw, expected):
    assert _canonical_target(raw) == expected  # pylint: disable=protected-access


@pytest.mark.parametrize("raw", ["not-an-ip", "single-label", "s3:", "ftp:x"])
def test_canonicalize_rejects_anything_that_is_none_of_the_three(raw):
    with pytest.raises(InvalidAuthorizedTargetError):
        _canonical_target(raw)  # pylint: disable=protected-access


# --------------------------------------------------- cobertura de un dominio


def test_a_domain_covers_itself_and_its_subdomains():
    assert _domain_covers("example.com", "example.com")
    assert _domain_covers("example.com", "dev.example.com")
    assert _domain_covers("example.com", "a.b.example.com")


def test_a_domain_does_not_cover_siblings_or_deceptive_suffixes():
    # Un hermano y un sufijo engañoso son los dos errores clásicos: ``otro.com``
    # no tiene nada que ver, y ``evil-example.com`` no es un subdominio de
    # ``example.com`` porque no termina en ``.example.com``.
    assert not _domain_covers("example.com", "otro.com")
    assert not _domain_covers("example.com", "evil-example.com")
    assert not _domain_covers("example.com", "notexample.com")
