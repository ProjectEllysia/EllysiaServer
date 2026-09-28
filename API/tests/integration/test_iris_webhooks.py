"""Webhooks de Iris: eventos firmados, reintentos acotados, sin duplicados, y auto-desactivación.

Recorre el camino completo: la emisión desde el sitio real que la provoca (un
análisis que termina con el catálogo real de reglas, un caso que cambia por la
API, una campaña que se abre, un buzón que pierde la autorización), el job de
entrega del worker llamado directamente y la red sustituida en la costura más
baja (``egress.fetch``). Así la firma que se comprueba es la que saldría de
verdad, y se comprueba como lo haría un receptor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text

import src.modules.system.config_reading as CR
from src.modules.features.iris.managers.analysis import _run_analysis
from src.modules.features.iris.managers.mailbox import _mark_reauth_is_required
from src.modules.features.iris.managers.webhooks import IrisWebhookManager
from src.modules.features.iris.model import (
    IrisAnalysis, IrisMailboxConnection, IrisWebhookDelivery, IrisWebhookSubscription,
)
from src.modules.features.iris.repositories import (
    IrisAnalysisRepository, IrisMailboxConnectionRepository, IrisWebhookDeliveryRepository,
)
from src.modules.features.iris.services.enrichment import egress
from src.modules.features.iris.services.enrichment.egress import EgressResponse
from src.modules.features.iris.services.webhook_events import emit_event
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE,
    AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]
_HOOK = "https://siem.example.com/hooks/ellysia"


class _Receiver:
    """Un receptor falso: guarda lo que le llega y responde lo que se le diga."""

    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[dict] = []

    def __call__(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return EgressResponse(url=url, status=self.status, headers={}, body=b"ok", is_truncated=False,
                              peer_address="93.184.216.34")

    def events(self) -> list[dict]:
        return [json.loads(request["body"]) for request in self.requests]


def _verify(secret: str, request: dict) -> bool:
    """Comprueba la firma de una petición recibida como lo haría el receptor."""
    parts = dict(part.split("=", 1) for part in request["extra_headers"]["X-Ellysia-Signature"].split(","))
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + request["body"], hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


def _deliveries(app, subscription_id: int) -> list[IrisWebhookDelivery]:
    with app.app_context():
        return (build_repository(IrisWebhookDeliveryRepository)._session.query(IrisWebhookDelivery)
                .filter(IrisWebhookDelivery.subscription_id == subscription_id)
                .order_by(IrisWebhookDelivery.id).all())


def _subscription(app, subscription_id: int) -> IrisWebhookSubscription:
    with app.app_context():
        return build_repository(IrisWebhookDeliveryRepository)._session.get(IrisWebhookSubscription, subscription_id)


def _deliver_due(app, receiver: _Receiver, *, now_offset: timedelta = timedelta(0)) -> None:
    """Ejecuta el job de cada entrega pendiente cuyo intento ya toca, como el worker."""
    with app.app_context():
        due = build_repository(IrisWebhookDeliveryRepository).get_due_ids(utcnow_naive() + now_offset, 100)
    with patch.object(egress, "fetch", receiver):
        for delivery_id, _ in due:
            if now_offset:
                _make_due_now(app, delivery_id)
            with app.app_context():
                IrisWebhookManager.execute_webhook_delivery(delivery_id)


def _make_due_now(app, delivery_id: int) -> None:
    """Adelanta el siguiente intento de una entrega, para no esperar la espera real."""
    with app.app_context():
        with UnitOfWork() as uow:
            delivery = IrisWebhookDeliveryRepository(uow).get_by_id(delivery_id)
            delivery.next_attempt_at = utcnow_naive() - timedelta(seconds=1)


@pytest.fixture
def analyst(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    return user, auth_headers(user)


def _create_hook(client, headers, events=("analysis.finished", "case.updated", "campaign.detected",
                                          "mailbox.reauth_required"), url=_HOOK) -> dict:
    response = client.post("/iris/webhooks", headers=headers,
                           json={"name": "SIEM", "url": url, "eventTypes": list(events)})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _phishing(invoice: int) -> str:
    return (
        "From: Soporte PayPal <avisos@paypa1-secure.example>\r\n"
        "To: ana@corp.example\r\n"
        f"Subject: Factura {invoice} pendiente de pago\r\n"
        "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
        f"Message-ID: <{invoice}@paypa1-secure.example>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"<p>Estimado cliente, la factura {invoice} vence hoy. Verifique su cuenta.</p>"
        "<a href=\"http://paypa1-secure.example/login\">https://www.paypal.com</a>\r\n"
    )


def _analyze(app, user_id: int, raw: str) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers=raw, user_id=user_id, status="pending", title=f"Correo {len(raw)}")
            IrisAnalysisRepository(uow).save(analysis)
            analysis_id = analysis.id
        _run_analysis(analysis_id, raw)
    return analysis_id


# --------------------------------------------------------------------------- alta y secreto

def test_the_secret_is_shown_once_and_stored_encrypted(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers)

    assert created["secret"].startswith("whsec_")
    listing = client.get("/iris/webhooks", headers=headers).get_json()
    assert "secret" not in listing["subscriptions"][0]
    assert "analysis.finished" in listing["availableEventTypes"] and "ping" not in listing["availableEventTypes"]
    with app.app_context():
        stored = build_repository(IrisWebhookDeliveryRepository)._session.execute(
            text('SELECT secret FROM "IrisWebhookSubscription"')).scalar()
    assert stored != created["secret"] and created["secret"] not in stored


def test_an_insecure_or_internal_url_is_rejected(client, analyst):
    _, headers = analyst
    for url in ("http://siem.example.com/h", "https://192.168.1.10/h", "https://localhost/h"):
        response = client.post("/iris/webhooks", headers=headers,
                               json={"name": "x", "url": url, "eventTypes": ["case.updated"]})
        assert response.status_code == 400, url


def test_ping_is_not_a_subscribable_event(client, analyst):
    _, headers = analyst
    response = client.post("/iris/webhooks", headers=headers,
                           json={"name": "x", "url": _HOOK, "eventTypes": ["ping"]})
    assert response.status_code == 422


def test_the_number_of_webhooks_per_user_is_capped(client, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.setattr(CR, "iris_webhooks_config", lambda: CR.IrisWebhooksConfig(max_subscriptions_per_user=1))
    _create_hook(client, headers)

    response = client.post("/iris/webhooks", headers=headers,
                           json={"name": "otro", "url": _HOOK, "eventTypes": ["case.updated"]})
    assert response.status_code == 409
    assert response.get_json()["messageKey"] == "irisWebhookLimitReached"


def test_the_surface_is_closed_in_preview(client, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.delenv("LAUNCH_MODE", raising=False)
    monkeypatch.setattr(CR, "launch_config", lambda: CR.LaunchConfig(
        configured_mode="preview", surfaces={surface.value: True for surface in CR.LaunchSurface}))

    response = client.post("/iris/webhooks", headers=headers,
                           json={"name": "x", "url": _HOOK, "eventTypes": ["case.updated"]})
    assert response.status_code == 403


def test_a_webhook_of_another_user_does_not_exist_for_you(client, analyst, make_user, auth_headers):
    _, headers = analyst
    created = _create_hook(client, headers)
    intruder = auth_headers(make_user(role="role_user", attributes=_IRIS_ATTRIBUTES))

    hook_id = created["subscriptionId"]
    assert client.get(f"/iris/webhooks/{hook_id}/deliveries", headers=intruder).status_code == 404
    assert client.patch(f"/iris/webhooks/{hook_id}", headers=intruder, json={"isActive": False}).status_code == 404
    assert client.delete(f"/iris/webhooks/{hook_id}", headers=intruder).status_code == 404


# --------------------------------------------------------------------------- eventos

def test_a_case_change_arrives_signed_and_verifiable(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    case = client.post("/iris/cases", headers=headers, json={"title": "Campaña de facturas"}).get_json()
    client.post(f"/iris/cases/{case['caseId']}/status", headers=headers, json={"status": "triage"})

    receiver = _Receiver()
    _deliver_due(app, receiver)

    assert len(receiver.requests) == 2
    assert all(_verify(created["secret"], request) for request in receiver.requests)
    kinds = [event["data"]["change"]["kind"] for event in receiver.events()]
    assert kinds == ["created", "status_changed"]
    last = receiver.events()[-1]
    assert last["type"] == "case.updated" and last["data"]["status"] == "triage"
    assert receiver.requests[-1]["extra_headers"]["X-Ellysia-Event-Id"] == last["id"]
    assert all(delivery.status == "delivered" for delivery in _deliveries(app, created["subscriptionId"]))


def test_a_note_is_announced_without_its_text(client, app, analyst):
    _, headers = analyst
    _create_hook(client, headers, events=("case.updated",))
    case = client.post("/iris/cases", headers=headers, json={"title": "Caso"}).get_json()
    client.post(f"/iris/cases/{case['caseId']}/notes", headers=headers, json={"note": "Contraseña: hunter2"})

    receiver = _Receiver()
    _deliver_due(app, receiver)

    note_event = receiver.events()[-1]
    assert note_event["data"]["change"] == {"kind": "note", "detail": None, "hasNote": True,
                                            "actorId": note_event["data"]["change"]["actorId"]}
    assert b"hunter2" not in receiver.requests[-1]["body"]


def test_only_the_subscribed_events_are_sent(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("analysis.finished",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})

    assert _deliveries(app, created["subscriptionId"]) == []


def test_a_finished_analysis_is_announced_once_with_its_verdict(client, app, analyst):
    user, headers = analyst
    created = _create_hook(client, headers, events=("analysis.finished",))

    analysis_id = _analyze(app, user.id, _phishing(1))
    # El mismo job otra vez (la outbox entrega al menos una vez): el análisis ya
    # está terminado y no vuelve a avisar.
    with app.app_context():
        _run_analysis(analysis_id, _phishing(1))

    receiver = _Receiver()
    _deliver_due(app, receiver)
    events = receiver.events()
    assert len(events) == 1
    data = events[0]["data"]
    assert events[0]["type"] == "analysis.finished"
    assert data["analysisId"] == analysis_id and data["source"] == "manual"
    assert data["verdict"] in ("Suspicious", "Phishing") and data["totalScore"] is not None
    assert b"paypa1-secure" not in receiver.requests[0]["body"], "el contenido del correo no viaja"


def test_a_new_campaign_is_announced_once(client, app, analyst):
    user, headers = analyst
    created = _create_hook(client, headers, events=("campaign.detected",))

    first = _analyze(app, user.id, _phishing(101))
    second = _analyze(app, user.id, _phishing(202))
    third = _analyze(app, user.id, _phishing(303))

    receiver = _Receiver()
    _deliver_due(app, receiver)
    events = receiver.events()
    assert len(events) == 1, "los miembros que se suman después no vuelven a avisar"
    assert sorted(events[0]["data"]["analysisIds"]) == sorted([first, second])
    assert third not in events[0]["data"]["analysisIds"]
    assert _deliveries(app, created["subscriptionId"])[0].status == "delivered"


def test_a_mailbox_that_loses_its_authorization_is_announced(client, app, analyst):
    user, headers = analyst
    _create_hook(client, headers, events=("mailbox.reauth_required",))
    with app.app_context():
        with UnitOfWork() as uow:
            connection = IrisMailboxConnectionRepository(uow).save(IrisMailboxConnection(
                user_id=user.id, provider="gmail", account_email="ana@corp.example", scopes="x",
                refresh_token="r", status="active",
            ))
            connection_id = connection.id
        _mark_reauth_is_required(connection_id, "invalid_grant")
        _mark_reauth_is_required(connection_id, "invalid_grant")

    receiver = _Receiver()
    _deliver_due(app, receiver)
    assert [event["data"] for event in receiver.events()] == [
        {"connectionId": connection_id, "provider": "gmail", "accountEmail": "ana@corp.example"},
    ]


def test_events_of_another_user_never_reach_your_webhook(client, app, analyst, make_user, auth_headers):
    _, headers = analyst
    created = _create_hook(client, headers)
    other_headers = auth_headers(make_user(role="role_user", attributes=_IRIS_ATTRIBUTES))
    client.post("/iris/cases", headers=other_headers, json={"title": "Caso ajeno"})

    assert _deliveries(app, created["subscriptionId"]) == []


def test_emitting_the_same_fact_twice_creates_one_delivery(client, app, analyst):
    user, headers = analyst
    created = _create_hook(client, headers, events=("analysis.finished",))
    with app.app_context():
        for _ in range(2):
            with UnitOfWork() as uow:
                emit_event(uow, user.id, "analysis.finished", "analysis.finished:999", {"analysisId": 999})

    assert len(_deliveries(app, created["subscriptionId"])) == 1


# --------------------------------------------------------------------------- reintentos y desactivación

def test_a_failure_is_retried_later_and_gives_up_after_the_last_attempt(client, app, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.setattr(CR, "iris_webhooks_config", lambda: CR.IrisWebhooksConfig(
        max_attempts=3, retry_base_seconds=30, disable_after_consecutive_failures=100))
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})
    receiver = _Receiver(status=503)

    _deliver_due(app, receiver)
    delivery = _deliveries(app, created["subscriptionId"])[0]
    assert delivery.status == "pending" and delivery.attempts == 1 and delivery.last_error == "http_503"
    wait = (delivery.next_attempt_at - utcnow_naive()).total_seconds()
    assert 20 < wait <= 30, "el primer reintento espera la base"

    _deliver_due(app, receiver)
    assert len(receiver.requests) == 1, "no se reintenta antes de tiempo"

    for _ in range(2):
        _deliver_due(app, receiver, now_offset=timedelta(hours=2))
    delivery = _deliveries(app, created["subscriptionId"])[0]
    assert delivery.status == "failed" and delivery.attempts == 3
    assert [request["extra_headers"]["X-Ellysia-Delivery-Attempt"] for request in receiver.requests] == ["1", "2", "3"]
    assert len({request["extra_headers"]["X-Ellysia-Event-Id"] for request in receiver.requests}) == 1

    _deliver_due(app, receiver, now_offset=timedelta(days=1))
    assert len(receiver.requests) == 3, "una entrega fallida no se reintenta sola"


def test_a_broken_receiver_disables_the_webhook_by_itself(client, app, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.setattr(CR, "iris_webhooks_config", lambda: CR.IrisWebhooksConfig(
        max_attempts=10, disable_after_consecutive_failures=2))
    created = _create_hook(client, headers, events=("case.updated",))
    for title in ("uno", "dos", "tres"):
        client.post("/iris/cases", headers=headers, json={"title": title})

    receiver = _Receiver(status=500)
    _deliver_due(app, receiver)

    subscription = _subscription(app, created["subscriptionId"])
    assert subscription.is_active is False and subscription.disabled_reason == "failures"
    assert len(receiver.requests) == 2
    statuses = sorted(delivery.status for delivery in _deliveries(app, created["subscriptionId"]))
    assert statuses == ["failed", "failed", "failed"]
    listed = client.get("/iris/webhooks", headers=headers).get_json()["subscriptions"][0]
    assert listed["isActive"] is False and listed["disabledReason"] == "failures"


def test_a_receiver_that_answers_gone_disables_the_webhook_at_once(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})

    _deliver_due(app, _Receiver(status=410))

    subscription = _subscription(app, created["subscriptionId"])
    assert subscription.is_active is False and subscription.disabled_reason == "gone"


def test_a_success_resets_the_failure_count(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})
    _deliver_due(app, _Receiver(status=500))
    assert _subscription(app, created["subscriptionId"]).consecutive_failures == 1

    _deliver_due(app, _Receiver(status=200), now_offset=timedelta(hours=1))
    assert _subscription(app, created["subscriptionId"]).consecutive_failures == 0


def test_reactivating_a_disabled_webhook_starts_from_zero(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})
    _deliver_due(app, _Receiver(status=410))

    updated = client.patch(f"/iris/webhooks/{created['subscriptionId']}", headers=headers,
                           json={"isActive": True}).get_json()
    assert updated["isActive"] is True and updated["disabledReason"] is None
    assert updated["consecutiveFailures"] == 0


# --------------------------------------------------------------------------- reenvío, prueba y secreto

def test_a_delivery_can_be_replayed_with_the_same_event_id(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})
    receiver = _Receiver()
    _deliver_due(app, receiver)
    delivery = _deliveries(app, created["subscriptionId"])[0]

    replayed = client.post(f"/iris/webhooks/{created['subscriptionId']}/deliveries/{delivery.id}/replay",
                           headers=headers)
    assert replayed.status_code == 202 and replayed.get_json()["status"] == "pending"
    in_progress = client.post(f"/iris/webhooks/{created['subscriptionId']}/deliveries/{delivery.id}/replay",
                              headers=headers)
    assert in_progress.status_code == 409
    _deliver_due(app, receiver)

    event_ids = [request["extra_headers"]["X-Ellysia-Event-Id"] for request in receiver.requests]
    assert len(event_ids) == 2 and event_ids[0] == event_ids[1]
    history = client.get(f"/iris/webhooks/{created['subscriptionId']}/deliveries", headers=headers).get_json()
    assert history["total"] == 1 and history["deliveries"][0]["status"] == "delivered"


def test_a_test_event_reaches_the_receiver(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers)

    queued = client.post(f"/iris/webhooks/{created['subscriptionId']}/test", headers=headers)
    assert queued.status_code == 202
    receiver = _Receiver()
    _deliver_due(app, receiver)

    assert receiver.events()[0]["type"] == "ping"
    assert _verify(created["secret"], receiver.requests[0])


def test_a_disabled_webhook_cannot_be_tested(client, analyst):
    _, headers = analyst
    created = _create_hook(client, headers)
    client.patch(f"/iris/webhooks/{created['subscriptionId']}", headers=headers, json={"isActive": False})

    response = client.post(f"/iris/webhooks/{created['subscriptionId']}/test", headers=headers)
    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisWebhookInactive"


def test_a_rotated_secret_replaces_the_old_one_immediately(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    rotated = client.post(f"/iris/webhooks/{created['subscriptionId']}/secret", headers=headers).get_json()
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})

    receiver = _Receiver()
    _deliver_due(app, receiver)

    assert rotated["secret"] != created["secret"]
    assert _verify(rotated["secret"], receiver.requests[0])
    assert not _verify(created["secret"], receiver.requests[0])


def test_deleting_a_webhook_stops_its_deliveries(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})

    assert client.delete(f"/iris/webhooks/{created['subscriptionId']}", headers=headers).status_code == 200
    receiver = _Receiver()
    _deliver_due(app, receiver)
    assert receiver.requests == []


# --------------------------------------------------------------------------- barrido del scheduler

class _RecordingQueue:
    def __init__(self):
        self.submitted: list[dict] = []

    def submit(self, **kwargs):
        self.submitted.append(kwargs)


def test_the_sweep_queues_due_deliveries_and_rescues_abandoned_ones(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "uno"})
    client.post("/iris/cases", headers=headers, json={"title": "dos"})
    first, second = _deliveries(app, created["subscriptionId"])
    with app.app_context():
        with UnitOfWork() as uow:
            abandoned = IrisWebhookDeliveryRepository(uow).get_by_id(second.id)
            abandoned.status = "delivering"
            abandoned.claimed_at = utcnow_naive() - timedelta(hours=1)

    queue = _RecordingQueue()
    with app.app_context():
        submitted = IrisWebhookManager(task_queue=queue).submit_due_deliveries()

    assert submitted == 2
    assert {job["args"] for job in queue.submitted} == {(first.id,), (second.id,)}
    assert all(job["category"] == "iris.webhook" for job in queue.submitted)
    assert all(job["external_id"].startswith("iris-webhook-delivery:") for job in queue.submitted)


def test_the_history_is_purged_after_its_retention(client, app, analyst):
    _, headers = analyst
    created = _create_hook(client, headers, events=("case.updated",))
    client.post("/iris/cases", headers=headers, json={"title": "Caso"})
    _deliver_due(app, _Receiver())
    with app.app_context():
        with UnitOfWork() as uow:
            delivery = IrisWebhookDeliveryRepository(uow).get_by_id(_deliveries(app, created["subscriptionId"])[0].id)
            delivery.created_at = utcnow_naive() - timedelta(days=90)
        assert IrisWebhookManager.purge_expired_deliveries() == 1

    assert _deliveries(app, created["subscriptionId"]) == []
