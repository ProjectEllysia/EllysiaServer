"""El feed de mapeos de cumplimiento de Lybra y la función que lo consulta.

El feed es un fichero curado a mano: un código de control mal escrito o un
``check_id`` que ya no existe no rompe nada visible, sólo hace que un hallazgo
salga en el informe sin su control. Estos tests convierten esas erratas en un
fallo de CI.
"""

import re

import pytest

from src.modules.features.themis.lybra.checks import CHECK_CATEGORIES, load_checks
from src.modules.features.themis.lybra.compliance import (
    load_compliance_catalog,
    map_finding_compliance,
)

pytestmark = pytest.mark.unit

_TECHNIQUE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")

# Las categorías que el motor emite por su cuenta, sin pasar por el feed de
# checks (ver el comentario de ``CHECK_CATEGORIES``).
_ENGINE_CATEGORIES = ("outdated_software", "open_port", "installed_package", "web_component")

# Eventos puntuales, no riesgos: no afectan a ningún control.
_EVENT_CATEGORIES = ("fingerprint", "surface_change", "scan_integrity", "virtual_host")


@pytest.fixture(scope="module")
def catalog():
    return load_compliance_catalog()


def _all_mappings(catalog):
    yield from catalog.categories.items()
    yield from catalog.checks.items()


def test_every_risk_category_is_mapped(catalog):
    missing = [category for category in (*CHECK_CATEGORIES, *_ENGINE_CATEGORIES)
               if category not in catalog.categories]
    assert not missing, f"Categorías sin mapeo de cumplimiento: {missing}"


def test_event_categories_are_not_mapped(catalog):
    assert not set(_EVENT_CATEGORIES) & set(catalog.categories)


def test_every_category_mapping_declares_both_keys(catalog):
    incomplete = [category for category, mapping in catalog.categories.items()
                  if "mitre" not in mapping or "controls" not in mapping]
    assert not incomplete


def test_every_mapped_check_exists_in_the_checks_feed(catalog):
    known = {check.id for check in load_checks()}
    unknown = sorted(set(catalog.checks) - known)
    assert not unknown, f"check_id del mapeo que no existen en el feed: {unknown}"


def test_every_referenced_control_exists(catalog):
    broken = [(key, code) for key, mapping in _all_mappings(catalog)
              for code in mapping.get("controls", ()) if code not in catalog.controls]
    assert not broken


def test_every_referenced_technique_exists_and_is_well_formed(catalog):
    broken = [(key, identifier) for key, mapping in _all_mappings(catalog)
              for identifier in mapping.get("mitre", ()) if identifier not in catalog.techniques]
    assert not broken
    assert all(_TECHNIQUE_RE.match(identifier) for identifier in catalog.techniques)


def test_every_technique_names_known_tactics(catalog):
    document_tactics = {name for technique in catalog.techniques.values() for name in technique.tactics}
    assert not {name for name in document_tactics if name.startswith("TA")}, (
        "Una técnica cita una táctica que no está en mitre.tactics"
    )


def test_every_parent_exists_in_the_same_framework(catalog):
    for control in catalog.controls.values():
        if control.parent is None:
            continue
        parent = catalog.controls.get(control.parent)
        assert parent is not None, control.code
        assert parent.framework == control.framework


def test_mapping_only_returns_the_requested_frameworks():
    result = map_finding_compliance("tls", "tls-expired-cert", ["ens"])
    assert result.controls
    assert {control.framework for control in result.controls} == {"ens"}
    assert result.techniques


def test_attack_techniques_come_without_any_framework():
    result = map_finding_compliance("outdated_software", None)
    assert [technique.identifier for technique in result.techniques] == ["T1190", "T1210"]
    assert result.techniques[0].tactics == ("Initial Access",)
    assert result.controls == ()


def test_a_check_override_only_replaces_the_keys_it_declares(catalog):
    # phpinfo-exposure sólo afina la técnica: los controles son los de su categoría.
    result = map_finding_compliance("exposed_path", "phpinfo-exposure", ["iso27001", "ens", "nis2"])
    assert [technique.identifier for technique in result.techniques] == ["T1592.002"]
    assert [control.code for control in result.controls] == catalog.categories["exposed_path"]["controls"]


def test_unmapped_findings_yield_nothing():
    result = map_finding_compliance("fingerprint", None, ["ens"])
    assert result.techniques == () and result.controls == ()
