"""El catálogo de marcos: formato, validación e inmutabilidad de lo publicado."""

import copy
import json
from pathlib import Path

import pytest

from src.modules.features.eunomia.services import catalog as catalog_service
from src.modules.features.eunomia.services.catalog import (
    CATALOG_ROOT,
    CatalogFormatError,
    file_digest,
    load_index,
    load_version,
    lock_mismatches,
    parse_version,
)

pytestmark = pytest.mark.unit


def _document(**overrides) -> dict:
    document = {
        "key": "demo", "version": "1", "status": "draft", "name": "Marco de prueba",
        "shortName": "Demo", "publishedAt": "2026-01-01",
        "sources": [{"name": "Norma", "url": "https://example.test", "license": "libre", "consultedAt": "2026-10-10"}],
        "nodes": [
            {"identifier": "1", "parent": None, "order": 1, "kind": "group", "title": "Uno"},
            {"identifier": "1.2", "parent": "1", "order": 2, "kind": "requirement", "title": "Dos",
             "description": "Qué pide.", "actions": ["Hacer algo"], "evidence": ["Un documento"]},
            {"identifier": "1.1", "parent": "1", "order": 1, "kind": "requirement", "title": "Primero",
             "description": "Qué pide.", "actions": ["Hacer algo"], "evidence": ["Un documento"]},
            {"identifier": "2", "parent": None, "order": 2, "kind": "requirement", "title": "Hoja raíz"},
        ],
    }
    document.update(overrides)
    return document


# ── formato ────────────────────────────────────────────────────────────────

def test_a_valid_version_is_parsed_with_global_codes():
    version = parse_version(_document())

    assert version.node("demo:1.1").parent == "demo:1"
    assert version.node("demo:2").parent is None


def test_children_come_out_in_catalog_order_not_file_order():
    version = parse_version(_document())

    assert [node.identifier for node in version.children("demo:1")] == ["1.1", "1.2"]
    assert [node.identifier for node in version.walk()] == ["1", "1.1", "1.2", "2"]


def test_leaves_are_assessable_by_default_and_groups_are_not():
    version = parse_version(_document())

    assert [node.identifier for node in version.assessable_nodes()] == ["1.1", "1.2", "2"]


def test_a_group_can_be_declared_assessable():
    document = _document()
    document["nodes"][0]["assessable"] = True

    assert parse_version(document).node("demo:1").is_assessable is True


def test_ancestors_go_from_the_parent_to_the_root():
    document = _document()
    document["nodes"].append({"identifier": "1.1.1", "parent": "1.1", "order": 1, "kind": "requirement", "title": "Hondo"})

    version = parse_version(document)

    assert [node.identifier for node in version.ancestors("demo:1.1.1")] == ["1.1", "1"]
    assert version.ancestors("demo:1") == ()


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["nodes"].append(dict(d["nodes"][0])), "repetido"),
    (lambda d: d["nodes"][1].update(parent="9"), "no existe"),
    (lambda d: d["nodes"][0].update(parent="1.2"), "ciclo"),
    (lambda d: d["nodes"][1].update(kind="otra"), "kind"),
    (lambda d: d["nodes"][1].update(title=""), "title"),
    (lambda d: d.update(sources=[]), "sources"),
    (lambda d: d.update(status="otro"), "status"),
    (lambda d: d["nodes"][1].update(evidence=[""]), "evidence"),
])
def test_a_malformed_version_is_rejected_naming_the_problem(mutate, message):
    document = copy.deepcopy(_document())
    mutate(document)

    with pytest.raises(CatalogFormatError, match=message):
        parse_version(document)


def test_a_published_version_needs_every_assessable_node_to_be_complete():
    document = _document(status="published")

    with pytest.raises(CatalogFormatError, match="necesita descripción"):
        parse_version(document)   # el nodo «2» no tiene descripción ni evidencias


def test_a_draft_may_leave_assessable_nodes_unfinished():
    assert parse_version(_document(status="draft")).node("demo:2").description == ""


# ── el catálogo que viaja con el código ────────────────────────────────────

def _real_versions():
    for framework in load_index()["frameworks"]:
        for item in framework["versions"]:
            yield framework, item


def test_every_version_declared_in_the_index_is_loadable_and_consistent():
    for framework, item in _real_versions():
        version = load_version(framework["key"], item["version"])
        assert version is not None
        assert version.status == item["status"]
        assert version.key == framework["key"]


def test_the_current_version_of_each_framework_is_one_of_its_versions():
    for framework in load_index()["frameworks"]:
        assert framework["current"] in {item["version"] for item in framework["versions"]}


def test_no_version_file_is_missing_from_the_index():
    declared = {
        (framework["key"], f"{item['version']}.json") for framework, item in _real_versions()
    }
    on_disk = {
        (folder.name, path.name)
        for folder in CATALOG_ROOT.iterdir() if folder.is_dir()
        for path in folder.glob("*.json")
    }
    assert on_disk == declared


def test_published_versions_match_the_lock():
    assert lock_mismatches() == []


# ── la inmutabilidad ───────────────────────────────────────────────────────

def _catalog_on_disk(tmp_path: Path, status: str) -> Path:
    document = _document(status=status)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "1.json").write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({"frameworks": [{
        "key": "demo", "name": "Demo", "shortName": "Demo", "current": "1",
        "versions": [{"version": "1", "status": status}],
    }]}), encoding="utf-8")
    return tmp_path


def _complete(document: dict) -> dict:
    document["nodes"][3].update(description="Qué pide.", actions=["Hacer"], evidence=["Doc"])
    return document


def test_a_published_version_without_a_lock_line_is_reported(tmp_path):
    root = _catalog_on_disk(tmp_path, "draft")
    document = _complete(_document(status="published"))
    (root / "demo" / "1.json").write_text(json.dumps(document), encoding="utf-8")
    (root / "index.json").write_text(json.dumps({"frameworks": [{
        "key": "demo", "name": "Demo", "shortName": "Demo", "current": "1",
        "versions": [{"version": "1", "status": "published"}],
    }]}), encoding="utf-8")
    (root / "LOCK.json").write_text("{}", encoding="utf-8")
    catalog_service._load_index.cache_clear()

    assert lock_mismatches(root) == ["demo/1 está publicada y no tiene línea en LOCK.json"]


def test_editing_a_locked_version_is_reported(tmp_path):
    root = _catalog_on_disk(tmp_path, "draft")
    document = _complete(_document(status="published"))
    path = root / "demo" / "1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    (root / "index.json").write_text(json.dumps({"frameworks": [{
        "key": "demo", "name": "Demo", "shortName": "Demo", "current": "1",
        "versions": [{"version": "1", "status": "published"}],
    }]}), encoding="utf-8")
    (root / "LOCK.json").write_text(json.dumps({"demo/1": file_digest(path)}), encoding="utf-8")
    catalog_service._load_index.cache_clear()
    assert lock_mismatches(root) == []

    document["nodes"][1]["title"] = "Renombrado después de publicar"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert lock_mismatches(root) == ["demo/1 está publicada y su contenido ya no coincide con LOCK.json"]


def test_the_digest_does_not_depend_on_line_endings(tmp_path):
    unix, windows = tmp_path / "unix.json", tmp_path / "windows.json"
    unix.write_bytes(b'{\n  "a": 1\n}\n')
    windows.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')

    assert file_digest(unix) == file_digest(windows)


def test_an_unknown_framework_or_version_is_none_and_never_builds_a_path():
    assert load_version("nope", "1") is None
    assert load_version("../../etc", "passwd") is None
