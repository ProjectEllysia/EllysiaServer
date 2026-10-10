"""El registro de incidentes y brechas: plazos de NIS2 y del RGPD desde la misma hora, y sus notificaciones."""

from datetime import datetime, timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/registers/incidentes-y-brechas"
_AWARE = "2026-10-10T08:00"
_BASE = {"name": "Ransomware en el ERP", "aware_at": _AWARE, "description": "Cifrado del servidor."}


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


def _deadlines(client, headers, **values):
    record = client.post(f"{_URL}/records", headers=headers, json={"values": {**_BASE, **values}}).get_json()
    return {d["key"]: d for d in record["deadlines"]}


def _due(deadline):
    return datetime.fromisoformat(deadline["dueAt"].replace("Z", "")).replace(tzinfo=None)


def test_a_nis2_only_incident_computes_24_hours_72_hours_and_waits_for_the_final_report(client, owner, auth_headers):
    found = _deadlines(client, auth_headers(owner), nis2_significant="yes", personal_data_risk="no_personal_data")

    assert set(found) == {"nis2_early", "nis2_notification", "nis2_final"}
    assert _due(found["nis2_early"]) == datetime(2026, 10, 11, 8, 0)
    assert _due(found["nis2_notification"]) == datetime(2026, 10, 13, 8, 0)
    assert found["nis2_final"]["status"] == "pending_input"      # corre desde la notificación enviada


def test_the_final_report_runs_one_month_from_the_notification_sent(client, owner, auth_headers):
    found = _deadlines(client, auth_headers(owner), nis2_significant="yes",
                       nis2_notification_sent_at="2026-10-12T10:00")

    assert _due(found["nis2_final"]) == datetime(2026, 11, 12, 10, 0)


def test_a_gdpr_only_breach_with_risk_computes_72_hours(client, owner, auth_headers):
    found = _deadlines(client, auth_headers(owner), nis2_significant="no", personal_data_risk="risk")

    assert set(found) == {"gdpr_authority"}
    assert _due(found["gdpr_authority"]) == datetime(2026, 10, 13, 8, 0)


def test_an_incident_that_is_both_computes_both_sets_from_the_same_moment(client, owner, auth_headers):
    found = _deadlines(client, auth_headers(owner), nis2_significant="yes", personal_data_risk="high")

    assert set(found) == {"nis2_early", "nis2_notification", "nis2_final", "gdpr_authority", "gdpr_subjects"}
    assert _due(found["nis2_notification"]) == _due(found["gdpr_authority"])


def test_a_breach_without_risk_has_no_deadline_but_is_recorded(client, owner, auth_headers):
    headers = auth_headers(owner)
    record = client.post(f"{_URL}/records", headers=headers, json={"values": {
        **_BASE, "nis2_significant": "no", "personal_data_risk": "no_risk",
        "gdpr_reason": "Datos cifrados; riesgo improbable."}}).get_json()

    listed = client.get(_URL, headers=headers).get_json()["records"]

    assert record["deadlines"] == []
    assert [r["id"] for r in listed] == [record["id"]]


def test_sending_a_notification_closes_its_deadline(client, owner, auth_headers):
    found = _deadlines(client, auth_headers(owner), nis2_significant="yes", nis2_early_sent_at="2026-10-10T20:00")

    assert found["nis2_early"]["status"] == "done"


def test_the_notification_template_arrives_filled_with_the_incident_data(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"legalName": "Acme S.L.", "taxId": "B12345674",
                                                                       "country": "ES", "securityContact": "ciso@acme.test"})
    record = client.post(f"{_URL}/records", headers=headers, json={"values": {
        **_BASE, "nis2_significant": "yes", "systems": "ERP\nCorreo"}}).get_json()

    form = client.get(f"/eunomia/templates/incident-early-warning/draft?recordId={record['id']}",
                      headers=headers).get_json()
    fields = {f["key"]: f for f in form["fields"]}

    assert fields["incident"]["value"] == "Ransomware en el ERP"
    assert fields["aware_at"]["value"] == "10/10/2026 08:00"
    assert fields["systems"]["origin"] == "record"
    assert fields["company_name"]["value"] == "Acme S.L."
    assert fields["contact"]["value"] == "ciso@acme.test"


def test_a_template_without_a_record_leaves_the_record_fields_empty(client, owner, auth_headers):
    form = client.get("/eunomia/templates/incident-early-warning/draft", headers=auth_headers(owner)).get_json()

    assert {f["key"]: f["value"] for f in form["fields"]}["incident"] == ""


def test_a_record_of_another_account_is_not_found(client, owner, make_user, auth_headers):
    record = client.post(f"{_URL}/records", headers=auth_headers(owner), json={"values": _BASE}).get_json()

    response = client.get(f"/eunomia/templates/incident-early-warning/draft?recordId={record['id']}",
                          headers=auth_headers(make_user()))

    assert response.status_code == 404


def test_the_register_is_evidence_of_the_incident_requirements_of_both_frameworks(client, owner, auth_headers):
    headers = auth_headers(owner)
    for framework in ("nis2", "rgpd"):
        client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": framework})
    client.post(f"{_URL}/records", headers=headers, json={"values": _BASE})

    nis2 = client.get("/eunomia/adoptions/nis2/automatic-evidence/23.4.a", headers=headers).get_json()["evidence"]
    gdpr = client.get("/eunomia/adoptions/rgpd/automatic-evidence/art.33", headers=headers).get_json()["evidence"]

    assert any(e["providerKey"] == "eunomia.register.incidentes-y-brechas" for e in nis2)
    assert any(e["providerKey"] == "eunomia.register.incidentes-y-brechas" for e in gdpr)
