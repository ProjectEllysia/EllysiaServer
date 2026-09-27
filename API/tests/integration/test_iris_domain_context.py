"""Contexto de infraestructura de un dominio (RDAP): caché, cupo y modo neutro.

La consulta RDAP se sustituye en la costura (``lookup_domain``): lo que se
prueba es el camino del manager —solo dominios del usuario, caché con
caducidad, cupo por proveedor, degradación a neutro sin red y la superficie
``externalEnrichment`` cerrada en vista previa— y que un dominio recién
registrado es solo contexto: no cambia ningún veredicto.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.iris.model import IrisAnalysis, IrisIndicator
from src.modules.features.iris.repositories import IrisAnalysisRepository, IrisIndicatorRepository
from src.modules.features.iris.services.enrichment.policy import RATE_LIMITER
from src.modules.features.iris.services.enrichment.rdap import (
    DomainContext,
    DomainRegistration,
    NetworkRegistration,
    parse_domain_response,
    parse_ip_response,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_LOOKUP = "src.modules.features.iris.managers.enrichment.lookup_domain"

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (AttributeType.IRIS_READ, AttributeType.IRIS_CREATE)]


def _context(days_old: int = 3) -> DomainContext:
    return DomainContext(
        registration=DomainRegistration(
            registered_at=utcnow_naive() - timedelta(days=days_old), expires_at=datetime(2027, 1, 1),
            registrar="Registrador Ejemplo", statuses=("client transfer prohibited",),
            nameservers=("ns1.evil.example",),
        ),
        network=NetworkRegistration(address="93.184.216.34", name="EDGECAST", country="US", asn="AS15133"),
    )


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    RATE_LIMITER.reset()
    yield
    RATE_LIMITER.reset()


@pytest.fixture
def analyst(app, make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers="From: a@login.evil.example\n", user_id=user.id,
                                    status="finished", verdict="Phishing", total_score=10.0)
            IrisAnalysisRepository(uow).save(analysis)
            IrisIndicatorRepository(uow).save(IrisIndicator(analysis_id=analysis.id, kind="domain",
                                                            value="login.evil.example"))
    return user, auth_headers(user)


def test_the_context_of_a_domain_of_the_user(client, analyst):
    _, headers = analyst
    with patch(_LOOKUP, return_value=_context()) as lookup:
        body = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()

    lookup.assert_called_once()
    assert lookup.call_args.args[0] == "evil.example"
    assert body["status"] == "ok" and body["registrableDomain"] == "evil.example"
    assert body["ageDays"] == 3 and body["isRecentlyRegistered"] is True
    assert body["registrar"] == "Registrador Ejemplo" and body["country"] == "US" and body["asn"] == "AS15133"


def test_a_defanged_domain_is_accepted(client, analyst):
    _, headers = analyst
    with patch(_LOOKUP, return_value=_context()):
        assert client.get("/iris/domains/login.evil[.]example/context", headers=headers).status_code == 200


def test_a_domain_the_user_never_saw_is_not_looked_up(client, analyst):
    _, headers = analyst
    with patch(_LOOKUP) as lookup:
        response = client.get("/iris/domains/google.com/context", headers=headers)

    assert response.status_code == 404
    lookup.assert_not_called()


def test_the_answer_is_cached_until_it_expires(client, analyst):
    _, headers = analyst
    with patch(_LOOKUP, return_value=_context()) as lookup:
        first = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()
        second = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()

    assert lookup.call_count == 1
    assert first["cached"] is False and second["cached"] is True


def test_a_provider_down_degrades_to_neutral_and_is_remembered_briefly(client, analyst):
    _, headers = analyst
    with patch(_LOOKUP, return_value=DomainContext(error="timeout")) as lookup:
        first = client.get("/iris/domains/login.evil.example/context", headers=headers)
        second = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()

    assert first.status_code == 200
    assert first.get_json()["status"] == "unavailable" and first.get_json()["error"] == "timeout"
    assert first.get_json()["registrar"] is None and first.get_json()["ageDays"] is None
    assert second["cached"] is True and lookup.call_count == 1


def test_the_rate_limit_answers_without_asking(client, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.setattr(CR, "iris_rdap_config", lambda: CR.IrisRdapConfig(requests_per_minute=0))
    with patch(_LOOKUP) as lookup:
        body = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()

    assert body["status"] == "rate_limited"
    lookup.assert_not_called()


def test_disabled_enrichment_makes_no_request(client, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.setattr(CR, "iris_enrichment_config", lambda: CR.IrisEnrichmentConfig(enabled=False))
    with patch(_LOOKUP) as lookup:
        body = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()

    assert body["status"] == "disabled"
    lookup.assert_not_called()


def test_the_surface_is_closed_in_preview(client, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.delenv("LAUNCH_MODE", raising=False)
    monkeypatch.setattr(CR, "launch_config", lambda: CR.LaunchConfig(
        configured_mode="preview", surfaces={surface.value: True for surface in CR.LaunchSurface}))
    with patch(_LOOKUP) as lookup:
        response = client.get("/iris/domains/login.evil.example/context", headers=headers)

    assert response.status_code == 403 and response.get_json()["details"]["surface"] == "externalEnrichment"
    lookup.assert_not_called()


def test_an_old_legitimate_looking_domain_is_not_flagged_as_recent(client, analyst):
    _, headers = analyst
    with patch(_LOOKUP, return_value=_context(days_old=4000)):
        body = client.get("/iris/domains/login.evil.example/context", headers=headers).get_json()

    assert body["isRecentlyRegistered"] is False and body["ageDays"] == 4000


def test_rdap_responses_are_parsed():
    registration = parse_domain_response({
        "events": [{"eventAction": "registration", "eventDate": "2026-09-20T10:00:00Z"},
                   {"eventAction": "expiration", "eventDate": "2027-09-20T10:00:00+02:00"}],
        "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                                                        ["fn", {}, "text", "Ejemplo SL"]]]}],
        "status": ["active"],
        "nameservers": [{"ldhName": "NS1.Evil.Example."}],
    })
    network = parse_ip_response("93.184.216.34", {"name": "NET", "country": "us",
                                                   "arin_originas0_originautnums": [15133]})

    assert registration.registered_at == datetime(2026, 9, 20, 10, 0)
    assert registration.expires_at == datetime(2027, 9, 20, 8, 0)
    assert registration.registrar == "Ejemplo SL" and registration.nameservers == ("ns1.evil.example",)
    assert network.country == "US" and network.asn == "AS15133"
