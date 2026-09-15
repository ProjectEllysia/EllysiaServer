"""``CheckPlanner``: qué servicios de un re-escaneo pueden saltarse el fingerprint."""

import pytest

from src.modules.features.themis.lybra.planner import CheckPlanner, KnownService
from src.modules.features.themis.lybra.engine import Service

pytestmark = pytest.mark.unit


def _service(port=80, protocol="tcp", product="", version="", cpe=None):
    return Service(port=port, protocol=protocol, name="http", product=product, version=version, cpe=cpe)


def test_a_new_service_always_needs_fingerprinting():
    planner = CheckPlanner(previous_surface={})
    assert planner.needs_fingerprint(_service()) is True


def test_a_service_known_with_product_and_version_skips_fingerprinting():
    previous = {(80, "tcp"): KnownService(product="Apache httpd", version="2.4.49", cpe="cpe:/a:apache:http_server:2.4.49")}
    planner = CheckPlanner(previous_surface=previous)
    assert planner.needs_fingerprint(_service(port=80)) is False


def test_a_service_known_without_a_resolved_version_still_needs_fingerprinting():
    # Puerto visto antes, pero nunca se le pudo sacar versión: no hay nada
    # fiable que reutilizar, así que se sondea igual que a uno nuevo.
    previous = {(80, "tcp"): KnownService(product="", version="", cpe=None)}
    planner = CheckPlanner(previous_surface=previous)
    assert planner.needs_fingerprint(_service(port=80)) is True


def test_a_portless_inventory_service_always_needs_fingerprinting():
    # No hay (port, protocol) que buscar en el surface tracking, así que no
    # hay nada que reutilizar — coherente con que tampoco hay nada que sondear.
    previous = {(80, "tcp"): KnownService(product="Apache httpd", version="2.4.49", cpe=None)}
    planner = CheckPlanner(previous_surface=previous)
    assert planner.needs_fingerprint(_service(port=None)) is True


def test_a_different_protocol_on_the_same_port_is_not_reused():
    previous = {(80, "tcp"): KnownService(product="Apache httpd", version="2.4.49", cpe=None)}
    planner = CheckPlanner(previous_surface=previous)
    assert planner.needs_fingerprint(_service(port=80, protocol="udp")) is True


def test_apply_cached_identity_fills_in_the_known_product_version_and_cpe():
    previous = {(80, "tcp"): KnownService(product="Apache httpd", version="2.4.49", cpe="cpe:/a:apache:http_server:2.4.49")}
    planner = CheckPlanner(previous_surface=previous)
    result = planner.apply_cached_identity(_service(port=80))
    assert result.product == "Apache httpd"
    assert result.version == "2.4.49"
    assert result.cpe == "cpe:/a:apache:http_server:2.4.49"
    # El puerto/protocolo no cambian: sólo se rellena la identidad.
    assert result.port == 80


def test_apply_cached_identity_on_an_unknown_service_returns_it_unchanged():
    planner = CheckPlanner(previous_surface={})
    service = _service(port=80)
    assert planner.apply_cached_identity(service) == service


def test_partition_splits_in_the_original_relative_order():
    previous = {(80, "tcp"): KnownService(product="Apache httpd", version="2.4.49", cpe=None)}
    planner = CheckPlanner(previous_surface=previous)
    known = _service(port=80)
    new_ssh = _service(port=22, product="")
    new_ftp = _service(port=21, product="")

    to_probe, to_reuse = planner.partition([new_ssh, known, new_ftp])

    assert to_probe == [new_ssh, new_ftp]
    assert to_reuse == [known]
