"""Expansión de URLs: a dónde lleva de verdad un enlace de un correo.

Recorre el camino completo —petición, job encolado por la outbox, worker— con
la red sustituida en la costura más baja (``egress.fetch``), así que la
cadena de redirects, las comprobaciones de cada salto y el resumen final son
los reales. Fija que la expansión es explícita, que solo se sigue una URL del
propio análisis, que un redirect hacia la red interna se corta, y que el
resultado es de un solo usuario.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.iris.managers.url_expansion import IrisUrlExpansionManager
from src.modules.features.iris.model import IrisAnalysis, IrisIndicator, IrisUrlExpansion
from src.modules.features.iris.repositories import IrisAnalysisRepository, IrisIndicatorRepository
from src.modules.features.iris.services.enrichment import egress
from src.modules.features.iris.services.enrichment.egress import EgressBlockedError, EgressResponse
from src.modules.features.iris.services.enrichment.policy import RATE_LIMITER
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (AttributeType.IRIS_READ, AttributeType.IRIS_CREATE)]
_SHORT = "https://bit.example/Ab3"


def _response(url, status, location=None, body=b"", content_type="text/html"):
    headers = {"content-type": content_type}
    if location:
        headers["location"] = location
    return EgressResponse(url=url, status=status, headers=headers, body=body, is_truncated=False,
                          peer_address="93.184.216.34", certificate={"subject": "CN=x", "issuer": "CN=ca",
                                                                     "notBefore": "", "notAfter": ""})


def _web(url, **kwargs):
    """Una pequeña web falsa: el acortador redirige a un login de otro dominio."""
    if url == _SHORT:
        return _response(url, 301, "https://login-microsoft.evil.example/auth")
    if url == "https://login-microsoft.evil.example/auth":
        return _response(url, 200, body=b"<html><title>Iniciar sesi&oacute;n - Microsoft</title></html>")
    raise EgressBlockedError("private_address", url)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    RATE_LIMITER.reset()
    yield
    RATE_LIMITER.reset()


def _analysis_with_urls(app, user_id: int, *urls: str) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers="From: a@b.example\n", user_id=user_id, status="finished",
                                    verdict="Phishing", total_score=10.0)
            IrisAnalysisRepository(uow).save(analysis)
            for url in urls:
                IrisIndicatorRepository(uow).save(IrisIndicator(analysis_id=analysis.id, kind="url", value=url.lower()))
            return analysis.id


def _run_pending_jobs(app):
    with app.app_context():
        pending = [expansion.id for expansion in build_repository(IrisAnalysisRepository)._session
                   .query(IrisUrlExpansion).filter(IrisUrlExpansion.status == "pending").all()]
    for expansion_id in pending:
        with app.app_context():
            IrisUrlExpansionManager.execute_url_expansion(expansion_id)


@pytest.fixture
def analyst(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    return user, auth_headers(user)


def test_nothing_is_followed_until_asked(client, app, analyst):
    user, headers = analyst
    analysis_id = _analysis_with_urls(app, user.id, _SHORT)

    listing = client.get(f"/iris/results/{analysis_id}/url-expansions", headers=headers).get_json()

    assert listing["expansions"] == [pytest.approx(listing["expansions"][0])]
    assert listing["expansions"][0]["status"] == "not_requested"


def test_a_shortener_is_followed_hop_by_hop_to_its_real_destination(client, app, analyst):
    user, headers = analyst
    analysis_id = _analysis_with_urls(app, user.id, _SHORT)

    queued = client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers, json={"url": _SHORT})
    assert queued.status_code == 202 and queued.get_json()["status"] == "pending"
    with patch.object(egress, "fetch", _web):
        _run_pending_jobs(app)

    expansion = client.get(f"/iris/results/{analysis_id}/url-expansions", headers=headers).get_json()["expansions"][0]
    assert expansion["status"] == "done"
    assert [hop["status"] for hop in expansion["hops"]] == [301, 200]
    assert expansion["finalDomain"] == "login-microsoft.evil.example"
    assert expansion["isDomainChanged"] is True
    assert expansion["pageTitle"] == "Iniciar sesión - Microsoft"
    assert expansion["hops"][0]["certificate"]["issuer"] == "CN=ca"


def test_a_redirect_into_the_internal_network_is_cut(client, app, analyst):
    """El segundo salto pasa por el ``fetch`` real, que resuelve y lo bloquea sin conectar."""
    user, headers = analyst
    url = "https://redirect.evil.example/x"
    analysis_id = _analysis_with_urls(app, user.id, url)
    real_fetch = egress.fetch

    def web(requested, **kwargs):
        if requested == url:
            return _response(requested, 302, "http://metadata.evil.example/latest/meta-data/")
        return real_fetch(requested, **kwargs)

    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers, json={"url": url})
    with patch.object(egress, "fetch", web), patch.object(socket, "getaddrinfo", resolve), \
            patch.object(socket, "create_connection") as connect:
        _run_pending_jobs(app)

    connect.assert_not_called()
    expansion = client.get(f"/iris/results/{analysis_id}/url-expansions", headers=headers).get_json()["expansions"][0]
    assert expansion["hops"][-1]["error"] == "private_address"
    assert expansion["finalUrl"] == url


def test_only_urls_of_the_analysis_can_be_followed(client, app, analyst):
    user, headers = analyst
    analysis_id = _analysis_with_urls(app, user.id, _SHORT)

    response = client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers,
                           json={"url": "http://127.0.0.1:8080/admin"})

    assert response.status_code == 404


def test_a_second_request_reuses_the_expansion(client, app, analyst):
    user, headers = analyst
    analysis_id = _analysis_with_urls(app, user.id, _SHORT)
    client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers, json={"url": _SHORT})
    with patch.object(egress, "fetch", _web):
        _run_pending_jobs(app)

    again = client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers, json={"url": _SHORT})

    assert again.get_json()["status"] == "done"
    with app.app_context():
        assert build_repository(IrisAnalysisRepository)._session.query(IrisUrlExpansion).count() == 1


def test_a_timeout_leaves_a_neutral_result(client, app, analyst):
    user, headers = analyst
    analysis_id = _analysis_with_urls(app, user.id, _SHORT)
    client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers, json={"url": _SHORT})

    def slow(url, **kwargs):
        raise TimeoutError("slow")

    with patch.object(egress, "fetch", slow):
        _run_pending_jobs(app)

    expansion = client.get(f"/iris/results/{analysis_id}/url-expansions", headers=headers).get_json()["expansions"][0]
    assert expansion["status"] == "unavailable" and expansion["hops"][0]["error"] == "timeout"


def test_the_rate_limit_does_not_queue(client, app, analyst, monkeypatch):
    user, headers = analyst
    analysis_id = _analysis_with_urls(app, user.id, _SHORT)
    monkeypatch.setattr(CR, "iris_url_expansion_config", lambda: CR.IrisUrlExpansionConfig(requests_per_minute=0))

    body = client.post(f"/iris/results/{analysis_id}/url-expansions", headers=headers, json={"url": _SHORT}).get_json()

    assert body["status"] == "rate_limited"
    with app.app_context():
        assert build_repository(IrisAnalysisRepository)._session.query(IrisUrlExpansion).count() == 0


def test_expansions_are_private_to_each_user(client, app, analyst, make_user, auth_headers):
    user, headers = analyst
    other = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    mine = _analysis_with_urls(app, user.id, _SHORT)
    theirs = _analysis_with_urls(app, other.id, _SHORT)
    client.post(f"/iris/results/{mine}/url-expansions", headers=headers, json={"url": _SHORT})
    with patch.object(egress, "fetch", _web):
        _run_pending_jobs(app)

    other_headers = auth_headers(other)
    assert client.get(f"/iris/results/{theirs}/url-expansions", headers=other_headers) \
        .get_json()["expansions"][0]["status"] == "not_requested"
    assert client.get(f"/iris/results/{mine}/url-expansions", headers=other_headers).status_code == 404
