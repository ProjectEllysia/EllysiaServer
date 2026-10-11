"""La API del catálogo de Eunomia: quién la lee y qué devuelve."""

import json

import pytest

from src.modules.features.eunomia.managers import catalog as catalog_manager
from src.modules.features.eunomia.services import catalog as catalog_service
from src.modules.features.eunomia.services import crosswalks as crosswalk_service

pytestmark = pytest.mark.integration

_DOCUMENT = {
    "key": "demo", "version": "1", "status": "draft", "name": "Marco de prueba",
    "shortName": "Demo", "publishedAt": "2026-01-01", "licenseMode": "full_text",
    "sources": [{"name": "Norma", "url": "https://example.test", "license": "libre", "consultedAt": "2026-10-10"}],
    "nodes": [
        {"identifier": "1", "parent": None, "order": 1, "kind": "group", "title": "Uno"},
        {"identifier": "1.1", "parent": "1", "order": 1, "kind": "requirement", "title": "Dos",
         "description": "Qué pide.", "actions": ["Hacer"], "evidence": ["Doc"]},
    ],
}


@pytest.fixture()
def demo_catalog(tmp_path, monkeypatch):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "1.json").write_text(json.dumps(_DOCUMENT), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({"frameworks": [{
        "key": "demo", "name": "Marco de prueba", "shortName": "Demo", "current": "1",
        "versions": [{"version": "1", "status": "draft"}],
    }]}), encoding="utf-8")
    catalog_service._load_index.cache_clear()
    monkeypatch.setattr(catalog_manager, "load_index", lambda: catalog_service.load_index(tmp_path))
    monkeypatch.setattr(catalog_manager, "load_version",
                        lambda key, version: catalog_service.load_version(key, version, tmp_path))


def test_the_catalog_requires_a_session(client):
    assert client.get("/eunomia/frameworks").status_code == 401


def test_the_framework_list_summarises_versions(client, regular_user, auth_headers, demo_catalog):
    body = client.get("/eunomia/frameworks", headers=auth_headers(regular_user)).get_json()

    assert body["frameworks"] == [{
        "key": "demo", "name": "Marco de prueba", "shortName": "Demo", "current": "1",
        "versions": [{"version": "1", "status": "draft"}],
    }]


def test_a_version_comes_back_as_a_nested_tree(client, regular_user, auth_headers, demo_catalog):
    body = client.get("/eunomia/frameworks/demo/1", headers=auth_headers(regular_user)).get_json()

    assert body["status"] == "draft"
    assert [root["code"] for root in body["tree"]] == ["demo:1"]
    child = body["tree"][0]["children"][0]
    assert child["code"] == "demo:1.1"
    assert child["isAssessable"] is True
    assert child["evidence"] == ["Doc"]


def test_an_unknown_version_is_a_404_with_a_message_key(client, regular_user, auth_headers, demo_catalog):
    response = client.get("/eunomia/frameworks/demo/9", headers=auth_headers(regular_user))

    assert response.status_code == 404
    assert response.get_json()["messageKey"] == "entityNotFound.framework"


def _install_crosswalk_catalog(tmp_path, monkeypatch, beta_versions):
    """Dos marcos, ``alfa`` y ``beta``, y un cruce entre sus versiones ``1``.

    ``beta_versions`` son las versiones que tiene ``beta``; la última es la vigente.
    """
    for key, versions in (("alfa", ("1",)), ("beta", beta_versions)):
        (tmp_path / key).mkdir()
        for version in versions:
            document = dict(_DOCUMENT, key=key, version=version, shortName=key.capitalize(), name=f"Marco {key}")
            (tmp_path / key / f"{version}.json").write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "crosswalks").mkdir()
    (tmp_path / "crosswalks" / "alfa@1__beta@1.json").write_text(json.dumps({
        "a": {"framework": "alfa", "version": "1"}, "b": {"framework": "beta", "version": "1"},
        "links": [{"from": "1.1", "to": "1.1", "coverage": "partial"}],
    }), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({"frameworks": [
        {"key": key, "name": f"Marco {key}", "shortName": key.capitalize(), "current": versions[-1],
         "versions": [{"version": version, "status": "draft"} for version in versions]}
        for key, versions in (("alfa", ("1",)), ("beta", beta_versions))
    ]}), encoding="utf-8")
    catalog_service._load_index.cache_clear()
    monkeypatch.setattr(catalog_manager, "load_index", lambda: catalog_service.load_index(tmp_path))
    monkeypatch.setattr(catalog_manager, "load_version",
                        lambda key, version: catalog_service.load_version(key, version, tmp_path))
    monkeypatch.setattr(catalog_manager, "load_crosswalks", lambda: crosswalk_service.load_crosswalks(tmp_path))


def test_the_crosswalk_map_requires_a_session(client):
    assert client.get("/eunomia/crosswalks").status_code == 401


def test_the_crosswalk_map_lists_each_framework_flat_with_its_links(
        client, regular_user, auth_headers, tmp_path, monkeypatch):
    _install_crosswalk_catalog(tmp_path, monkeypatch, ("1",))

    body = client.get("/eunomia/crosswalks", headers=auth_headers(regular_user)).get_json()

    assert [framework["key"] for framework in body["frameworks"]] == ["alfa", "beta"]
    assert body["frameworks"][0] == {
        "key": "alfa", "shortName": "Alfa", "name": "Marco alfa", "version": "1",
        "controls": [
            {"identifier": "1", "title": "Uno", "kind": "group", "isAssessable": False, "depth": 0},
            {"identifier": "1.1", "title": "Dos", "kind": "requirement", "isAssessable": True, "depth": 1},
        ],
    }
    assert body["links"] == [{
        "fromFramework": "alfa", "fromIdentifier": "1.1",
        "toFramework": "beta", "toIdentifier": "1.1", "coverage": "partial",
    }]


def test_a_link_to_a_version_that_is_no_longer_current_is_left_out(
        client, regular_user, auth_headers, tmp_path, monkeypatch):
    _install_crosswalk_catalog(tmp_path, monkeypatch, ("1", "2"))

    body = client.get("/eunomia/crosswalks", headers=auth_headers(regular_user)).get_json()

    assert [framework["version"] for framework in body["frameworks"]] == ["1", "2"]
    assert body["links"] == []
