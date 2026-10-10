"""Los marcos de los informes de Lybra son los adoptados en Eunomia, con la regla del dueño efectivo."""

from datetime import timedelta

import pytest

from src.modules.infrastructure import unit_of_work
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

FUTURE = utcnow_naive() + timedelta(days=30)


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=FUTURE)
    return user


def _effective_keys(app, user_id):
    from src.modules.features.themis.services.reports.findings import effective_frameworks

    with app.app_context():
        return [framework.key for framework in effective_frameworks(user_id)]


def test_a_user_who_adopted_nothing_gets_reports_without_frameworks(app, regular_user):
    assert _effective_keys(app, regular_user.id) == []


def test_the_reports_use_the_frameworks_the_user_adopted(client, app, owner, auth_headers):
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "nis2"})
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "iso27001"})

    # En el orden del catálogo, no en el de adopción.
    assert _effective_keys(app, owner.id) == ["iso27001", "nis2"]


def test_a_removed_framework_disappears_from_the_reports(client, app, owner, auth_headers):
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "nis2"})
    client.delete("/eunomia/adoptions/nis2", headers=auth_headers(owner))

    assert _effective_keys(app, owner.id) == []


def test_a_member_gets_the_frameworks_of_the_owner(client, app, owner, regular_user, auth_headers):
    from src.modules.accounts.model import OrganizationMember

    organization = client.post("/organizations", headers=auth_headers(owner), json={"name": "Acme"}).get_json()
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "ens"})
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(
                organization_id=organization["id"], user_id=regular_user.id, member_role="member",
            ))
            uow.session.flush()

    assert _effective_keys(app, regular_user.id) == ["ens"]


def test_the_old_selection_endpoints_are_gone(client, regular_user, auth_headers):
    headers = auth_headers(regular_user)

    assert client.get("/themis/compliance", headers=headers).status_code == 404
    assert client.put("/themis/compliance/frameworks", headers=headers, json={"frameworks": []}).status_code in (404, 405)
