"""Adoptar marcos: versión fijada, cuota, un solo dueño efectivo y miembros en solo lectura."""

from datetime import timedelta

import pytest

from src.modules.accounts.services.limits import LimitKey
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


def _join(app, organization_id, user_id):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=organization_id, user_id=user_id, member_role="member"))
            uow.session.flush()


def _adopt(client, headers, key="nis2"):
    return client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": key})


def test_adopting_pins_the_current_catalog_version(client, owner, auth_headers):
    response = _adopt(client, auth_headers(owner))

    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["frameworkKey"] == "nis2"
    assert body["catalogVersion"] == body["currentVersion"] == "2022-2555"
    assert body["status"] == "active"
    assert body["hasNewerVersion"] is False


def test_adopting_the_same_framework_twice_is_rejected(client, owner, auth_headers):
    _adopt(client, auth_headers(owner))
    second = _adopt(client, auth_headers(owner))

    assert second.status_code == 409
    assert second.get_json()["messageKey"] == "frameworkAlreadyAdopted"


def test_an_unknown_framework_is_a_404(client, owner, auth_headers):
    assert _adopt(client, auth_headers(owner), "no-existe").status_code == 404


def test_the_free_plan_allows_one_framework_and_the_second_is_a_402(
    client, regular_user, make_subscription, auth_headers,
):
    make_subscription(regular_user, plan_code="freemium")
    headers = auth_headers(regular_user)
    assert _adopt(client, headers, "nis2").status_code == 201

    second = _adopt(client, headers, "ens")

    assert second.status_code == 402
    assert second.get_json()["messageKey"] == "quotaExceeded"


def test_a_member_sees_the_frameworks_of_the_owner_and_cannot_adopt(
    client, app, owner, regular_user, auth_headers,
):
    org = client.post("/organizations", headers=auth_headers(owner), json={"name": "Acme"}).get_json()
    _adopt(client, auth_headers(owner), "nis2")
    _join(app, org["id"], regular_user.id)

    listing = client.get("/eunomia/adoptions", headers=auth_headers(regular_user)).get_json()
    assert [item["frameworkKey"] for item in listing["adoptions"]] == ["nis2"]
    assert listing["ownership"]["isOwnData"] is False

    denied = _adopt(client, auth_headers(regular_user), "ens")
    assert denied.status_code == 403
    assert denied.get_json()["messageKey"] == "dataOwnedByOrganization"


def test_a_member_does_not_consume_their_own_quota_for_the_owner_frameworks(
    client, app, owner, regular_user, auth_headers,
):
    org = client.post("/organizations", headers=auth_headers(owner), json={"name": "Acme"}).get_json()
    _join(app, org["id"], regular_user.id)

    for key in ("nis2", "ens"):
        assert _adopt(client, auth_headers(owner), key).status_code == 201

    keys = [a["frameworkKey"] for a in client.get("/eunomia/adoptions", headers=auth_headers(owner)).get_json()["adoptions"]]
    assert keys == ["nis2", "ens"]


def test_the_quota_counter_only_counts_active_adoptions(app, client, owner, auth_headers):
    from src.modules.accounts.services.limits import STOCK_COUNTERS
    from src.modules.infrastructure import unit_of_work

    _adopt(client, auth_headers(owner))
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            assert STOCK_COUNTERS[LimitKey.EUNOMIA_FRAMEWORKS](uow.session, [owner.id]) == 1
