"""Inteligencia compartida en una organización: agregados, consentimiento y fronteras.

Monta dos organizaciones con varios miembros y fija el criterio de cierre: los
miembros que consienten comparten agregados anonimizados —recuentos por
indicador y por dominio, nunca quién ni qué análisis— sin que un correo cruce
de un miembro a otro ni nada cruce de una organización a otra.
"""

from __future__ import annotations

import json

import pytest

from src.modules.accounts.model import Organization, OrganizationMember
from src.modules.features.iris.model import IrisAnalysis, IrisCommunicationEdge, IrisIndicator
from src.modules.features.iris.repositories import IrisAnalysisRepository
from src.modules.features.iris.services.tenant import find_imitated_protected, normalize_protected_domains
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE, AttributeType.IRIS_UPDATE,
)]
_EVIL = "acme-nominas.example"
_SECRET_TITLE = "Nomina de Ana Garcia"


def _organization(app, make_user, slug: str, size: int):
    """Una organización con su dueño y ``size - 1`` miembros más."""
    users = [make_user(role="role_user", attributes=_IRIS_ATTRIBUTES) for _ in range(size)]
    with app.app_context():
        with UnitOfWork() as uow:
            organization = Organization(name=slug.title(), slug=slug, owner_user_id=users[0].id)
            uow.session.add(organization)
            uow.session.flush()
            for position, user in enumerate(users):
                uow.session.add(OrganizationMember(organization_id=organization.id, user_id=user.id,
                                                   member_role="owner" if position == 0 else "member"))
    return users


def _phishing_seen_by(app, user_id: int, domain: str = _EVIL, verdict: str = "Phishing") -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers=f"Subject: {_SECRET_TITLE}\n", title=_SECRET_TITLE,
                                    user_id=user_id, status="finished", verdict=verdict, total_score=10.0)
            IrisAnalysisRepository(uow).save(analysis)
            uow.session.add(IrisIndicator(analysis_id=analysis.id, kind="domain", value=domain))
            uow.session.add(IrisIndicator(analysis_id=analysis.id, kind="email", value=f"ceo@{domain}"))
            return analysis.id


def _legitimate_sender(app, user_id: int, domain: str) -> None:
    with app.app_context():
        with UnitOfWork() as uow:
            now = utcnow_naive()
            uow.session.add(IrisCommunicationEdge(
                user_id=user_id, sender_address=f"jefa@{domain}", sender_domain=domain,
                recipient_address=f"u{user_id}@acme.example", kind="to", message_count=4, legitimate_count=4,
                first_seen_at=now, last_seen_at=now,
            ))


def _share(client, auth_headers, owner, domains=()):
    response = client.put("/iris/organization/intel/policy", headers=auth_headers(owner),
                          json={"sharingEnabled": True, "protectedDomains": list(domains)})
    assert response.status_code == 200, response.get_json()


def _consent(client, auth_headers, user, consent=True):
    return client.put("/iris/organization/intel/consent", headers=auth_headers(user), json={"consent": consent})


def test_consenting_members_share_anonymised_aggregates(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 3)
    _share(client, auth_headers, users[0], domains=["acme.example"])
    for user in users:
        _consent(client, auth_headers, user)
        _phishing_seen_by(app, user.id)
        _legitimate_sender(app, user.id, "proveedor.example")

    body = client.get("/iris/organization/intel", headers=auth_headers(users[1])).get_json()

    assert body["contributingMembers"] == 3
    assert body["sharedIndicators"] == [{
        "kind": "domain", "value": _EVIL, "memberCount": 3, "analysisCount": 3,
        "firstSeenAt": body["sharedIndicators"][0]["firstSeenAt"],
        "lastSeenAt": body["sharedIndicators"][0]["lastSeenAt"],
        "imitatesProtected": "acme.example",
    }]
    assert body["frequentDomains"] == [{"domain": "proveedor.example", "memberCount": 3, "legitimateMessages": 12}]
    serialized = json.dumps(body)
    assert _SECRET_TITLE not in serialized and "ceo@" not in serialized and "jefa@" not in serialized
    identifying = {"userId", "userIds", "analysisId", "analysisIds", "username", "email"}
    assert not identifying & {key for item in body["sharedIndicators"] + body["frequentDomains"] for key in item}


