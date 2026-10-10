"""Correspondencias entre versiones: completas, coherentes y consultables."""

import copy

import pytest

from src.modules.features.eunomia.services.catalog import CatalogFormatError, parse_version
from src.modules.features.eunomia.services.version_mappings import (
    RELATION_MERGED,
    RELATION_NEW,
    RELATION_RETIRED,
    RELATION_SPLIT,
    parse_mapping,
)

pytestmark = pytest.mark.unit


def _version(version, identifiers):
    return parse_version({
        "key": "demo", "version": version, "status": "draft", "name": "Demo", "shortName": "Demo",
        "publishedAt": "2026-01-01", "licenseMode": "full_text",
        "sources": [{"name": "n", "url": "u", "license": "l", "consultedAt": "2026-10-10"}],
        "nodes": [{"identifier": i, "parent": None, "order": n, "kind": "requirement", "title": i}
                  for n, i in enumerate(identifiers, 1)],
    })


OLD = _version("1", ["A", "B", "C", "D"])
NEW = _version("2", ["X", "Y", "Z", "W"])

_DOCUMENT = {
    "framework": "demo", "from": "1", "to": "2",
    "mappings": [
        {"from": "A", "to": "X", "relation": "equivalent"},
        {"from": "B", "to": "Y", "relation": "split"},
        {"from": "B", "to": "Z", "relation": "split"},
        {"from": "C", "to": "W", "relation": "merged"},
        {"from": "D", "to": "W", "relation": "merged"},
    ],
}


def test_a_complete_mapping_with_a_split_and_a_merge_is_accepted():
    mapping = parse_mapping(_DOCUMENT, OLD, NEW)

    assert [entry.target for entry in mapping.targets_of("B")] == ["Y", "Z"]
    assert [entry.source for entry in mapping.sources_of("W")] == ["C", "D"]
    assert {entry.relation for entry in mapping.targets_of("B")} == {RELATION_SPLIT}
    assert {entry.relation for entry in mapping.sources_of("W")} == {RELATION_MERGED}


def test_an_incomplete_mapping_is_rejected():
    document = copy.deepcopy(_DOCUMENT)
    document["mappings"].pop(0)   # A deja de aparecer, y X también

    with pytest.raises(CatalogFormatError, match="sin correspondencia"):
        parse_mapping(document, OLD, NEW)


def test_a_retired_control_and_a_new_one_complete_the_picture():
    document = copy.deepcopy(_DOCUMENT)
    document["mappings"] = [
        {"from": "A", "to": "X", "relation": "equivalent"},
        {"from": "B", "to": None, "relation": "retired"},
        {"from": "C", "to": "Y", "relation": "equivalent"},
        {"from": "D", "to": "Z", "relation": "equivalent"},
        {"from": None, "to": "W", "relation": "new"},
    ]

    mapping = parse_mapping(document, OLD, NEW)

    assert mapping.targets_of("B")[0].relation == RELATION_RETIRED
    assert mapping.sources_of("W")[0].relation == RELATION_NEW


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["mappings"][0].update({"from": "Q"}), "no existe"),
    (lambda d: d["mappings"][0].update({"to": "Q"}), "no existe"),
    (lambda d: d["mappings"][0].update({"relation": "otra"}), "relación desconocida"),
    (lambda d: d["mappings"][0].update({"relation": "retired"}), "retired"),
    (lambda d: d.update({"to": "3"}), "cabecera"),
])
def test_an_incoherent_mapping_is_rejected(mutate, message):
    document = copy.deepcopy(_DOCUMENT)
    mutate(document)

    with pytest.raises(CatalogFormatError, match=message):
        parse_mapping(document, OLD, NEW)


# ── el catálogo en disco ──────────────────────────────────────────────────

import json

from src.modules.features.eunomia.services import catalog as catalog_service
from src.modules.features.eunomia.services import version_mappings
from src.modules.features.eunomia.services.catalog import CATALOG_ROOT


def _doc(version, identifiers):
    return {
        "key": "demo", "version": version, "status": "draft", "name": "Demo", "shortName": "Demo",
        "publishedAt": "2026-01-01", "licenseMode": "full_text",
        "sources": [{"name": "n", "url": "u", "license": "l", "consultedAt": "2026-10-10"}],
        "nodes": [{"identifier": i, "parent": None, "order": n, "kind": "requirement", "title": i}
                  for n, i in enumerate(identifiers, 1)],
    }


@pytest.fixture()
def disk_catalog(tmp_path):
    (tmp_path / "demo" / "mappings").mkdir(parents=True)
    for version, ids in (("1", ["A", "B"]), ("2", ["X", "Y"])):
        (tmp_path / "demo" / f"{version}.json").write_text(json.dumps(_doc(version, ids)), encoding="utf-8")
    (tmp_path / "demo" / "mappings" / "1__2.json").write_text(json.dumps({
        "framework": "demo", "from": "1", "to": "2",
        "mappings": [{"from": "A", "to": "X", "relation": "equivalent"},
                     {"from": "B", "to": "Y", "relation": "equivalent"}],
    }), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({"frameworks": [{
        "key": "demo", "name": "Demo", "shortName": "Demo", "current": "2",
        "versions": [{"version": "1", "status": "draft"}, {"version": "2", "status": "draft"}],
    }]}), encoding="utf-8")
    catalog_service._load_index.cache_clear()
    catalog_service._load_version.cache_clear()
    version_mappings._load.cache_clear()
    return tmp_path


def test_a_control_of_an_old_version_is_translated_to_the_adopted_one(disk_catalog):
    translated = version_mappings.translate_control("demo", "A", "1", "2", disk_catalog)

    assert [item.target for item in translated] == ["X"]


def test_translating_inside_the_same_version_is_the_identity(disk_catalog):
    assert version_mappings.translate_control("demo", "A", "2", "2", disk_catalog)[0].target == "A"


def test_a_pair_without_a_mapping_file_translates_to_nothing(disk_catalog):
    assert version_mappings.translate_control("demo", "A", "2", "1", disk_catalog) == []


def test_every_mapping_file_in_the_real_catalog_is_valid_and_complete():
    for path in CATALOG_ROOT.glob("*/mappings/*.json"):
        key = path.parent.parent.name
        origin, destination = path.stem.split("__")
        assert version_mappings.load_mapping(key, origin, destination) is not None, path
