"""Preferencias de marcos de cumplimiento: del usuario y, por encima, de su organización."""

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


@pytest.fixture()
def organization_with_member(client, app, owner, make_user, auth_headers):
    """Una organización de ``owner`` con un miembro; devuelve ``(owner, member)``."""
    from src.modules.accounts.model import OrganizationMember

    organization = client.post("/organizations", headers=auth_headers(owner),
                               json={"name": "Acme"}).get_json()
    member = make_user()
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(
                organization_id=organization["id"], user_id=member.id, member_role="member",
            ))
            uow.session.flush()
    return owner, member


def _put(client, headers, path, frameworks):
    return client.put(f"/themis/compliance/{path}", headers=headers, json={"frameworks": frameworks})


def test_a_new_user_has_chosen_nothing(client, regular_user, auth_headers):
    body = client.get("/themis/compliance", headers=auth_headers(regular_user)).get_json()
    assert {framework["key"] for framework in body["frameworks"]} == {"iso27001", "ens", "nis2"}
    assert body["mine"] is None
    assert body["effective"] == []
    assert body["isLockedByOrganization"] is False


def test_a_user_chooses_and_clears_their_frameworks(client, regular_user, auth_headers):
    headers = auth_headers(regular_user)
    body = _put(client, headers, "frameworks", ["ens", "iso27001", "ens"]).get_json()
    assert body["mine"] == ["ens", "iso27001"]
    assert body["effective"] == ["ens", "iso27001"]

    body = _put(client, headers, "frameworks", None).get_json()
    assert body["mine"] is None
    assert body["effective"] == []


def test_an_unknown_framework_is_rejected(client, regular_user, auth_headers):
    response = _put(client, auth_headers(regular_user), "frameworks", ["pci"])
    assert response.status_code == 422


def test_the_organization_overrides_its_members(client, organization_with_member, auth_headers):
    owner, member = organization_with_member
    _put(client, auth_headers(member), "frameworks", ["iso27001"])

    assert _put(client, auth_headers(owner), "organization-frameworks", ["ens"]).status_code == 200

    body = client.get("/themis/compliance", headers=auth_headers(member)).get_json()
    assert body["mine"] == ["iso27001"]
    assert body["organization"] == ["ens"]
    assert body["effective"] == ["ens"]
    assert body["isLockedByOrganization"] is True
    assert body["canManageOrganization"] is False


def test_releasing_the_organization_restores_the_members_choice(client, organization_with_member, auth_headers):
    owner, member = organization_with_member
    _put(client, auth_headers(member), "frameworks", ["iso27001"])
    _put(client, auth_headers(owner), "organization-frameworks", ["ens"])

    _put(client, auth_headers(owner), "organization-frameworks", None)

    body = client.get("/themis/compliance", headers=auth_headers(member)).get_json()
    assert body["effective"] == ["iso27001"]
    assert body["isLockedByOrganization"] is False


def test_an_empty_organization_choice_still_locks_the_members(client, organization_with_member, auth_headers):
    owner, member = organization_with_member
    _put(client, auth_headers(member), "frameworks", ["iso27001"])
    _put(client, auth_headers(owner), "organization-frameworks", [])

    body = client.get("/themis/compliance", headers=auth_headers(member)).get_json()
    assert body["effective"] == []
    assert body["isLockedByOrganization"] is True


def test_only_the_owner_sets_the_organization_frameworks(client, organization_with_member, regular_user,
                                                         auth_headers):
    _, member = organization_with_member
    for user in (member, regular_user):
        response = _put(client, auth_headers(user), "organization-frameworks", ["ens"])
        assert response.status_code == 403
        assert response.get_json()["messageKey"] == "complianceOrganizationOwnerOnly"


def test_the_preferences_require_the_themis_read_attribute(client, stripped_user, auth_headers):
    assert client.get("/themis/compliance", headers=auth_headers(stripped_user)).status_code == 403
