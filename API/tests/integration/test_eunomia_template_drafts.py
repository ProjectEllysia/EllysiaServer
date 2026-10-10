"""Borradores de plantillas: precarga del perfil y de las evaluaciones, y lo que escribe el usuario."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/templates/incident-procedure/draft"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


def _fields(response):
    return {item["key"]: item for item in response.get_json()["fields"]}


def _join(app, organization_id, user_id):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=organization_id, user_id=user_id, member_role="member"))
            uow.session.flush()


def test_the_list_offers_the_templates_and_whether_the_framework_is_adopted(client, owner, auth_headers):
    headers = auth_headers(owner)

    before = client.get("/eunomia/templates", headers=headers).get_json()["templates"]
    client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": "nis2"})
    after = client.get("/eunomia/templates", headers=headers).get_json()["templates"]

    assert {t["key"] for t in before} >= {"incident-procedure", "security-policy"}
    assert all(not t["isFrameworkAdopted"] for t in before)
    assert all(t["isFrameworkAdopted"] for t in after if t["framework"] == "nis2")


def test_the_form_arrives_prefilled_from_the_company_profile(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"legalName": "Acme S.L.", "taxId": "B12345674",
                                                                  "country": "ES"})

    form = _fields(client.get(_URL, headers=headers))

    assert (form["company_name"]["value"], form["company_name"]["origin"]) == ("Acme S.L.", "company")
    assert "company_name" not in client.get(_URL, headers=headers).get_json()["missingRequired"]


def test_the_responsible_of_a_control_prefills_the_person(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": "nis2"})
    client.put("/eunomia/adoptions/nis2/controls/RE.3.5", headers=headers,
               json={"status": "in_progress", "responsibleUserId": owner.id, "updatedAt": None})

    form = _fields(client.get(_URL, headers=headers))

    assert form["incident_manager"]["origin"] == "assessment"
    assert form["incident_manager"]["value"]


def test_a_saved_value_wins_over_the_prefill_and_is_kept(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"legalName": "Acme S.L."})

    saved = client.put(_URL, headers=headers, json={"values": {"company_name": "Acme Seguridad S.A."}})

    assert saved.status_code == 200, saved.get_json()
    form = _fields(client.get(_URL, headers=headers))
    assert (form["company_name"]["value"], form["company_name"]["origin"]) == ("Acme Seguridad S.A.", "saved")
    assert saved.get_json()["updatedAt"] is not None


def test_required_fields_left_empty_are_reported(client, owner, auth_headers):
    body = client.get(_URL, headers=auth_headers(owner)).get_json()

    assert {"reporting_channel", "csirt", "approver"} <= set(body["missingRequired"])


def test_an_unknown_field_or_a_bad_date_is_rejected(client, owner, auth_headers):
    headers = auth_headers(owner)

    assert client.put(_URL, headers=headers, json={"values": {"inventado": "x"}}).status_code == 400
    bad_date = client.put(_URL, headers=headers, json={"values": {"approval_date": "ayer"}})
    assert bad_date.status_code == 400
    assert bad_date.get_json()["messageKey"] == "templateValueInvalid"


def test_an_unknown_template_is_a_404(client, owner, auth_headers):
    response = client.get("/eunomia/templates/no-existe/draft", headers=auth_headers(owner))

    assert response.status_code == 404
    assert response.get_json()["messageKey"] == "entityNotFound.template"


def test_a_member_fills_the_draft_of_the_owner(app, client, owner, regular_user, auth_headers):
    org = client.post("/organizations", headers=auth_headers(owner), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)

    client.put(_URL, headers=auth_headers(regular_user), json={"values": {"csirt": "INCIBE-CERT"}})

    seen = _fields(client.get(_URL, headers=auth_headers(owner)))
    assert seen["csirt"]["value"] == "INCIBE-CERT"
