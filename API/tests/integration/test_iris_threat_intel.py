"""Reputación de un indicador: caché, cupo, degradación y que el correo no sale.

Ejecuta el catálogo real sobre un correo con datos sensibles y consulta la
reputación de su URL con los cuatro proveedores encendidos. La red se
sustituye en ``threat_intel.base.fetch``, que ve todo lo que se envía: así se
comprueba que a los proveedores solo les llega el indicador y su clave.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.iris.managers.analysis import _run_analysis
from src.modules.features.iris.model import IrisAnalysis
from src.modules.features.iris.repositories import IrisAnalysisRepository
from src.modules.features.iris.services.enrichment.egress import EgressResponse
from src.modules.features.iris.services.enrichment.policy import RATE_LIMITER
from src.modules.infrastructure import UnitOfWork
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_FETCH = "src.modules.features.iris.services.enrichment.threat_intel.base.fetch"
_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (AttributeType.IRIS_READ, AttributeType.IRIS_CREATE)]
_URL = "http://paypa1-secure.example/login"
_SECRET = "Nomina de Ana Garcia IBAN ES7620770024003102575766"
_RAW = (
    "From: Soporte <avisos@paypa1-secure.example>\r\n"
    "To: ana@corp.example\r\n"
    f"Subject: {_SECRET}\r\n"
    "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
    "Message-ID: <1@paypa1-secure.example>\r\n"
    "Content-Type: text/html; charset=utf-8\r\n\r\n"
    f"<p>{_SECRET}</p><a href=\"{_URL}\">Pagar</a>\r\n"
)
_ALL_ON = {name: {"enabled": True, "requestsPerMinute": 30} for name in ("virustotal", "urlscan", "phishtank", "urlhaus")}


class _Web:
    """Proveedores falsos que recuerdan todo lo que se les envía."""

    def __init__(self):
        self.requests = []

    def __call__(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        if "virustotal" in url:
            payload = {"data": {"attributes": {"last_analysis_stats": {"malicious": 7, "suspicious": 0}}}}
        elif "urlscan" in url:
            payload = {"total": 0}
        elif "phishtank" in url:
            payload = {"results": {"in_database": False}}
        else:
            payload = {"query_status": "ok", "url_status": "online"}
        return EgressResponse(url=url, status=200, headers={}, body=json.dumps(payload).encode(),
                              is_truncated=False, peer_address="93.184.216.34")


@pytest.fixture(autouse=True)
def _providers(monkeypatch):
    RATE_LIMITER.reset()
    for name in _ALL_ON:
        monkeypatch.setenv(f"IRIS_{name.upper()}_API_KEY", f"key-{name}")
    monkeypatch.setattr(CR, "iris_threat_intel_config", lambda: CR.IrisThreatIntelConfig(providers=_ALL_ON))
    yield
    RATE_LIMITER.reset()


@pytest.fixture
def analyst(app, make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers=_RAW, user_id=user.id, status="pending")
            IrisAnalysisRepository(uow).save(analysis)
            analysis_id = analysis.id
        _run_analysis(analysis_id, _RAW)
    return user, auth_headers(user)


def _reputation(client, headers, kind="url", value=_URL):
    return client.post("/iris/indicators/reputation", headers=headers, json={"kind": kind, "value": value})


def test_every_provider_answers_with_a_common_verdict(client, analyst):
    _, headers = analyst
    with patch(_FETCH, _Web()):
        body = _reputation(client, headers).get_json()

    by_provider = {result["provider"]: result["verdict"] for result in body["providers"]}
    assert by_provider == {"phishtank": "unknown", "urlhaus": "known_malicious",
                           "urlscan": "unknown", "virustotal": "known_malicious"}
    assert body["verdict"] == "known_malicious" and body["status"] == "ok"


def test_only_the_indicator_and_the_key_leave_the_server(client, analyst):
    _, headers = analyst
    web = _Web()
    with patch(_FETCH, web):
        _reputation(client, headers)

    assert len(web.requests) == 4
    for request in web.requests:
        sent = json.dumps({key: (value.decode() if isinstance(value, bytes) else value)
                           for key, value in request.items()}, ensure_ascii=False)
        assert "Garcia" not in sent and "ES7620770024003102575766" not in sent and "ana@corp" not in sent


def test_answers_are_cached(client, analyst):
    _, headers = analyst
    web = _Web()
    with patch(_FETCH, web):
        _reputation(client, headers)
        second = _reputation(client, headers).get_json()

    assert len(web.requests) == 4
    assert all(result["cached"] for result in second["providers"])


def test_a_provider_without_quota_is_not_asked(client, analyst, monkeypatch):
    _, headers = analyst
    quotas = {**_ALL_ON, "virustotal": {"enabled": True, "requestsPerMinute": 0}}
    monkeypatch.setattr(CR, "iris_threat_intel_config", lambda: CR.IrisThreatIntelConfig(providers=quotas))
    web = _Web()
    with patch(_FETCH, web):
        body = _reputation(client, headers).get_json()

    assert not any("virustotal" in request["url"] for request in web.requests)
    assert next(result for result in body["providers"] if result["provider"] == "virustotal")["verdict"] \
        == "rate_limited"


def test_providers_down_degrade_to_neutral(client, analyst):
    _, headers = analyst

    def down(url, **kwargs):
        raise ConnectionRefusedError

    with patch(_FETCH, down):
        body = _reputation(client, headers).get_json()

    assert body["verdict"] == "unavailable"
    assert {result["verdict"] for result in body["providers"]} == {"unavailable"}


def test_without_keys_nothing_is_configured(client, analyst, monkeypatch):
    _, headers = analyst
    for name in _ALL_ON:
        monkeypatch.delenv(f"IRIS_{name.upper()}_API_KEY")
    with patch(_FETCH) as fetch:
        body = _reputation(client, headers).get_json()

    fetch.assert_not_called()
    assert body["status"] == "not_configured" and body["providers"] == []


def test_an_indicator_that_is_not_the_users_is_not_sent(client, analyst):
    _, headers = analyst
    with patch(_FETCH) as fetch:
        response = _reputation(client, headers, "domain", "google.com")

    assert response.status_code == 404
    fetch.assert_not_called()
