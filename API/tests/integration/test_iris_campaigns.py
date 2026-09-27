"""Campañas: investigar una campaña una vez en lugar de mensaje a mensaje.

Ejecuta el catálogo real sobre varios correos como lo haría el worker y
comprueba que los de la misma campaña quedan juntos, que la ventana de tiempo
y el veredicto legítimo los separan, y que nunca se agrupa con análisis de
otro usuario.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.modules.features.iris.managers.analysis import _run_analysis
from src.modules.features.iris.model import IrisAnalysis, IrisCampaignMember
from src.modules.features.iris.repositories import IrisAnalysisRepository
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE,
    AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]


def _phishing(invoice: int, recipient: str = "ana@corp.example") -> str:
    """Un correo de la campaña: cambian la factura y el destinatario, no el enlace."""
    return (
        "From: Soporte PayPal <avisos@paypa1-secure.example>\r\n"
        f"To: {recipient}\r\n"
        f"Subject: Factura {invoice} pendiente de pago\r\n"
        "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
        f"Message-ID: <{invoice}@paypa1-secure.example>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"<p>Estimado cliente, la factura {invoice} vence hoy. Verifique su cuenta.</p>"
        "<a href=\"http://paypa1-secure.example/login\">https://www.paypal.com</a>\r\n"
    )


_LEGITIMATE = (
    "From: Boletin <news@example.org>\r\n"
    "To: ana@corp.example\r\n"
    "Subject: Novedades de septiembre\r\n"
    "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
    "Message-ID: <n1@example.org>\r\n\r\n"
    "Hola, estas son las novedades.\r\n"
)


def _analyze(app, user_id: int, raw: str, days_ago: int = 0) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            received_at = utcnow_naive() - timedelta(days=days_ago)
            analysis = IrisAnalysis(raw_headers=raw, user_id=user_id, status="pending",
                                    created_at=received_at, started_at=received_at)
            IrisAnalysisRepository(uow).save(analysis)
            analysis_id = analysis.id
        _run_analysis(analysis_id, raw)
    return analysis_id


def _campaign_of(app, analysis_id: int):
    with app.app_context():
        member = build_repository(IrisAnalysisRepository).get_by_id(analysis_id).campaign_link
        return member.campaign_id if member else None


@pytest.fixture
def analyst(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    return user, auth_headers(user)


def test_messages_of_the_same_campaign_end_up_together(client, app, analyst):
    user, headers = analyst
    ids = [_analyze(app, user.id, _phishing(invoice, f"u{invoice}@corp.example")) for invoice in (101, 202, 303)]

    campaign_ids = {_campaign_of(app, analysis_id) for analysis_id in ids}

    assert len(campaign_ids) == 1 and None not in campaign_ids
    listing = client.get("/iris/campaigns", headers=headers).get_json()
    assert listing["total"] == 1
    summary = listing["campaigns"][0]
    assert summary["analysisCount"] == 3 and summary["messageCount"] == 3
    # La abre el segundo mensaje, el primero que se parece a otro.
    assert summary["label"] == "Factura 202 pendiente de pago"


def test_the_campaign_detail_lists_its_messages_and_what_they_share(client, app, analyst):
    user, headers = analyst
    first = _analyze(app, user.id, _phishing(1))
    second = _analyze(app, user.id, _phishing(2))
    campaign_id = _campaign_of(app, first)

    detail = client.get(f"/iris/campaigns/{campaign_id}", headers=headers).get_json()

    assert {analysis["analysisId"] for analysis in detail["analyses"]} == {first, second}
    assert "url" in detail["analyses"][0]["matchedSignals"]
    shared = {(indicator["kind"], indicator["value"]) for indicator in detail["sharedIndicators"]}
    assert ("url", "http://paypa1-secure.example/login") in shared
    assert all(indicator["analysisCount"] == 2 for indicator in detail["sharedIndicators"])


def test_the_report_says_how_many_other_messages_share_the_campaign(client, app, analyst):
    user, headers = analyst
    first = _analyze(app, user.id, _phishing(1))
    second = _analyze(app, user.id, _phishing(2))
    lonely = _analyze(app, user.id, _LEGITIMATE)

    report = client.get(f"/iris/results/{second}", headers=headers).get_json()

    assert report["campaign"]["campaignId"] == _campaign_of(app, first)
    assert report["campaign"]["relatedCount"] == 1
    assert client.get(f"/iris/results/{lonely}", headers=headers).get_json()["campaign"] is None


def test_a_message_outside_the_window_opens_no_campaign(app, analyst):
    user, _ = analyst
    old = _analyze(app, user.id, _phishing(1), days_ago=30)
    recent = _analyze(app, user.id, _phishing(2))

    assert _campaign_of(app, old) is None
    assert _campaign_of(app, recent) is None


def test_legitimate_messages_are_not_grouped(app, analyst):
    user, _ = analyst
    first = _analyze(app, user.id, _LEGITIMATE)
    second = _analyze(app, user.id, _LEGITIMATE)

    assert _campaign_of(app, first) is None and _campaign_of(app, second) is None


def test_campaigns_never_mix_users(client, app, analyst, make_user, auth_headers):
    user, headers = analyst
    other = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    other_headers = auth_headers(other)
    mine = [_analyze(app, user.id, _phishing(invoice)) for invoice in (1, 2)]
    theirs = _analyze(app, other.id, _phishing(3))

    assert _campaign_of(app, theirs) is None
    campaign_id = _campaign_of(app, mine[0])
    assert client.get("/iris/campaigns", headers=other_headers).get_json()["total"] == 0
    assert client.get(f"/iris/campaigns/{campaign_id}", headers=other_headers).status_code == 404


def test_deleting_messages_until_one_is_left_hides_the_campaign(client, app, analyst):
    user, headers = analyst
    first = _analyze(app, user.id, _phishing(1))
    second = _analyze(app, user.id, _phishing(2))
    campaign_id = _campaign_of(app, first)

    assert client.delete(f"/iris/results/{second}", headers=headers).status_code == 200

    assert client.get("/iris/campaigns", headers=headers).get_json()["total"] == 0
    assert client.get(f"/iris/campaigns/{campaign_id}", headers=headers).status_code == 404
    with app.app_context():
        assert build_repository(IrisAnalysisRepository).get_by_id(first) is not None
        remaining = build_repository(IrisAnalysisRepository).get_by_id(first).campaign_link
        assert isinstance(remaining, IrisCampaignMember)