def test_what_fewer_members_than_the_minimum_saw_is_not_shared(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 3)
    _share(client, auth_headers, users[0])
    for user in users:
        _consent(client, auth_headers, user)
    _phishing_seen_by(app, users[0].id)
    _phishing_seen_by(app, users[1].id)

    assert client.get("/iris/organization/intel", headers=auth_headers(users[2])).get_json()["sharedIndicators"] == []


def test_without_consent_a_member_neither_contributes_nor_sees(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 4)
    _share(client, auth_headers, users[0])
    for user in users[:3]:
        _consent(client, auth_headers, user)
        _phishing_seen_by(app, user.id)
    _phishing_seen_by(app, users[3].id, domain="solo-del-que-no-consiente.example")

    outsider = client.get("/iris/organization/intel", headers=auth_headers(users[3])).get_json()
    insider = client.get("/iris/organization/intel", headers=auth_headers(users[0])).get_json()

    assert outsider["hasConsented"] is False and outsider["sharedIndicators"] == []
    assert [indicator["value"] for indicator in insider["sharedIndicators"]] == [_EVIL]
    assert insider["contributingMembers"] == 3


def test_withdrawing_consent_removes_the_member_at_once(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 3)
    _share(client, auth_headers, users[0])
    for user in users:
        _consent(client, auth_headers, user)
        _phishing_seen_by(app, user.id)

    _consent(client, auth_headers, users[2], consent=False)

    body = client.get("/iris/organization/intel", headers=auth_headers(users[0])).get_json()
    assert body["contributingMembers"] == 2 and body["sharedIndicators"] == []


def test_two_organizations_never_mix(client, app, make_user, auth_headers):
    acme = _organization(app, make_user, "acme", 3)
    globex = _organization(app, make_user, "globex", 3)
    for organization in (acme, globex):
        _share(client, auth_headers, organization[0])
    for user in acme + globex[:1]:
        _consent(client, auth_headers, user)
        _phishing_seen_by(app, user.id)

    globex_view = client.get("/iris/organization/intel", headers=auth_headers(globex[0])).get_json()

    assert globex_view["contributingMembers"] == 1 and globex_view["sharedIndicators"] == []


def test_the_report_counts_other_members_who_saw_the_indicators(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 3)
    _share(client, auth_headers, users[0])
    for user in users:
        _consent(client, auth_headers, user)
    analysis_ids = [_phishing_seen_by(app, user.id) for user in users]

    report = client.get(f"/iris/results/{analysis_ids[0]}", headers=auth_headers(users[0])).get_json()

    assert report["organizationSightings"] == {
        "minMembers": 3, "indicators": [{"kind": "domain", "value": _EVIL, "memberCount": 3}],
    }


def test_only_the_owner_sets_the_policy(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 2)

    response = client.put("/iris/organization/intel/policy", headers=auth_headers(users[1]),
                          json={"sharingEnabled": True})

    assert response.status_code == 403
    assert response.get_json()["messageKey"] == "irisTenantOwnerRequired"


def test_sharing_is_off_until_the_owner_turns_it_on(client, app, make_user, auth_headers):
    users = _organization(app, make_user, "acme", 3)
    for user in users:
        _consent(client, auth_headers, user)
        _phishing_seen_by(app, user.id)

    body = client.get("/iris/organization/intel", headers=auth_headers(users[0])).get_json()

    assert body["sharingEnabled"] is False and body["sharedIndicators"] == []


def test_a_user_without_organization_gets_a_clear_answer(client, make_user, auth_headers):
    loner = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)

    response = client.get("/iris/organization/intel", headers=auth_headers(loner))

    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisNotInOrganization"


def test_protected_domains_are_validated_and_lookalikes_found():
    assert normalize_protected_domains(["WWW.Acme.example.", "acme.example"]) == ["acme.example"]
    with pytest.raises(ValueError):
        normalize_protected_domains(["no es un dominio"])
    assert find_imitated_protected("domain", "acrne.example", ["acme.example"]) is None
    assert find_imitated_protected("url", "https://acme-login.example/x", ["acme.example"]) == "acme.example"
    assert find_imitated_protected("domain", "mail.acme.example", ["acme.example"]) is None
    assert find_imitated_protected("domain", "acne.example", ["acme.example"]) == "acme.example"
