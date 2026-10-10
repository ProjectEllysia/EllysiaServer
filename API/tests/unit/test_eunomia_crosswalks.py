"""Correspondencias entre marcos: válidas en el catálogo y solo sugeridas entre marcos adoptados."""

import copy
import json

import pytest

from src.modules.features.eunomia.services.catalog import CATALOG_ROOT, CatalogFormatError
from src.modules.features.eunomia.services.crosswalks import (
    load_crosswalks,
    parse_crosswalk,
    suggestions,
)

pytestmark = pytest.mark.unit

_ADOPTED = {"nis2": "2022-2555", "ens": "rd-311-2022"}


def test_every_crosswalk_in_the_catalog_is_valid():
    assert len(load_crosswalks()) >= 2


def test_a_control_sees_the_controls_of_the_other_adopted_frameworks():
    found = suggestions("nis2", "2022-2555", "RE.11.1", _ADOPTED)

    assert [(s.framework, s.identifier, s.coverage) for s in found] == [("ens", "op.acc.2", "full")]


def test_the_relation_can_be_read_from_the_other_side():
    found = suggestions("ens", "rd-311-2022", "op.acc.2", _ADOPTED | {"nis2": "2022-2555"})

    assert ("nis2", "RE.11.1", "full") in [(s.framework, s.identifier, s.coverage) for s in found]


def test_only_adopted_frameworks_are_suggested():
    assert suggestions("nis2", "2022-2555", "RE.11.1", {"nis2": "2022-2555"}) == []


def test_a_framework_adopted_in_another_version_is_not_suggested():
    assert suggestions("nis2", "2022-2555", "RE.11.1", {"nis2": "2022-2555", "ens": "otra"}) == []


def test_a_partial_coverage_is_reported_as_partial():
    found = suggestions("nis2", "2022-2555", "RE.3.2", _ADOPTED)

    assert {s.identifier: s.coverage for s in found} == {"op.exp.8": "full", "op.mon.1": "partial"}


def _document():
    path = next(CATALOG_ROOT.glob("crosswalks/nis2@*__ens@*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["links"][0].update({"from": "no-existe"}), "no existe"),
    (lambda d: d["links"][0].update({"to": "op"}), "no es evaluable"),
    (lambda d: d["links"][0].update({"coverage": "casi"}), "cobertura"),
    (lambda d: d["b"].update({"version": "9"}), "no existe"),
])
def test_an_invalid_crosswalk_is_rejected(mutate, message):
    document = copy.deepcopy(_document())
    mutate(document)

    with pytest.raises(CatalogFormatError, match=message):
        parse_crosswalk(document)
