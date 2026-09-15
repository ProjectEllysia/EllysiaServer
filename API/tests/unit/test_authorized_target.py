"""Tests unitarios de la normalización del registro de objetivos autorizados."""

import pytest

from src.modules.features.themis.managers.authorized_target import AuthorizedTargetManager
from src.modules.features.themis.exceptions import IPValidationError

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
