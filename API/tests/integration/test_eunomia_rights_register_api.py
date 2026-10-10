"""El registro de solicitudes de derechos por la API."""

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


def test_the_rights_register_lists_its_one_month_deadline_its_one_month_deadline(client, owner, auth_headers):
    headers = auth_headers(owner)
    url = "/eunomia/registers/rgpd-solicitudes-derechos"

    created = client.post(f"{url}/records", headers=headers, json={"values": {
        "name": "Acceso — cliente", "right": "access", "received_at": "2026-01-15"}}).get_json()

    assert [item["key"] for item in created["deadlines"]] == ["response"]
