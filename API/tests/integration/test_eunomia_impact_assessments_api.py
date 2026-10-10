"""Las evaluaciones de impacto enlazan con una ficha del registro de actividades del mismo dueño."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_ACTIVITIES = "/eunomia/registers/rgpd-actividades-tratamiento"
_ASSESSMENTS = "/eunomia/registers/rgpd-evaluaciones-impacto"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


def _activity(client, headers):
    records = client.post(f"{_ACTIVITIES}/examples", headers=headers).get_json()["records"]
    return next(item["id"] for item in records if item["title"] == "Videovigilancia")


def _assessment(activity_id):
    return {"values": {"name": "EIPD videovigilancia", "treatment": str(activity_id), "trigger": "public_monitoring"}}


def test_an_assessment_is_linked_to_its_activity_and_offered_in_the_form(client, owner, auth_headers):
    headers = auth_headers(owner)
    activity_id = _activity(client, headers)

    created = client.post(f"{_ASSESSMENTS}/records", headers=headers, json=_assessment(activity_id))
    detail = client.get(_ASSESSMENTS, headers=headers).get_json()

    assert created.status_code in (200, 201)
    assert {"id": activity_id, "title": "Videovigilancia"} in detail["links"]["treatment"]
    assert detail["records"][0]["values"]["treatment"] == str(activity_id)


def test_an_assessment_cannot_point_to_a_missing_activity(client, owner, auth_headers):
    headers = auth_headers(owner)

    response = client.post(f"{_ASSESSMENTS}/records", headers=headers, json=_assessment(9999))

    assert response.status_code == 400


def test_an_assessment_cannot_point_to_another_owners_activity(client, owner, make_user, make_subscription, auth_headers):
    stranger = make_user()
    make_subscription(stranger, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    foreign_id = _activity(client, auth_headers(stranger))

    response = client.post(f"{_ASSESSMENTS}/records", headers=auth_headers(owner), json=_assessment(foreign_id))

    assert response.status_code == 400


def test_the_export_shows_the_activity_name_instead_of_its_id(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.post(f"{_ASSESSMENTS}/records", headers=headers, json=_assessment(_activity(client, headers)))

    csv_body = client.get(f"{_ASSESSMENTS}/export?format=csv", headers=headers).data.decode("utf-8")

    assert "Videovigilancia" in csv_body
