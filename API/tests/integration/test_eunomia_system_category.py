"""La categoría del sistema en la adopción del ENS: qué se exige y qué cuenta en el cumplimiento."""

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


def _adopt(client, headers, key="ens", **body):
    return client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": key, **body})


def _node(tree, identifier):
    for node in tree:
        if node["identifier"] == identifier:
            return node
        found = _node(node["children"], identifier)
        if found:
            return found
    return None


def test_the_ens_is_adopted_with_its_category_and_lists_the_ones_it_admits(client, owner, auth_headers):
    response = _adopt(client, auth_headers(owner), systemCategory="basic")

    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["systemCategory"] == "basic"
    assert body["categories"] == ["basic", "medium", "high"]


def test_a_framework_without_categories_rejects_one(client, owner, auth_headers):
    response = _adopt(client, auth_headers(owner), "nis2", systemCategory="basic")

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "systemCategoryNotSupported"


def test_an_unknown_category_is_a_validation_error(client, owner, auth_headers):
    assert _adopt(client, auth_headers(owner), systemCategory="extreme").status_code in (400, 422)


def test_the_tree_says_what_is_required_and_the_progress_only_counts_that(client, owner, auth_headers):
    headers = auth_headers(owner)
    _adopt(client, headers, systemCategory="basic")

    tree = client.get("/eunomia/adoptions/ens/tree", headers=headers).get_json()
    assert tree["systemCategory"] == "basic"
    assert _node(tree["tree"], "mp.info.3")["applicability"] == "required"
    assert _node(tree["tree"], "mp.info.3.r1")["applicability"] == "not_required"
    assert _node(tree["tree"], "mp.info.3.r5")["applicability"] == "optional"
    assert _node(tree["tree"], "mp.info")["applicability"] is None

    basic_total = client.get("/eunomia/adoptions/ens/summary", headers=headers).get_json()["global"]["total"]
    changed = client.patch("/eunomia/adoptions/ens", headers=headers, json={"systemCategory": "high"})
    assert changed.status_code == 200, changed.get_json()
    assert changed.get_json()["systemCategory"] == "high"
    high_total = client.get("/eunomia/adoptions/ens/summary", headers=headers).get_json()["global"]["total"]

    assert basic_total < high_total
    listed = client.get("/eunomia/adoptions", headers=headers).get_json()["adoptions"][0]
    assert listed["progress"]["total"] == high_total


def test_without_a_category_everything_counts_as_before(client, owner, auth_headers):
    headers = auth_headers(owner)
    _adopt(client, headers)

    tree = client.get("/eunomia/adoptions/ens/tree", headers=headers).get_json()
    summary = client.get("/eunomia/adoptions/ens/summary", headers=headers).get_json()

    assert tree["systemCategory"] is None
    assert _node(tree["tree"], "mp.info.3.r5")["applicability"] == "required"
    assert summary["global"]["total"] == 206


def test_changing_the_category_needs_an_adopted_framework_that_has_them(client, owner, auth_headers):
    headers = auth_headers(owner)
    assert client.patch("/eunomia/adoptions/ens", headers=headers, json={"systemCategory": "basic"}).status_code == 404

    _adopt(client, headers, "nis2")
    rejected = client.patch("/eunomia/adoptions/nis2", headers=headers, json={"systemCategory": "basic"})
    assert rejected.status_code == 400
    assert rejected.get_json()["messageKey"] == "systemCategoryNotSupported"


def test_a_member_cannot_change_the_category(client, app, owner, regular_user, auth_headers):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    org = client.post("/organizations", headers=auth_headers(owner), json={"name": "Acme"}).get_json()
    _adopt(client, auth_headers(owner), systemCategory="basic")
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=org["id"], user_id=regular_user.id, member_role="member"))
            uow.session.flush()

    denied = client.patch("/eunomia/adoptions/ens", headers=auth_headers(regular_user), json={"systemCategory": "high"})

    assert denied.status_code == 403
