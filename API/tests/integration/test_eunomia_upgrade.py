"""Cambio de versión de un marco adoptado: vista previa, traslado y límites."""

import json
from datetime import timedelta

import pytest

from src.modules.features.eunomia.managers import assessments as assessments_manager
from src.modules.features.eunomia.managers import frameworks as frameworks_manager
from src.modules.features.eunomia.services import catalog as catalog_service
from src.modules.features.eunomia.services import version_mappings
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)


def _version(version, identifiers):
    return {
        "key": "demo", "version": version, "status": "draft", "name": "Marco de prueba",
        "shortName": "Demo", "publishedAt": "2026-01-01", "licenseMode": "full_text",
        "sources": [{"name": "n", "url": "u", "license": "l", "consultedAt": "2026-10-10"}],
        "nodes": [{"identifier": i, "parent": None, "order": n, "kind": "requirement", "title": f"Control {i}"}
                  for n, i in enumerate(identifiers, 1)],
    }


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """Un marco ``demo`` con la versión 1 vigente; ``publish_v2()`` hace vigente la 2."""
    (tmp_path / "demo" / "mappings").mkdir(parents=True)
    (tmp_path / "demo" / "1.json").write_text(json.dumps(_version("1", ["A", "B", "C", "D", "E"])), "utf-8")
    (tmp_path / "demo" / "2.json").write_text(json.dumps(_version("2", ["X", "Y", "Z", "W", "N"])), "utf-8")
    (tmp_path / "demo" / "mappings" / "1__2.json").write_text(json.dumps({
        "framework": "demo", "from": "1", "to": "2", "mappings": [
            {"from": "A", "to": "X", "relation": "equivalent"},
            {"from": "B", "to": "Y", "relation": "split"}, {"from": "B", "to": "Z", "relation": "split"},
            {"from": "C", "to": "W", "relation": "merged"}, {"from": "D", "to": "W", "relation": "merged"},
            {"from": "E", "to": None, "relation": "retired"},
            {"from": None, "to": "N", "relation": "new"},
        ]}), "utf-8")

    def write_index(current):
        versions = [{"version": "1", "status": "draft"}] + ([{"version": "2", "status": "draft"}] if current == "2" else [])
        (tmp_path / "index.json").write_text(json.dumps({"frameworks": [{
            "key": "demo", "name": "Marco de prueba", "shortName": "Demo", "current": current, "versions": versions,
        }]}), "utf-8")
        catalog_service._load_index.cache_clear()

    write_index("1")
    load_version = lambda key, version: catalog_service.load_version(key, version, tmp_path)  # noqa: E731
    monkeypatch.setattr(frameworks_manager, "load_index", lambda: catalog_service.load_index(tmp_path))
    monkeypatch.setattr(frameworks_manager, "load_version", load_version)
    monkeypatch.setattr(frameworks_manager, "load_mapping",
                        lambda key, a, b: version_mappings.load_mapping(key, a, b, tmp_path))
    monkeypatch.setattr(assessments_manager, "load_version", load_version)
    return lambda: write_index("2")


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def adopted(client, owner, auth_headers, demo):
    assert client.post("/eunomia/adoptions", headers=auth_headers(owner),
                       json={"frameworkKey": "demo"}).status_code == 201
    return owner


def _assess(client, headers, control, status="implemented", **extra):
    response = client.put(f"/eunomia/adoptions/demo/controls/{control}", headers=headers,
                          json={"status": status, "updatedAt": None, **extra})
    assert response.status_code == 200, response.get_json()


def test_an_up_to_date_framework_has_nothing_to_upgrade(client, adopted, auth_headers):
    response = client.get("/eunomia/adoptions/demo/upgrade-preview", headers=auth_headers(adopted))

    assert response.status_code == 409
    assert response.get_json()["messageKey"] == "frameworkUpToDate"


def test_the_preview_explains_what_moves_what_is_reviewed_and_what_is_lost(client, adopted, auth_headers, demo):
    headers = auth_headers(adopted)
    for control in ("A", "B", "E"):
        _assess(client, headers, control)
    demo()

    body = client.get("/eunomia/adoptions/demo/upgrade-preview", headers=headers).get_json()

    moves = {move["identifier"]: move for move in body["moves"]}
    assert (body["fromVersion"], body["toVersion"]) == ("1", "2")
    assert moves["X"]["needsReview"] is False
    assert moves["Y"]["needsReview"] and moves["Z"]["needsReview"]
    assert [item["identifier"] for item in body["lost"]] == ["E"]
    assert [item["identifier"] for item in body["newControls"]] == ["N"]


def test_the_preview_changes_nothing(client, adopted, auth_headers, demo):
    headers = auth_headers(adopted)
    _assess(client, headers, "A")
    demo()
    client.get("/eunomia/adoptions/demo/upgrade-preview", headers=headers)

    listed = client.get("/eunomia/adoptions", headers=headers).get_json()["adoptions"]
    assert listed[0]["catalogVersion"] == "1"


def test_upgrading_moves_the_assessment_and_marks_what_needs_review(client, adopted, auth_headers, demo):
    headers = auth_headers(adopted)
    _assess(client, headers, "A", notes="Hecho en 2025")
    _assess(client, headers, "B")
    _assess(client, headers, "C")
    demo()

    assert client.post("/eunomia/adoptions/demo/upgrade", headers=headers).status_code == 200

    listed = client.get("/eunomia/adoptions", headers=headers).get_json()["adoptions"]
    assert listed[0]["catalogVersion"] == "2"
    tree = {node["identifier"]: node for node in
            client.get("/eunomia/adoptions/demo/tree", headers=headers).get_json()["tree"]}
    assert tree["X"]["assessment"]["status"] == "implemented"
    assert tree["X"]["assessment"]["notes"] == "Hecho en 2025"
    assert "Revisar" in tree["Y"]["assessment"]["notes"]
    assert tree["W"]["assessment"]["status"] == "in_progress"      # C hecho, D pendiente: no mejora
    assert tree["N"]["assessment"]["status"] == "pending"


def test_evidence_links_follow_their_controls(client, adopted, auth_headers, demo):
    import io

    headers = auth_headers(adopted)
    evidence_id = client.post(
        "/eunomia/evidence", headers=headers, content_type="multipart/form-data",
        data={"file": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "p.pdf"), "title": "Política"},
    ).get_json()["id"]
    for control in ("A", "E"):
        client.post(f"/eunomia/evidence/{evidence_id}/links", headers=headers,
                    json={"frameworkKey": "demo", "controlIdentifier": control})
    demo()

    client.post("/eunomia/adoptions/demo/upgrade", headers=headers)

    item = next(e for e in client.get("/eunomia/evidence", headers=headers).get_json()["evidence"]
                if e["id"] == evidence_id)
    assert {link["controlIdentifier"] for link in item["links"]} == {"X"}


def test_a_member_cannot_upgrade_the_owners_frameworks(app, client, adopted, regular_user, auth_headers, demo):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=org["id"], user_id=regular_user.id,
                                               member_role="member"))
            uow.session.flush()
    demo()

    response = client.post("/eunomia/adoptions/demo/upgrade", headers=auth_headers(regular_user))

    assert response.status_code == 403
