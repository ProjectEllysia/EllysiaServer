"""La API del catálogo de Eunomia: quién la lee y qué devuelve."""

import json

import pytest

from src.modules.features.eunomia.managers import catalog as catalog_manager
from src.modules.features.eunomia.services import catalog as catalog_service

pytestmark = pytest.mark.integration

_DOCUMENT = {
    "key": "demo", "version": "1", "status": "draft", "name": "Marco de prueba",
    "shortName": "Demo", "publishedAt": "2026-01-01",
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
