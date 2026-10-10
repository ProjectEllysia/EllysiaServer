"""Evidencias: se suben una vez y demuestran varios controles de varios marcos."""

import io
from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def adopted(client, owner, auth_headers):
    for key in ("nis2", "ens"):
        client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": key})
    return owner


def _join(app, organization_id, user_id):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=organization_id, user_id=user_id, member_role="member"))
            uow.session.flush()


def _upload(client, headers, content=_PDF, filename="politica.pdf", **form):
    data = {"file": (io.BytesIO(content), filename), "title": "Política de acceso"}
    data.update(form)
    return client.post("/eunomia/evidence", headers=headers, data=data, content_type="multipart/form-data")


def _link(client, headers, evidence_id, framework, control):
    return client.post(f"/eunomia/evidence/{evidence_id}/links", headers=headers,
                       json={"frameworkKey": framework, "controlIdentifier": control})


def test_an_upload_comes_back_with_the_same_bytes(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    created = _upload(client, headers)
    assert created.status_code == 201, created.get_json()
    body = created.get_json()
    assert body["title"] == "Política de acceso"
    assert body["sizeBytes"] == len(_PDF)
    assert body["contentType"] == "application/pdf"

    download = client.get(f"/eunomia/evidence/{body['id']}/download", headers=headers)

    assert download.status_code == 200
    assert download.data == _PDF
    assert "attachment" in download.headers["Content-Disposition"]
    assert download.headers["X-Content-Type-Options"] == "nosniff"


def test_the_stored_row_does_not_contain_the_plaintext(app, client, adopted, auth_headers):
    from sqlalchemy import text

    from src.modules.infrastructure import unit_of_work

    _upload(client, auth_headers(adopted))

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            raw = uow.session.execute(text('SELECT content FROM "EunomiaEvidenceContent"')).scalar()

    assert b"%PDF-" not in bytes(raw)


def test_one_evidence_demonstrates_controls_of_two_frameworks(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    evidence_id = _upload(client, headers).get_json()["id"]

    assert _link(client, headers, evidence_id, "nis2", "RE.11.1").status_code == 200
    assert _link(client, headers, evidence_id, "ens", "op.acc.2").status_code == 200

    listing = client.get("/eunomia/evidence", headers=headers).get_json()["evidence"]
    assert len(listing) == 1
    assert {(l["frameworkKey"], l["controlIdentifier"]) for l in listing[0]["links"]} == {
        ("nis2", "RE.11.1"), ("ens", "op.acc.2")}

    tree = client.get("/eunomia/adoptions/ens/tree", headers=headers).get_json()["tree"]

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node["children"])

    node = next(n for n in walk(tree) if n["identifier"] == "op.acc.2")
    assert [item["id"] for item in node["linkedEvidence"]] == [evidence_id]


def test_linking_twice_leaves_one_link_and_unlinking_keeps_the_evidence(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    evidence_id = _upload(client, headers).get_json()["id"]
    _link(client, headers, evidence_id, "nis2", "RE.11.1")
    _link(client, headers, evidence_id, "nis2", "RE.11.1")

    unlinked = client.delete(f"/eunomia/evidence/{evidence_id}/links/nis2/RE.11.1", headers=headers)

    assert unlinked.status_code == 200
    assert unlinked.get_json()["links"] == []
    assert len(client.get("/eunomia/evidence", headers=headers).get_json()["evidence"]) == 1


def test_a_group_or_unknown_control_cannot_be_linked(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    evidence_id = _upload(client, headers).get_json()["id"]

    assert _link(client, headers, evidence_id, "nis2", "RE.11").status_code == 400
    assert _link(client, headers, evidence_id, "nis2", "no-existe").status_code == 404
    assert _link(client, headers, evidence_id, "iso27001", "A.5.9").status_code == 404   # no adoptado


def test_deleting_the_evidence_removes_its_links_and_content(app, client, adopted, auth_headers):
    from src.modules.features.eunomia.model import (
        EunomiaEvidence, EunomiaEvidenceContent, EunomiaEvidenceLink,
    )
    from src.modules.infrastructure import unit_of_work

    headers = auth_headers(adopted)
    evidence_id = _upload(client, headers).get_json()["id"]
    _link(client, headers, evidence_id, "nis2", "RE.11.1")

    assert client.delete(f"/eunomia/evidence/{evidence_id}", headers=headers).status_code == 204

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            assert [uow.session.query(m).count() for m in (EunomiaEvidence, EunomiaEvidenceContent, EunomiaEvidenceLink)] == [0, 0, 0]


def test_linking_and_unlinking_are_written_in_the_control_history(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    evidence_id = _upload(client, headers).get_json()["id"]
    _link(client, headers, evidence_id, "nis2", "RE.11.1")
    client.delete(f"/eunomia/evidence/{evidence_id}/links/nis2/RE.11.1", headers=headers)

    events = client.get("/eunomia/adoptions/nis2/history/RE.11.1", headers=headers).get_json()["events"]

    assert [e["changes"]["evidence"] for e in events] == [
        {"from": "Política de acceso", "to": None}, {"from": None, "to": "Política de acceso"}]


def test_a_member_uploads_and_links_in_the_owner_space(client, app, adopted, regular_user, auth_headers):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)

    created = _upload(client, auth_headers(regular_user))
    assert created.status_code == 201
    evidence_id = created.get_json()["id"]
    assert _link(client, auth_headers(regular_user), evidence_id, "nis2", "RE.11.1").status_code == 200

    owner_listing = client.get("/eunomia/evidence", headers=auth_headers(adopted)).get_json()["evidence"]
    assert [item["id"] for item in owner_listing] == [evidence_id]


def test_a_user_outside_the_organization_gets_a_404(client, adopted, make_user, auth_headers):
    evidence_id = _upload(client, auth_headers(adopted)).get_json()["id"]
    stranger = make_user()

    assert client.get(f"/eunomia/evidence/{evidence_id}/download", headers=auth_headers(stranger)).status_code == 404
    assert client.delete(f"/eunomia/evidence/{evidence_id}", headers=auth_headers(stranger)).status_code == 404


def test_an_upload_without_a_file_is_rejected(client, adopted, auth_headers):
    response = client.post("/eunomia/evidence", headers=auth_headers(adopted),
                           data={"title": "Sin fichero"}, content_type="multipart/form-data")

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "evidenceFileMissing"


def test_the_file_name_is_sanitized(client, adopted, auth_headers):
    created = _upload(client, auth_headers(adopted), filename="../../etc/pass\x00wd.pdf").get_json()

    assert "/" not in created["filename"] and "\x00" not in created["filename"]
    assert created["filename"].endswith(".pdf")


def test_a_type_outside_the_allowed_list_is_rejected(client, adopted, auth_headers):
    response = _upload(client, auth_headers(adopted), filename="programa.exe", content=b"MZ\x90\x00")

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "evidenceTypeNotAllowed"


def test_removing_a_framework_keeps_evidence_that_serves_another_one(app, client, adopted, auth_headers):
    from src.modules.features.eunomia import EunomiaFrameworkManager
    from src.modules.features.eunomia.model import EunomiaFrameworkAdoption
    from src.modules.infrastructure import unit_of_work

    headers = auth_headers(adopted)
    shared = _upload(client, headers, title="Compartida").get_json()["id"]
    exclusive = _upload(client, headers, title="Solo NIS2").get_json()["id"]
    _link(client, headers, shared, "nis2", "RE.11.1")
    _link(client, headers, shared, "ens", "op.acc.2")
    _link(client, headers, exclusive, "nis2", "RE.11.2")

    preview = client.get("/eunomia/adoptions/nis2/removal-preview", headers=headers).get_json()
    assert (preview["evidenceDeleted"], preview["evidenceKept"]) == (1, 1)

    client.delete("/eunomia/adoptions/nis2", headers=headers)
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.query(EunomiaFrameworkAdoption).filter_by(framework_key="nis2").update(
                {"archived_at": utcnow_naive() - timedelta(days=40)})
        EunomiaFrameworkManager().purge_expired()

    remaining = client.get("/eunomia/evidence", headers=headers).get_json()["evidence"]
    assert [item["id"] for item in remaining] == [shared]
    assert [(l["frameworkKey"]) for l in remaining[0]["links"]] == ["ens"]


# ── cuota de almacenamiento ────────────────────────────────────────────────

@pytest.fixture()
def tight_storage(app, seeded_plans):
    """Aprieta a 1 MB el almacenamiento de evidencias del plan Gold de la suite."""
    from src.modules.accounts.model import PlanLimit
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.query(PlanLimit).filter(
                PlanLimit.plan_id == seeded_plans["gold"],
                PlanLimit.limit_key == "eunomia.evidence_storage", PlanLimit.scope == "holder",
            ).update({"value": 1024 * 1024})


def test_an_upload_over_the_quota_is_rejected_and_stores_nothing(app, client, adopted, tight_storage, auth_headers):
    from src.modules.features.eunomia.model import EunomiaEvidence
    from src.modules.infrastructure import unit_of_work

    response = _upload(client, auth_headers(adopted), content=b"%PDF-" + b"0" * (1024 * 1024 + 10))

    assert response.status_code == 402
    assert response.get_json()["messageKey"] == "evidenceStorageFull"
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            assert uow.session.query(EunomiaEvidence).count() == 0


def test_the_usage_is_reported_and_deleting_frees_the_space(client, adopted, tight_storage, auth_headers):
    headers = auth_headers(adopted)
    evidence_id = _upload(client, headers).get_json()["id"]

    usage = client.get("/eunomia/evidence", headers=headers).get_json()["usage"]
    assert usage["usedBytes"] == len(_PDF)
    assert usage["limitBytes"] == 1024 * 1024

    client.delete(f"/eunomia/evidence/{evidence_id}", headers=headers)
    assert client.get("/eunomia/evidence", headers=headers).get_json()["usage"]["usedBytes"] == 0


def test_a_member_spends_the_quota_of_the_owner(client, app, adopted, regular_user, tight_storage, auth_headers):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)

    assert _upload(client, auth_headers(regular_user)).status_code == 201

    usage = client.get("/eunomia/evidence", headers=auth_headers(adopted)).get_json()["usage"]
    assert usage["usedBytes"] == len(_PDF)
