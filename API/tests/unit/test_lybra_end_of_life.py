"""El catálogo de fin de soporte del fabricante (L114).

Módulo puro: sin red, sin ORM. Las pruebas usan tanto un catálogo sintético
pequeño (para los bordes: producto desconocido, rama sin fecha, versión que no
encaja en ninguna rama) como el catálogo real empaquetado (para comprobar que
la instantánea que se commitea tiene forma y sentido).
"""

from datetime import date

import pytest

from src.modules.features.themis.lybra.end_of_life import (
    check_end_of_life,
    cycle_for_version,
    load_eol_catalog,
    validate_eol_catalog,
)

pytestmark = pytest.mark.unit

_CATALOG = {
    "nginx:nginx": [
        {"cycle": "1.29", "eol": "2026-05-13"},
        {"cycle": "1.28", "eol": "2026-04-14"},
        {"cycle": "1.27", "eol": "2025-06-24"},
    ],
    "example:rolling": [
        {"cycle": "2024", "eol": False},
    ],
}


# ======================================================================
# cycle_for_version
# ======================================================================

@pytest.mark.parametrize("version, expected", [
    ("1.29.8", "1.29"),         # coincide por el prefijo de dos componentes
    ("1.29", "1.29"),           # coincide exacto
    ("1.27.0", "1.27"),
])
def test_a_version_is_encajada_en_la_rama_mas_especifica(version, expected):
    assert cycle_for_version(version, {"1.29", "1.28", "1.27"}) == expected


def test_a_version_outside_every_known_cycle_matches_nothing():
    assert cycle_for_version("2.0.0", {"1.29", "1.28"}) is None


def test_an_empty_cycle_list_matches_nothing():
    assert cycle_for_version("1.29.8", set()) is None


# ======================================================================
# check_end_of_life
# ======================================================================

def test_a_branch_already_past_its_eol_date_is_reported_as_past():
    status = check_end_of_life("nginx", "nginx", "1.27.5", as_of=date(2026, 1, 1), catalog=_CATALOG)
    assert status is not None and status.cycle == "1.27" and status.is_past


def test_a_branch_not_yet_at_its_eol_date_is_reported_as_not_past():
    status = check_end_of_life("nginx", "nginx", "1.29.8", as_of=date(2026, 1, 1), catalog=_CATALOG)
    assert status is not None and status.cycle == "1.29" and not status.is_past


def test_the_eol_date_itself_counts_as_already_past():
    """Señuelo del borde: el día exacto de la fecha ya cuenta como fuera de soporte."""
    status = check_end_of_life("nginx", "nginx", "1.27.5", as_of=date(2025, 6, 24), catalog=_CATALOG)
    assert status.is_past


def test_the_day_before_the_eol_date_does_not_count():
    status = check_end_of_life("nginx", "nginx", "1.27.5", as_of=date(2025, 6, 23), catalog=_CATALOG)
    assert not status.is_past


def test_an_unknown_product_yields_nothing():
    assert check_end_of_life("acme", "widget", "1.0", catalog=_CATALOG) is None


def test_a_version_that_matches_no_known_cycle_yields_nothing():
    assert check_end_of_life("nginx", "nginx", "9.9.9", catalog=_CATALOG) is None


def test_a_branch_with_no_recorded_eol_date_yields_nothing():
    """Señuelo: desarrollo continuo (``eol: false``) no es un hallazgo."""
    assert check_end_of_life("example", "rolling", "2024.1", catalog=_CATALOG) is None


def test_as_of_defaults_to_today():
    # 1.27 lleva fuera de soporte desde 2025; hoy, sea cuando sea esta prueba,
    # ya ha pasado.
    status = check_end_of_life("nginx", "nginx", "1.27.5", catalog=_CATALOG)
    assert status.is_past


# ======================================================================
# El catálogo empaquetado de verdad
# ======================================================================

def test_the_bundled_catalog_is_well_formed():
    assert validate_eol_catalog() == []


def test_the_bundled_catalog_covers_several_products():
    catalog = load_eol_catalog()
    assert {"nginx:nginx", "postgresql:postgresql", "redis:redis",
            "mongodb:mongodb"} <= set(catalog)


def test_an_old_real_branch_is_long_past_its_eol():
    """nginx 1.18 salió en 2020 y quedó sin soporte en 2021: a estas alturas,
    sea cuando sea "hoy", ya pasó."""
    status = check_end_of_life("nginx", "nginx", "1.18.0")
    assert status is not None and status.is_past


def test_every_cycle_in_the_bundled_catalog_resolves_to_a_real_date_or_rolling():
    for key, branches in load_eol_catalog().items():
        for branch in branches:
            assert "cycle" in branch and "eol" in branch, key
