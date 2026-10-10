"""Evaluar controles: cuatro estados, justificación, responsables y concurrencia."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_CONTROL = "/eunomia/adoptions/nis2/controls/RE.3.1"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def adopted(client, owner, auth_headers):
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "nis2"})
    return owner


def _join(app, organization_id, user_id):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=organization_id, user_id=user_id, member_role="member"))
            uow.session.flush()


def _put(client, headers, path=_CONTROL, **body):
    payload = {"status": "in_progress", "updatedAt": None}
    payload.update(body)
    return client.put(path, headers=headers, json=payload)


@pytest.mark.parametrize("status", ["pending", "in_progress", "implemented"])
def test_a_control_takes_each_plain_state(client, adopted, auth_headers, status):
    response = _put(client, auth_headers(adopted), status=status, notes="Revisado")

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["status"] == status
    assert body["code"] == "nis2:RE.3.1"
    assert body["updatedAt"] is not None


def test_not_applicable_needs_a_justification(client, adopted, auth_headers):
    denied = _put(client, auth_headers(adopted), status="not_applicable")
    assert denied.status_code == 400
    assert denied.get_json()["messageKey"] == "justificationRequired"

    allowed = _put(client, auth_headers(adopted), status="not_applicable", justification="No tenemos ese servicio.")
    assert allowed.status_code == 200
    assert allowed.get_json()["justification"] == "No tenemos ese servicio."


def test_a_group_cannot_be_assessed(client, adopted, auth_headers):
    response = _put(client, auth_headers(adopted), "/eunomia/adoptions/nis2/controls/RE.3")

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "controlNotAssessable"


def test_a_control_that_does_not_exist_is_a_404(client, adopted, auth_headers):
    assert _put(client, auth_headers(adopted), "/eunomia/adoptions/nis2/controls/9.9.9").status_code == 404


def test_a_framework_that_is_not_adopted_is_a_404(client, owner, auth_headers):
    assert _put(client, auth_headers(owner)).status_code == 404


def test_a_stale_write_is_a_conflict_that_carries_the_current_value(client, adopted, auth_headers):
    first = _put(client, auth_headers(adopted), status="in_progress").get_json()

    stale = _put(client, auth_headers(adopted), status="implemented", updatedAt=None)
    assert stale.status_code == 409
    assert stale.get_json()["messageKey"] == "assessmentConflict"
    assert stale.get_json()["details"]["current"]["status"] == "in_progress"

    fresh = _put(client, auth_headers(adopted), status="implemented", updatedAt=first["updatedAt"])
    assert fresh.status_code == 200
    assert fresh.get_json()["status"] == "implemented"


def test_two_writes_with_the_same_witness_only_one_wins(client, adopted, auth_headers):
    seen = _put(client, auth_headers(adopted), status="in_progress").get_json()["updatedAt"]

    one = _put(client, auth_headers(adopted), status="implemented", updatedAt=seen)
    two = _put(client, auth_headers(adopted), status="pending", updatedAt=seen)

    assert (one.status_code, two.status_code) == (200, 409)


def test_a_member_assesses_on_the_rows_of_the_owner(client, app, adopted, regular_user, auth_headers):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)

    by_member = _put(client, auth_headers(regular_user), status="implemented")
    assert by_member.status_code == 200
    seen = by_member.get_json()["updatedAt"]

    by_owner = _put(client, auth_headers(adopted), status="pending", updatedAt=seen)
    assert by_owner.status_code == 200


def test_the_responsible_has_to_be_the_owner_or_a_member(client, app, adopted, regular_user, make_user, auth_headers):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)
    stranger = make_user()

    inside = _put(client, auth_headers(adopted), responsibleUserId=regular_user.id)
    assert inside.status_code == 200
    assert inside.get_json()["responsibleUserId"] == regular_user.id

    outside = _put(client, auth_headers(adopted), responsibleUserId=stranger.id,
                   updatedAt=inside.get_json()["updatedAt"])
    assert outside.status_code == 400
    assert outside.get_json()["messageKey"] == "responsibleNotInOrganization"


def test_the_control_is_validated_against_the_adopted_version_not_the_current_one(
    client, app, adopted, auth_headers,
):
    from src.modules.features.eunomia.model import EunomiaFrameworkAdoption
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.query(EunomiaFrameworkAdoption).update({"catalog_version": "2020-viejo"})

    assert _put(client, auth_headers(adopted)).status_code == 404


def test_removing_a_framework_counts_its_assessments_and_the_purge_deletes_them(client, app, adopted, auth_headers):
    from datetime import timedelta as _td

    from src.modules.features.eunomia import EunomiaFrameworkManager
    from src.modules.features.eunomia.model import EunomiaControlAssessment, EunomiaFrameworkAdoption
    from src.modules.infrastructure import unit_of_work

    headers = auth_headers(adopted)
    _put(client, headers, status="implemented")
    _put(client, headers, "/eunomia/adoptions/nis2/controls/RE.3.2", status="pending")   # pendiente: no cuenta

    preview = client.get("/eunomia/adoptions/nis2/removal-preview", headers=headers).get_json()
    assert preview["assessments"] == 1

    client.delete("/eunomia/adoptions/nis2", headers=headers)
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.query(EunomiaFrameworkAdoption).update({"archived_at": utcnow_naive() - _td(days=40)})
        EunomiaFrameworkManager().purge_expired()
        with unit_of_work.UnitOfWork() as uow:
            assert uow.session.query(EunomiaControlAssessment).count() == 0


# ── el árbol personal ──────────────────────────────────────────────────────

def _flatten(nodes):
    for node in nodes:
        yield node
        yield from _flatten(node["children"])


def test_the_personal_tree_merges_the_catalog_with_the_assessments(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _put(client, headers, status="implemented", notes="Hecho")

    body = client.get("/eunomia/adoptions/nis2/tree", headers=headers).get_json()
    nodes = {node["identifier"]: node for node in _flatten(body["tree"])}

    assert body["version"] == "2022-2555"
    assert nodes["RE.3.1"]["assessment"]["status"] == "implemented"
    assert nodes["RE.3.2"]["assessment"]["status"] == "pending"      # sin fila = pendiente
    assert nodes["RE.3"]["assessment"] is None                         # un grupo no se evalúa
    assert nodes["RE.3.1"]["actions"] and nodes["RE.3.1"]["evidence"]  # lo que se le pide


def test_the_tree_of_a_framework_that_is_not_adopted_is_a_404(client, owner, auth_headers):
    assert client.get("/eunomia/adoptions/nis2/tree", headers=auth_headers(owner)).status_code == 404


def test_a_member_sees_the_assessments_of_the_owner(client, app, adopted, regular_user, auth_headers):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)
    _put(client, auth_headers(adopted), status="in_progress")

    body = client.get("/eunomia/adoptions/nis2/tree", headers=auth_headers(regular_user)).get_json()
    node = next(n for n in _flatten(body["tree"]) if n["identifier"] == "RE.3.1")

    assert node["assessment"]["status"] == "in_progress"


def test_the_tree_works_for_frameworks_of_different_depth(client, owner, auth_headers):
    headers = auth_headers(owner)
    for key in ("iso27001", "ens"):
        client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": key})

    def depth(node):
        return 1 + max((depth(child) for child in node["children"]), default=0)

    def tree_depth(key):
        tree = client.get(f"/eunomia/adoptions/{key}/tree", headers=headers).get_json()["tree"]
        return max(depth(root) for root in tree)

    assert tree_depth("iso27001") == 2
    assert tree_depth("ens") == 4   # marco, grupo, medida y refuerzo


def test_the_owner_sees_the_members_as_assignable_people_and_a_member_only_themselves(
    client, app, adopted, regular_user, auth_headers,
):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)

    as_owner = client.get("/eunomia/adoptions/nis2/tree", headers=auth_headers(adopted)).get_json()["people"]
    as_member = client.get("/eunomia/adoptions/nis2/tree", headers=auth_headers(regular_user)).get_json()["people"]

    assert {person["userId"] for person in as_owner} == {adopted.id, regular_user.id}
    assert {person["userId"] for person in as_member} == {adopted.id, regular_user.id}


# ── historial ──────────────────────────────────────────────────────────────

_HISTORY = "/eunomia/adoptions/nis2/history/RE.3.1"


def test_every_change_creates_an_event_with_its_differences(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    first = _put(client, headers, status="in_progress").get_json()
    _put(client, headers, status="implemented", notes="Ya está", updatedAt=first["updatedAt"])

    events = client.get(_HISTORY, headers=headers).get_json()["events"]

    assert len(events) == 2
    latest = events[0]["changes"]
    assert latest["status"] == {"from": "in_progress", "to": "implemented"}
    assert latest["notes"] == {"from": None, "to": "Ya está"}
    assert events[1]["changes"]["status"] == {"from": "pending", "to": "in_progress"}
    assert events[0]["actorName"]


def test_saving_without_changes_adds_no_event(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    first = _put(client, headers, status="in_progress").get_json()
    _put(client, headers, status="in_progress", updatedAt=first["updatedAt"])

    assert len(client.get(_HISTORY, headers=headers).get_json()["events"]) == 1


def test_a_rejected_change_leaves_no_event(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _put(client, headers, status="not_applicable")   # sin justificación: se rechaza

    assert client.get(_HISTORY, headers=headers).get_json()["events"] == []


def test_a_member_change_is_recorded_under_their_name(client, app, adopted, regular_user, auth_headers):
    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)
    _put(client, auth_headers(regular_user), status="implemented")

    event = client.get(_HISTORY, headers=auth_headers(adopted)).get_json()["events"][0]

    assert event["actorUserId"] == regular_user.id


def test_deleting_the_actor_keeps_the_event_without_the_account(client, app, adopted, regular_user, auth_headers):
    from src.modules.features.eunomia.services.user_data import purge_eunomia_data
    from src.modules.infrastructure import unit_of_work

    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)
    _put(client, auth_headers(regular_user), status="implemented")
    name = client.get(_HISTORY, headers=auth_headers(adopted)).get_json()["events"][0]["actorName"]

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            purge_eunomia_data(uow, regular_user.id)

    event = client.get(_HISTORY, headers=auth_headers(adopted)).get_json()["events"][0]
    assert event["actorUserId"] is None
    assert event["actorName"] == name


# ── resumen ────────────────────────────────────────────────────────────────

def test_the_summary_reports_progress_by_branch_and_what_needs_attention(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _put(client, headers, status="implemented")
    _put(client, headers, "/eunomia/adoptions/nis2/controls/RE.3.2", status="not_applicable",
         justification="No aplica a nuestro servicio.")
    _put(client, headers, "/eunomia/adoptions/nis2/controls/RE.3.3", status="in_progress",
         dueDate=(utcnow_naive() - timedelta(days=2)).date().isoformat())

    body = client.get("/eunomia/adoptions/nis2/summary", headers=headers).get_json()

    assert body["global"]["counts"]["implemented"] == 1
    assert body["global"]["counts"]["not_applicable"] == 1
    assert body["global"]["countable"] == body["global"]["total"] - 1
    assert any(branch["identifier"] == "20" for branch in body["branches"])
    assert [item["identifier"] for item in body["upcoming"]] == ["RE.3.3"]
    assert body["upcoming"][0]["isOverdue"] is True
    assert body["unassignedCount"] > 0


def test_the_adoption_list_carries_the_progress_of_each_active_framework(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _put(client, headers, status="implemented")

    item = client.get("/eunomia/adoptions", headers=headers).get_json()["adoptions"][0]

    assert item["progress"]["counts"]["implemented"] == 1
    assert item["progress"]["percent"] > 0


def test_groups_of_the_tree_carry_their_aggregate_progress(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _put(client, headers, status="implemented")

    tree = client.get("/eunomia/adoptions/nis2/tree", headers=headers).get_json()["tree"]
    nodes = {n["identifier"]: n for n in _flatten(tree)}

    assert nodes["RE.3"]["progress"]["counts"]["implemented"] == 1
    assert nodes["RE.3"]["progress"]["total"] == 6


# ── correspondencias entre marcos ──────────────────────────────────────────

def _adopt_both(client, headers):
    for key in ("nis2", "ens"):
        client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": key})


def _node(tree, identifier):
    return next(n for n in _flatten(tree) if n["identifier"] == identifier)


def test_a_control_shows_what_is_done_in_the_other_adopted_framework(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _adopt_both(client, headers)
    client.put("/eunomia/adoptions/ens/controls/op.acc.2", headers=headers,
               json={"status": "implemented", "updatedAt": None})

    tree = client.get("/eunomia/adoptions/nis2/tree", headers=headers).get_json()["tree"]

    suggestion = _node(tree, "RE.11.1")["suggestions"][0]
    assert (suggestion["frameworkKey"], suggestion["identifier"], suggestion["coverage"]) == ("ens", "op.acc.2", "full")
    assert suggestion["status"] == "implemented"


def test_no_suggestions_without_the_other_framework_adopted(client, adopted, auth_headers):
    tree = client.get("/eunomia/adoptions/nis2/tree", headers=auth_headers(adopted)).get_json()["tree"]

    assert _node(tree, "RE.11.1")["suggestions"] == []


def test_the_summary_counts_open_controls_already_covered_elsewhere(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    _adopt_both(client, headers)
    for control in ("op.acc.2", "op.acc.4"):
        client.put(f"/eunomia/adoptions/ens/controls/{control}", headers=headers,
                   json={"status": "implemented", "updatedAt": None})

    summary = client.get("/eunomia/adoptions/nis2/summary", headers=headers).get_json()

    assert summary["suggestedCoverage"] >= 2


def test_linking_the_suggested_evidence_creates_a_link_and_copies_no_file(app, client, adopted, auth_headers):
    import io

    from src.modules.features.eunomia.model import EunomiaEvidenceContent
    from src.modules.infrastructure import unit_of_work

    headers = auth_headers(adopted)
    _adopt_both(client, headers)
    evidence_id = client.post(
        "/eunomia/evidence", headers=headers, content_type="multipart/form-data",
        data={"file": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "politica.pdf"), "title": "Política"},
    ).get_json()["id"]
    client.post(f"/eunomia/evidence/{evidence_id}/links", headers=headers,
                json={"frameworkKey": "ens", "controlIdentifier": "op.acc.2"})

    tree = client.get("/eunomia/adoptions/nis2/tree", headers=headers).get_json()["tree"]
    offered = _node(tree, "RE.11.1")["suggestions"][0]["evidence"]
    assert [item["id"] for item in offered] == [evidence_id]

    client.post(f"/eunomia/evidence/{offered[0]['id']}/links", headers=headers,
                json={"frameworkKey": "nis2", "controlIdentifier": "RE.11.1"})
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            assert uow.session.query(EunomiaEvidenceContent).count() == 1


# ── evidencias automáticas ─────────────────────────────────────────────────

def test_the_automatic_evidence_of_a_control_comes_from_the_registered_providers(client, adopted, auth_headers,
                                                                                monkeypatch):
    from src.modules.features.eunomia.services.providers import AutomaticEvidence, EvidenceProviderRegistry

    monkeypatch.setattr(EvidenceProviderRegistry, "_providers", {})
    seen = []
    EvidenceProviderRegistry.register(
        "demo.scans", name="Escaneos", controls={"nis2": ("RE.3.1",)},
        collect=lambda owner, framework, identifier: seen.append(owner) or [
            AutomaticEvidence("Último escaneo", "Hace 2 días", status="warning")],
    )

    body = client.get("/eunomia/adoptions/nis2/automatic-evidence/RE.3.1", headers=auth_headers(adopted)).get_json()

    assert [(item["providerKey"], item["status"]) for item in body["evidence"]] == [("demo.scans", "warning")]
    assert seen == [adopted.id]


def test_automatic_evidence_of_a_group_or_an_unknown_control_is_rejected(client, adopted, auth_headers):
    headers = auth_headers(adopted)

    assert client.get("/eunomia/adoptions/nis2/automatic-evidence/RE.3", headers=headers).status_code == 400
    assert client.get("/eunomia/adoptions/nis2/automatic-evidence/no-existe", headers=headers).status_code == 404
