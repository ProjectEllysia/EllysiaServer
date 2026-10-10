"""Hygeia aporta a Eunomia el inventario real de activos."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/adoptions/nis2/automatic-evidence/RE.12.4"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def adopted(client, owner, auth_headers):
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "nis2"})
    return owner


_counter = [0]


def _asset(app, user_id, *, seen_days_ago=0, inventory=True):
    from src.modules.features.hygeia.model import MonitoredAsset
    from src.modules.infrastructure import unit_of_work

    _counter[0] += 1
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            now = utcnow_naive()
            uow.session.add(MonitoredAsset(
                user_id=user_id, hostname=f"host-{_counter[0]}", agent_key_id=f"key-{_counter[0]}-{user_id}",
                agent_key_hash="x", status="online", last_seen_at=now - timedelta(days=seen_days_ago),
                inventory=[{"name": "Edge"}] if inventory else None,
                inventory_collected_at=now - timedelta(days=seen_days_ago) if inventory else None,
            ))
            uow.session.flush()


def _evidence(client, headers):
    return {item["title"]: item for item in client.get(_URL, headers=headers).get_json()["evidence"]
            if item["providerKey"] == "hygeia.asset_inventory"}


def test_without_assets_the_control_says_there_is_no_data(client, adopted, auth_headers):
    assert [i["status"] for i in _evidence(client, auth_headers(adopted)).values()] == ["missing"]


def test_reporting_assets_are_fine(app, client, adopted, auth_headers):
    _asset(app, adopted.id)
    _asset(app, adopted.id, seen_days_ago=2)

    found = _evidence(client, auth_headers(adopted))

    assert found["Activos monitorizados"]["status"] == "ok"
    assert found["Activos monitorizados"]["summary"].startswith("2 activo(s); 2 han reportado")
    assert found["Inventario de software"]["dataDate"] is not None


def test_assets_that_stopped_reporting_raise_a_warning(app, client, adopted, auth_headers):
    _asset(app, adopted.id)
    _asset(app, adopted.id, seen_days_ago=20)

    found = _evidence(client, auth_headers(adopted))

    assert found["Activos monitorizados"]["status"] == "warning"
    assert "1 no" in found["Activos monitorizados"]["summary"]


def test_an_organization_owner_counts_the_assets_of_the_members(app, client, adopted, regular_user, auth_headers):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    org = client.post("/organizations", headers=auth_headers(adopted), json={"name": "Acme"}).get_json()
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=org["id"], user_id=regular_user.id, member_role="member"))
            uow.session.flush()
    _asset(app, adopted.id)
    _asset(app, regular_user.id)

    found = _evidence(client, auth_headers(adopted))

    assert found["Activos monitorizados"]["summary"].startswith("2 activo(s)")


def test_a_stranger_assets_are_not_counted(app, client, adopted, make_user, auth_headers):
    _asset(app, make_user().id)

    assert [i["status"] for i in _evidence(client, auth_headers(adopted)).values()] == ["missing"]
