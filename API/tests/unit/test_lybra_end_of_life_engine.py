"""El motor emite un hallazgo cuando la rama resuelta está fuera de soporte (L114).

Usa un producto real del catálogo empaquetado (nginx) en vez de uno sintético,
para que la prueba sea honesta sobre lo que de verdad se commitea — pero fija
``eol_as_of`` para que el resultado no dependa de qué día se ejecuten los
tests: nginx 1.18 salió de soporte el 2021-04-20, así que un ``as_of`` anterior
a esa fecha no debe disparar nada y uno posterior sí.
"""

from datetime import date

import pytest

from src.modules.features.themis.lybra import LybraEngine, Service

pytestmark = pytest.mark.unit

_NGINX_1_18 = Service(port=80, protocol="tcp", name="http", product="nginx", version="1.18.0")
_NGINX_1_18_BEFORE_EOL = date(2020, 6, 1)     # 1.18 ya había salido, aún con soporte
_NGINX_1_18_AFTER_EOL = date(2026, 1, 1)


def test_a_branch_past_its_eol_date_gets_an_end_of_life_finding():
    engine = LybraEngine(eol_as_of=_NGINX_1_18_AFTER_EOL)
    findings = engine.analyze([_NGINX_1_18])

    eol = [f for f in findings if f["check_id"] == "lybra:end-of-life@1"]
    assert len(eol) == 1
    assert eol[0]["category"] == "outdated_software"
    assert eol[0]["severity"] == "MEDIUM"
    assert eol[0]["cve_ids"] == []
    assert eol[0]["confirmed"] is False
    assert "2021-04-20" in eol[0]["title"]
    assert "nginx 1.18.0" in eol[0]["title"]


def test_a_branch_still_supported_at_that_date_gets_nothing():
    engine = LybraEngine(eol_as_of=_NGINX_1_18_BEFORE_EOL)
    findings = engine.analyze([_NGINX_1_18])

    assert not [f for f in findings if f["check_id"] == "lybra:end-of-life@1"]
    # La informativa de siempre sigue ahí: el fin de soporte no sustituye nada.
    assert [f["category"] for f in findings] == ["open_port"]


def test_it_fires_even_without_a_cve_lookup_wired():
    """El catálogo de fin de soporte es un feed puro, no depende de la KB."""
    engine = LybraEngine(eol_as_of=_NGINX_1_18_AFTER_EOL)
    findings = engine.analyze([_NGINX_1_18])

    assert {f["category"] for f in findings} == {"open_port", "outdated_software"}


def test_a_product_outside_the_eol_catalog_gets_nothing_extra():
    """Apache httpd no tiene fecha formal de fin de soporte publicada: el
    catálogo lo deja fuera a propósito, y el motor no debe inventar nada."""
    service = Service(port=80, protocol="tcp", name="http", product="Apache httpd", version="2.4.10")
    engine = LybraEngine(eol_as_of=date(2030, 1, 1))
    findings = engine.analyze([service])

    assert [f["category"] for f in findings] == ["open_port"]


def test_an_inventory_origin_end_of_life_finding_is_confirmed_with_high_qod():
    from src.modules.features.themis.lybra import QOD_INVENTORY_MATCH

    service = Service(port=None, protocol="", name="", product="nginx",
                      version="1.18.0", origin="inventory")
    engine = LybraEngine(eol_as_of=_NGINX_1_18_AFTER_EOL)
    findings = engine.analyze([service])

    eol = next(f for f in findings if f["check_id"] == "lybra:end-of-life@1")
    assert eol["confirmed"] is True and eol["qod"] == QOD_INVENTORY_MATCH


def test_as_of_defaults_to_the_real_clock_when_omitted():
    """Sin inyectar nada, el motor usa la fecha de hoy: una rama realmente
    vieja debe seguir disparando sea cuando sea que esto se ejecute."""
    engine = LybraEngine()
    findings = engine.analyze([_NGINX_1_18])
    assert any(f["check_id"] == "lybra:end-of-life@1" for f in findings)
