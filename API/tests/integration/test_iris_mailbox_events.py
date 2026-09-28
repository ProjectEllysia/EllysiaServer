"""Ingesta por eventos: un aviso válido despierta el sync, uno falso o repetido no, y el sondeo sigue.

Los avisos se mandan a los endpoints públicos reales (``/iris/mailbox/events/...``);
el sync que despiertan se sustituye por un registro de llamadas, y el proveedor
(para crear o renovar la suscripción) por un conector falso. Fija el gate de la
fase: sin secreto no se acepta nada, una ráfaga no dispara una tormenta de
syncs, un aviso repetido no hace nada, y si la suscripción falla o caduca el
sondeo vuelve a su ritmo normal.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from unittest import mock

import pytest

import src.modules.system.config_reading as CR
import src.modules.features.iris.managers.mailbox as mailbox_managers_mod
from src.modules.features.iris.managers.mailbox import IrisMailboxManager
from src.modules.features.iris.managers.mailbox_events import IrisMailboxEventManager
from src.modules.features.iris.model import IrisMailboxConnection, IrisMailboxSubscription
from src.modules.features.iris.repositories import (
    IrisMailboxConnectionRepository, IrisMailboxSubscriptionRepository,
)
from src.modules.features.iris.services.mailbox import SubscriptionInfo
from src.modules.features.iris.services.mailbox.events import hash_client_state
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_PUSH_TOKEN = "secreto-de-empuje-de-la-instalacion"
_CLIENT_STATE = "secreto-de-la-suscripcion-de-graph"


@pytest.fixture(autouse=True)
def _events_enabled(monkeypatch):
    """Eventos encendidos, secreto de Gmail configurado y sin agrupación salvo que el test la pida."""
    monkeypatch.setattr(CR, "iris_mailbox_events_config", lambda: CR.IrisMailboxEventsConfig(enabled=True))
    monkeypatch.setenv("IRIS_GMAIL_PUSH_TOKEN", _PUSH_TOKEN)
    monkeypatch.setenv("GMAIL_PUBSUB_TOPIC", "projects/p/topics/iris")


@pytest.fixture
def woken():
    """Sustituye el encolado del sync por una lista de las conexiones despertadas."""
    calls: list[int] = []
    with mock.patch.object(IrisMailboxManager, "submit_sync", lambda self, connection_id: calls.append(connection_id)):
        yield calls


class _FakeQueue:
    """Cola falsa: guarda lo que se encola."""

    def __init__(self):
        self.submitted: list[dict] = []

    def submit(self, **kwargs):
        self.submitted.append(kwargs)


class _SubscribingConnector:
    """Proveedor falso para crear y renovar suscripciones."""

    def __init__(self, fail_with: Exception | None = None, renewed_id: str | None = None):
        self.calls: list[tuple] = []
        self._fail_with = fail_with
        self._renewed_id = renewed_id

    def subscribe(self, access_token, notification_url, client_state):
        if self._fail_with is not None:
            raise self._fail_with
        self.calls.append(("subscribe", notification_url))
        return SubscriptionInfo(expires_at=utcnow_naive() + timedelta(days=3), external_id="sub-nueva")

    def renew(self, access_token, external_id, notification_url, client_state):
        self.calls.append(("renew", external_id))
        return SubscriptionInfo(expires_at=utcnow_naive() + timedelta(days=3),
                                external_id=self._renewed_id or external_id)


def _connection(app, user_id: int, *, provider: str = "gmail", email: str = "ana@corp.example",
                last_sync_minutes_ago: int | None = None) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            connection = IrisMailboxConnectionRepository(uow).save(IrisMailboxConnection(
                user_id=user_id, provider=provider, account_email=email, scopes="openid",
                refresh_token="refresh", access_token="access",
                access_token_expires_at=utcnow_naive() + timedelta(hours=1), status="active",
                last_sync_at=(utcnow_naive() - timedelta(minutes=last_sync_minutes_ago)
                              if last_sync_minutes_ago is not None else None),
            ))
            return connection.id


def _subscription(app, connection_id: int, *, provider: str = "gmail", status: str = "active",
                  expires_in: timedelta = timedelta(days=3), external_id: str | None = None,
                  last_history_id: str | None = None, updated_ago: timedelta = timedelta(0)) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            now = utcnow_naive()
            subscription = IrisMailboxSubscriptionRepository(uow).save(IrisMailboxSubscription(
                connection_id=connection_id, provider=provider, status=status, expires_at=now + expires_in,
                external_id=external_id, last_history_id=last_history_id, events_received=0,
                client_state_sha256=hash_client_state(_CLIENT_STATE) if provider == "microsoft" else None,
                updated_at=now - updated_ago, created_at=now - updated_ago,
            ))
            return subscription.id


def _stored(app, connection_id: int) -> IrisMailboxSubscription:
    with app.app_context():
        return build_repository(IrisMailboxSubscriptionRepository).get_by_connection(connection_id)


def _gmail_push(client, *, history_id: str = "100", email: str = "ana@corp.example", token: str = _PUSH_TOKEN,
                published_at: str | None = None):
    data = base64.b64encode(json.dumps({"emailAddress": email, "historyId": history_id}).encode()).decode()
    message = {"data": data, "messageId": "1"}
    if published_at:
        message["publishTime"] = published_at
    return client.post(f"/iris/mailbox/events/gmail?token={token}",
                       json={"message": message, "subscription": "projects/p/subscriptions/s"})


def _graph_notification(client, subscription_id: str = "sub-1", client_state: str = _CLIENT_STATE):
    return client.post("/iris/mailbox/events/microsoft", json={"value": [{
        "subscriptionId": subscription_id, "clientState": client_state, "changeType": "created",
        "resource": "me/mailFolders('inbox')/messages/AAA",
    }]})


# --------------------------------------------------------------------------- autenticidad

def test_a_gmail_notification_without_the_push_secret_is_rejected(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id)
    assert _gmail_push(client, token="otro").status_code == 401
    assert client.post("/iris/mailbox/events/gmail", json={}).status_code == 401
    assert woken == []


def test_without_a_configured_push_secret_nothing_is_accepted(client, app, regular_user, woken, monkeypatch):
    monkeypatch.delenv("IRIS_GMAIL_PUSH_TOKEN")
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id)
    assert client.post("/iris/mailbox/events/gmail?token=", json={}).status_code == 401
    assert woken == []


def test_a_graph_notification_with_the_wrong_client_state_is_ignored(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id, provider="microsoft")
    _subscription(app, connection_id, provider="microsoft", external_id="sub-1")
    # Graph espera un 202 rápido pase lo que pase; a quien falsifica no se le dan pistas.
    assert _graph_notification(client, client_state="falso").status_code == 202
    assert _graph_notification(client, subscription_id="no-existe").status_code == 202
    assert woken == []


def test_graph_validates_the_endpoint_by_getting_its_token_back(client):
    response = client.post("/iris/mailbox/events/microsoft?validationToken=Validation%3A+abc")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert response.get_data(as_text=True) == "Validation: abc"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_an_oversized_validation_token_is_not_reflected_whole(client):
    response = client.post(f"/iris/mailbox/events/microsoft?validationToken={'a' * 5000}")
    assert len(response.get_data(as_text=True)) == 1024


# --------------------------------------------------------------------------- despertar el sync

def test_a_valid_gmail_notification_wakes_every_connection_of_that_account(client, app, regular_user, admin_user,
                                                                           woken):
    first = _connection(app, regular_user.id)
    second = _connection(app, admin_user.id, email="Ana@Corp.Example")
    other = _connection(app, regular_user.id, email="otra@corp.example")
    for connection_id in (first, second, other):
        _subscription(app, connection_id)

    assert _gmail_push(client).status_code == 204

    assert sorted(woken) == sorted([first, second])
    assert _stored(app, first).last_history_id == "100"
    assert _stored(app, first).events_received == 1


def test_a_valid_graph_notification_wakes_its_connection(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id, provider="microsoft")
    _subscription(app, connection_id, provider="microsoft", external_id="sub-1")
    assert _graph_notification(client).status_code == 202
    assert woken == [connection_id]


def test_a_repeated_or_older_gmail_notification_wakes_nothing(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id, last_history_id="500")
    _gmail_push(client, history_id="500")
    _gmail_push(client, history_id="499")
    assert woken == []


def test_a_notification_published_long_ago_is_ignored(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id)
    stale = (utcnow_naive() - timedelta(hours=3)).isoformat() + "Z"
    assert _gmail_push(client, published_at=stale).status_code == 204
    assert woken == []


def test_a_malformed_gmail_envelope_is_ignored_without_error(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id)
    response = client.post(f"/iris/mailbox/events/gmail?token={_PUSH_TOKEN}",
                           json={"message": {"data": "%%%no-es-base64%%%"}})
    assert response.status_code == 204
    assert woken == []


def test_a_burst_of_notifications_wakes_a_single_sync(client, app, regular_user, woken, monkeypatch):
    monkeypatch.setattr(CR, "iris_mailbox_events_config",
                        lambda: CR.IrisMailboxEventsConfig(enabled=True, debounce_seconds=30))
    connection_id = _connection(app, regular_user.id, provider="microsoft")
    _subscription(app, connection_id, provider="microsoft", external_id="sub-1")
    for _ in range(10):
        _graph_notification(client)
    assert woken == [connection_id]
    # Los avisos de la ráfaga no despiertan nada más, pero se cuentan.
    assert _stored(app, connection_id).events_received == 10


def test_a_notification_for_a_paused_connection_wakes_nothing(client, app, regular_user, woken):
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id)
    with app.app_context():
        with UnitOfWork() as uow:
            IrisMailboxConnectionRepository(uow).get_by_id(connection_id).status = "paused"
    _gmail_push(client)
    assert woken == []


# --------------------------------------------------------------------------- sondeo de respaldo

def test_polling_is_spaced_out_only_while_the_subscription_is_healthy(app, regular_user, admin_user):
    healthy = _connection(app, regular_user.id, last_sync_minutes_ago=10)
    _subscription(app, healthy)
    expired = _connection(app, admin_user.id, email="b@corp.example", last_sync_minutes_ago=10)
    _subscription(app, expired, expires_in=timedelta(minutes=-1))
    failed = _connection(app, admin_user.id, email="c@corp.example", last_sync_minutes_ago=10)
    _subscription(app, failed, status="failed")
    without = _connection(app, admin_user.id, email="d@corp.example", last_sync_minutes_ago=10)

    with app.app_context():
        due = {connection.id for connection in build_repository(
            IrisMailboxConnectionRepository).get_due_for_sync_with_events(5, 30)}
    assert due == {expired, failed, without}

    with app.app_context():
        due = {connection.id for connection in build_repository(
            IrisMailboxConnectionRepository).get_due_for_sync_with_events(5, 8)}
    assert healthy in due


# --------------------------------------------------------------------------- mantener las suscripciones

def _ensure(app, connector, connection_id: int) -> None:
    with app.app_context(), mock.patch.object(mailbox_managers_mod, "get_connector", return_value=connector):
        IrisMailboxEventManager.execute_ensure_subscription(connection_id)


def test_maintenance_asks_for_missing_failed_and_expiring_subscriptions(app, regular_user, admin_user):
    missing = _connection(app, regular_user.id)
    failed_long_ago = _connection(app, admin_user.id, email="b@corp.example")
    _subscription(app, failed_long_ago, status="failed", updated_ago=timedelta(hours=2))
    failed_just_now = _connection(app, admin_user.id, email="c@corp.example")
    _subscription(app, failed_just_now, status="failed")
    expiring = _connection(app, admin_user.id, email="d@corp.example")
    _subscription(app, expiring, expires_in=timedelta(hours=2))
    healthy = _connection(app, admin_user.id, email="e@corp.example")
    _subscription(app, healthy)

    queue = _FakeQueue()
    with app.app_context():
        queued = IrisMailboxEventManager(task_queue=queue).run_maintenance()

    asked = {job["args"][0] for job in queue.submitted}
    assert asked == {missing, failed_long_ago, expiring}
    assert queued == 3
    assert all(job["category"] == "iris.ingest" for job in queue.submitted)
    assert all(job["external_id"].startswith("iris-mailbox-subscription:") for job in queue.submitted)


def test_with_events_disabled_nothing_is_subscribed(app, regular_user, monkeypatch):
    monkeypatch.setattr(CR, "iris_mailbox_events_config", lambda: CR.IrisMailboxEventsConfig(enabled=False))
    _connection(app, regular_user.id)
    queue = _FakeQueue()
    with app.app_context():
        assert IrisMailboxEventManager(task_queue=queue).run_maintenance() == 0
        assert IrisMailboxEventManager(task_queue=queue).request_subscription(1) is False
    assert queue.submitted == []


def test_the_worker_creates_the_subscription_with_a_fresh_client_state(app, regular_user):
    connection_id = _connection(app, regular_user.id, provider="microsoft")
    connector = _SubscribingConnector()
    _ensure(app, connector, connection_id)

    stored = _stored(app, connection_id)
    assert connector.calls == [("subscribe", f"{CR.general_config().public_url}/iris/mailbox/events/microsoft")]
    assert stored.status == "active"
    assert stored.external_id == "sub-nueva"
    assert stored.client_state_sha256 and len(stored.client_state_sha256) == 64
    assert stored.expires_at > utcnow_naive()


def test_renewing_keeps_the_client_state_graph_already_has(app, regular_user):
    connection_id = _connection(app, regular_user.id, provider="microsoft")
    _subscription(app, connection_id, provider="microsoft", external_id="sub-1", expires_in=timedelta(hours=2))
    _ensure(app, _SubscribingConnector(), connection_id)
    stored = _stored(app, connection_id)
    assert stored.external_id == "sub-1"
    assert stored.client_state_sha256 == hash_client_state(_CLIENT_STATE)
    assert stored.expires_at > utcnow_naive() + timedelta(days=2)


def test_a_subscription_recreated_on_renewal_gets_a_new_client_state(app, regular_user):
    connection_id = _connection(app, regular_user.id, provider="microsoft")
    _subscription(app, connection_id, provider="microsoft", external_id="sub-1", expires_in=timedelta(hours=2))
    _ensure(app, _SubscribingConnector(renewed_id="sub-2"), connection_id)
    stored = _stored(app, connection_id)
    assert stored.external_id == "sub-2"
    assert stored.client_state_sha256 != hash_client_state(_CLIENT_STATE)


def test_a_provider_refusal_leaves_the_subscription_failed_and_polling_normal(app, regular_user):
    connection_id = _connection(app, regular_user.id, last_sync_minutes_ago=10)
    _ensure(app, _SubscribingConnector(fail_with=ValueError("Falta GMAIL_PUBSUB_TOPIC")), connection_id)
    stored = _stored(app, connection_id)
    assert stored.status == "failed"
    assert "GMAIL_PUBSUB_TOPIC" in stored.last_error
    with app.app_context():
        due = {connection.id for connection in build_repository(
            IrisMailboxConnectionRepository).get_due_for_sync_with_events(5, 30)}
    assert connection_id in due


def test_the_health_of_a_connection_shows_its_event_subscription(client, app, regular_user, auth_headers):
    connection_id = _connection(app, regular_user.id)
    _subscription(app, connection_id)
    response = client.get(f"/iris/mailbox/connections/{connection_id}/health", headers=auth_headers(regular_user))
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["eventSubscription"]["status"] == "active"
