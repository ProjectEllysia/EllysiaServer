"""Avisos de correo nuevo: leerlos sin fiarse de ellos, y crear o renovar la suscripción en cada proveedor.

La primera mitad fija la lectura de los avisos (``services/mailbox/events.py``):
un sobre de Pub/Sub mal formado o un lote de Graph raro se ignoran sin error,
los secretos se comparan sin atajos y un ``historyId`` repetido no cuenta como
nuevo. La segunda, con el HTTP simulado, qué pide cada conector: en Gmail un
«watch» sobre el tema de Pub/Sub; en Graph una suscripción con ``clientState``
que, si al renovar ya no existe, se vuelve a crear.
"""

from __future__ import annotations

import base64
import json
from unittest import mock

import pytest

from src.modules.features.iris.services.mailbox.events import (
    hash_client_state,
    is_client_state_valid,
    is_history_newer,
    is_push_token_valid,
    parse_gmail_push,
    parse_graph_notifications,
)
from src.modules.features.iris.services.mailbox.gmail import GmailConnector
from src.modules.features.iris.services.mailbox.microsoft import GraphConnector

pytestmark = pytest.mark.unit

_CALLBACK = "https://app.example.com/iris/mailbox/callback"
_NOTIFY = "https://app.example.com/iris/mailbox/events/microsoft"


@pytest.fixture(autouse=True)
def _oauth_env(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "gmail-client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "gmail-client-secret")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "graph-client-id")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "graph-client-secret")
    monkeypatch.setenv("GRAPH_TENANT_ID", "common")
    monkeypatch.setenv("GMAIL_PUBSUB_TOPIC", "projects/p/topics/iris")


def _response(json_data=None, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.raise_for_status.side_effect = None
    return response


def _envelope(payload, publish_time="2026-09-28T10:00:00.123Z"):
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return {"message": {"data": data, "publishTime": publish_time}, "subscription": "projects/p/subscriptions/s"}


# ------------------------------------------------------------------- lectura de avisos

def test_a_gmail_envelope_gives_the_account_and_history_id():
    push = parse_gmail_push(_envelope({"emailAddress": "Ana@Corp.Example", "historyId": 12345}))
    assert push.email_address == "ana@corp.example"
    assert push.history_id == "12345"
    assert push.published_at.isoformat() == "2026-09-28T10:00:00.123000"


@pytest.mark.parametrize("body", [
    None, [], {}, {"message": "x"}, {"message": {"data": "%%%"}},
    _envelope(["no", "es", "un", "objeto"]),
    _envelope({"emailAddress": "ana@corp.example"}),
    _envelope({"emailAddress": "ana@corp.example", "historyId": "12a"}),
    _envelope({"historyId": "1"}),
])
def test_a_malformed_gmail_envelope_is_ignored(body):
    assert parse_gmail_push(body) is None


def test_a_graph_batch_keeps_only_notifications_with_a_subscription():
    notifications = parse_graph_notifications({"value": [
        {"subscriptionId": "s1", "clientState": "c1"}, {"clientState": "sin-id"}, "no-es-un-objeto",
        {"subscriptionId": "s2"},
    ]})
    assert [(n.subscription_id, n.client_state) for n in notifications] == [("s1", "c1"), ("s2", "")]
    assert parse_graph_notifications({"value": "x"}) == []
    assert parse_graph_notifications(None) == []


def test_secrets_are_only_accepted_when_they_match():
    assert is_push_token_valid("s3cret", "s3cret")
    assert not is_push_token_valid("otro", "s3cret")
    assert not is_push_token_valid(None, "s3cret")
    # Sin secreto configurado no se acepta nada, ni siquiera un token vacío.
    assert not is_push_token_valid("", "")

    stored = hash_client_state("estado")
    assert is_client_state_valid("estado", stored)
    assert not is_client_state_valid("otro", stored)
    assert not is_client_state_valid("", stored)
    assert not is_client_state_valid("estado", None)


def test_only_a_greater_history_id_counts_as_new():
    assert is_history_newer("10", None)
    assert is_history_newer("11", "10")
    assert not is_history_newer("10", "10")
    assert not is_history_newer("9", "10")
    # Se compara como número, no como texto.
    assert is_history_newer("100", "99")


# ------------------------------------------------------------------- Gmail

def test_gmail_watches_the_monitored_label_on_the_pubsub_topic():
    with mock.patch("requests.post", return_value=_response({"historyId": "1", "expiration": "1790000000000"})) as post:
        info = GmailConnector(_CALLBACK, folder="Label_7").subscribe("token", _NOTIFY, "ignorado")
    url, kwargs = post.call_args.args[0], post.call_args.kwargs
    assert url.endswith("/users/me/watch")
    assert kwargs["json"] == {"topicName": "projects/p/topics/iris", "labelIds": ["Label_7"],
                              "labelFilterBehavior": "include"}
    assert info.external_id is None
    assert info.expires_at.year == 2026


def test_gmail_without_a_topic_refuses_to_subscribe(monkeypatch):
    monkeypatch.delenv("GMAIL_PUBSUB_TOPIC")
    with mock.patch("requests.post") as post, pytest.raises(ValueError, match="GMAIL_PUBSUB_TOPIC"):
        GmailConnector(_CALLBACK).subscribe("token", _NOTIFY, "x")
    post.assert_not_called()


def test_gmail_stop_tolerates_a_watch_that_no_longer_exists():
    with mock.patch("requests.post", return_value=_response(status_code=404)) as post:
        GmailConnector(_CALLBACK).unsubscribe("token", None)
    assert post.call_args.args[0].endswith("/users/me/stop")


# ------------------------------------------------------------------- Microsoft Graph

def test_graph_subscribes_to_new_messages_of_the_folder_with_a_client_state():
    with mock.patch("requests.post", return_value=_response({"id": "sub-1"})) as post:
        info = GraphConnector(_CALLBACK, folder="inbox").subscribe("token", _NOTIFY, "estado")
    body = post.call_args.kwargs["json"]
    assert post.call_args.args[0].endswith("/subscriptions")
    assert body["changeType"] == "created"
    assert body["notificationUrl"] == _NOTIFY
    assert body["resource"] == "me/mailFolders('inbox')/messages"
    assert body["clientState"] == "estado"
    assert info.external_id == "sub-1"


def test_graph_renewal_only_extends_the_expiry():
    with mock.patch("requests.patch", return_value=_response({"id": "sub-1"})) as patch:
        info = GraphConnector(_CALLBACK).renew("token", "sub-1", _NOTIFY, "estado")
    assert patch.call_args.args[0].endswith("/subscriptions/sub-1")
    assert list(patch.call_args.kwargs["json"]) == ["expirationDateTime"]
    assert info.external_id == "sub-1"


def test_graph_renewal_recreates_a_subscription_graph_already_deleted():
    with mock.patch("requests.patch", return_value=_response(status_code=404)), \
            mock.patch("requests.post", return_value=_response({"id": "sub-2"})) as post:
        info = GraphConnector(_CALLBACK).renew("token", "sub-1", _NOTIFY, "estado")
    assert post.call_args.kwargs["json"]["clientState"] == "estado"
    assert info.external_id == "sub-2"


def test_graph_unsubscribe_deletes_and_tolerates_a_missing_one():
    with mock.patch("requests.delete", return_value=_response(status_code=404)) as delete:
        GraphConnector(_CALLBACK).unsubscribe("token", "sub-1")
    assert delete.call_args.args[0].endswith("/subscriptions/sub-1")
    with mock.patch("requests.delete") as delete:
        GraphConnector(_CALLBACK).unsubscribe("token", None)
    delete.assert_not_called()
