"""«Corregido en»: la cota sale de la regla cuyo rango contiene la versión.

Una CVE de regresión declara dos rangos para el mismo producto —donde el fallo
apareció y donde volvió—, y tomar el primero mandaba actualizar a una versión
que no corrige nada.
"""

from types import SimpleNamespace

import pytest

from src.modules.features.themis.services.cve_context import find_fixed_version

pytestmark = pytest.mark.unit


def _match(vendor="openbsd", product="openssh", **bounds):
    """Una regla de aplicabilidad con la forma de ``CpeMatch``."""
    fields = ("exact_version", "version_start_including", "version_start_excluding",
              "version_end_including", "version_end_excluding")
    return SimpleNamespace(vendor=vendor, product=product, **{f: bounds.get(f) for f in fields})


# CVE-2024-6387 (regreSSHion): el fallo de 2006 y su regresión.
_REGRESSHION = SimpleNamespace(cpe_matches=[
    _match(version_end_excluding="4.4p1"),
    _match(version_start_including="8.5p1", version_end_excluding="9.8p1"),
])


@pytest.mark.parametrize("version,expected", [
    ("9.6p1", "9.8p1"),   # dentro de la regresión: la cota es la de la regresión
    ("4.3p2", "4.4p1"),   # dentro del fallo original
    ("9.9p1", None),      # fuera de los dos: no se inventa una cota
])
def test_the_fixed_version_comes_from_the_range_containing_the_version(version, expected):
    cpe = f"cpe:2.3:a:openbsd:openssh:{version}:*:*:*:*:*:*:*"
    assert find_fixed_version(_REGRESSHION, cpe) == expected


def test_without_a_version_in_the_cpe_the_first_bounded_rule_is_used():
    assert find_fixed_version(_REGRESSHION, "cpe:2.3:a:openbsd:openssh:*:*:*:*:*:*:*:*") == "4.4p1"


def test_rules_for_other_products_are_ignored():
    entry = SimpleNamespace(cpe_matches=[
        _match(vendor="apache", product="http_server", version_end_excluding="2.4.60"),
        _match(version_end_including="9.6p1"),
    ])
    assert find_fixed_version(entry, "cpe:2.3:a:openbsd:openssh:9.5p1:*:*:*:*:*:*:*") == "9.6p1"


def test_no_cpe_means_no_fixed_version():
    assert find_fixed_version(_REGRESSHION, None) is None
