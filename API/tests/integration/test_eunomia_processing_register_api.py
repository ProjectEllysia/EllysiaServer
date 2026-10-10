"""El registro de actividades de tratamiento por la API: avisos, ejemplos y exportación."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


# ── registro de actividades de tratamiento ─────────────────────────────────

def test_the_processing_register_warns_small_companies_about_the_exemption(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"employeeCount": 40})

    body = client.get("/eunomia/registers/rgpd-actividades-tratamiento", headers=headers).get_json()

    assert "artículo 30.5" in body["advice"][0]


def test_the_processing_register_has_no_warning_for_a_large_company(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"employeeCount": 900})

    body = client.get("/eunomia/registers/rgpd-actividades-tratamiento", headers=headers).get_json()

    assert body["advice"] == []


def test_the_example_activities_are_created_and_exported_with_the_company_data(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"legalName": "Acme S.L.", "taxId": "B12345674",
                                                                       "country": "ES"})
    url = "/eunomia/registers/rgpd-actividades-tratamiento"

    created = client.post(f"{url}/examples", headers=headers).get_json()["records"]
    pdf = client.get(f"{url}/export?format=pdf", headers=headers)

    assert len(created) == 5
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
