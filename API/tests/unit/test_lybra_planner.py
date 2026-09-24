"""``CheckPlanner``: qué servicios de un re-escaneo pueden saltarse el fingerprint."""

from datetime import datetime, timedelta

import pytest

from src.modules.features.themis.lybra.planner import IDENTIFICATION_REVISION, CheckPlanner, KnownService
from src.modules.features.themis.lybra.engine import Service

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, 0)


def _known(product="Apache httpd", version="2.4.49", cpe=None, age_days=1, revision=IDENTIFICATION_REVISION):
    """Una identidad guardada, sondeada hace ``age_days`` días por la revisión ``revision``."""
    identified_at = None if age_days is None else _NOW - timedelta(days=age_days)
    return KnownService(product=product, version=version, cpe=cpe,
                        identified_at=identified_at, identified_by=revision)


def _planner(previous_surface, max_age_days=7):
    return CheckPlanner(previous_surface=previous_surface, max_age_days=max_age_days, now=_NOW)


def _service(port=80, protocol="tcp", product="", version="", cpe=None):
    return Service(port=port, protocol=protocol, name="http", product=product, version=version, cpe=cpe)


def test_a_new_service_always_needs_fingerprinting():
    planner = _planner({})
    assert planner.needs_fingerprint(_service()) is True


def test_a_service_known_with_product_and_version_skips_fingerprinting():
    previous = {(80, "tcp"): _known(cpe="cpe:/a:apache:http_server:2.4.49")}
    planner = _planner(previous)
    assert planner.needs_fingerprint(_service(port=80)) is False


def test_a_service_known_without_a_resolved_version_still_needs_fingerprinting():
    # Puerto visto antes, pero nunca se le pudo sacar versión: no hay nada
    # fiable que reutilizar, así que se sondea igual que a uno nuevo.
    previous = {(80, "tcp"): _known(product="", version="")}
    planner = _planner(previous)
    assert planner.needs_fingerprint(_service(port=80)) is True


def test_a_portless_inventory_service_always_needs_fingerprinting():
    # No hay (port, protocol) que buscar en el surface tracking, así que no
    # hay nada que reutilizar — coherente con que tampoco hay nada que sondear.
    previous = {(80, "tcp"): _known()}
    planner = _planner(previous)
    assert planner.needs_fingerprint(_service(port=None)) is True


def test_a_different_protocol_on_the_same_port_is_not_reused():
    previous = {(80, "tcp"): _known()}
    planner = _planner(previous)
    assert planner.needs_fingerprint(_service(port=80, protocol="udp")) is True


def test_apply_cached_identity_fills_in_the_known_product_version_and_cpe():
    previous = {(80, "tcp"): _known(cpe="cpe:/a:apache:http_server:2.4.49")}
    planner = _planner(previous)
    result = planner.apply_cached_identity(_service(port=80))
    assert result.product == "Apache httpd"
    assert result.version == "2.4.49"
    assert result.cpe == "cpe:/a:apache:http_server:2.4.49"
    # El puerto/protocolo no cambian: sólo se rellena la identidad.
    assert result.port == 80


def test_apply_cached_identity_on_an_unknown_service_returns_it_unchanged():
    planner = _planner({})
    service = _service(port=80)
    assert planner.apply_cached_identity(service) == service


def test_partition_splits_in_the_original_relative_order():
    previous = {(80, "tcp"): _known()}
    planner = _planner(previous)
    known = _service(port=80)
    new_ssh = _service(port=22, product="")
    new_ftp = _service(port=21, product="")

    to_probe, to_reuse = planner.partition([new_ssh, known, new_ftp])

    assert to_probe == [new_ssh, new_ftp]
    assert to_reuse == [known]


def test_an_identification_older_than_the_limit_is_probed_again():
    # Un servidor actualizado entre dos escaneos anunciaría otra versión; si la
    # identidad guardada no caducara, el motor seguiría con la vieja para siempre.
    previous = {(80, "tcp"): _known(age_days=8)}
    assert _planner(previous, max_age_days=7).needs_fingerprint(_service(port=80)) is True


def test_an_identification_within_the_limit_is_reused():
    previous = {(80, "tcp"): _known(age_days=6)}
    assert _planner(previous, max_age_days=7).needs_fingerprint(_service(port=80)) is False


def test_an_identification_without_a_date_is_probed_again():
    # Las filas anteriores a la caducidad no tienen fecha: no se sabe cuánto
    # llevan ahí, así que no se reutilizan.
    previous = {(80, "tcp"): _known(age_days=None)}
    assert _planner(previous).needs_fingerprint(_service(port=80)) is True


def test_an_identification_from_another_revision_of_the_identifier_is_probed_again():
    # El identificador mejoró (p. ej. ahora lee la revisión de distribución del
    # banner de SSH): lo que sacó la versión anterior no se reutiliza.
    previous = {(22, "tcp"): _known(product="OpenSSH", version="9.6p1", revision="1")}
    assert _planner(previous).needs_fingerprint(_service(port=22)) is True
