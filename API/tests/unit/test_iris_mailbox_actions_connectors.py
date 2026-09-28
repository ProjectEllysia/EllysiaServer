"""Acciones de los conectores de buzón sobre un mensaje, y su deshacer.

Fija, con el HTTP simulado, qué llamadas hace cada proveedor para cada acción
y que el deshacer revierte exactamente lo que cambió la acción: en Gmail solo
las etiquetas que tocó (si el usuario ha leído el correo después, se respeta);
en Graph devuelve el mensaje a su carpeta con el id nuevo que le dio el
movimiento. Y que ninguna acción es un borrado definitivo.
"""

from __future__ import annotations

from unittest import mock

import pytest

from src.modules.features.iris.services.mailbox.gmail import GmailConnector
from src.modules.features.iris.services.mailbox.microsoft import GraphConnector

pytestmark = pytest.mark.unit

_CALLBACK = "https://app.example.com/iris/mailbox/callback"


@pytest.fixture(autouse=True)
def _oauth_env(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "gmail-client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "gmail-client-secret")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "graph-client-id")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "graph-client-secret")
    monkeypatch.setenv("GRAPH_TENANT_ID", "common")


def _response(json_data=None, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = ""
    response.raise_for_status.side_effect = None
    return response


# ------------------------------------------------------------------- scopes

def test_actions_ask_for_write_permission_only_when_enabled():
    gmail, graph = GmailConnector(_CALLBACK), GraphConnector(_CALLBACK)

    assert "gmail.modify" in gmail.authorize_url("s", full_message_mode=False, remediation_enabled=True)
    assert "gmail.modify" not in gmail.authorize_url("s", full_message_mode=True)
    assert "Mail.ReadWrite" in graph.authorize_url("s", full_message_mode=False, remediation_enabled=True)
    assert "Mail.ReadWrite" not in graph.authorize_url("s", full_message_mode=False)


def test_can_act_depends_on_the_granted_scopes():
    assert GmailConnector.can_act("openid https://www.googleapis.com/auth/gmail.modify")
    assert not GmailConnector.can_act("https://www.googleapis.com/auth/gmail.readonly")
    assert GraphConnector.can_act("openid Mail.ReadWrite offline_access")
    assert GraphConnector.can_act("mail.readwrite")
    assert not GraphConnector.can_act("Mail.Read")
    assert not GraphConnector.can_act("")


# ------------------------------------------------------------------- Gmail

def _gmail_get(labels_of_message, existing_labels=()):
    def get(url, **kwargs):
        if url.endswith("/labels"):
            return _response({"labels": [{"id": label_id, "name": name, "type": "user"}
                                         for label_id, name in existing_labels]})
        return _response({"labelIds": list(labels_of_message)})
    return get


def test_gmail_quarantine_creates_the_label_once_and_leaves_the_inbox():
    connector = GmailConnector(_CALLBACK)
    with mock.patch("requests.get", side_effect=_gmail_get(["INBOX", "UNREAD"])), \
            mock.patch("requests.post", side_effect=[_response({"id": "Label_9"}), _response()]) as post:
        result = connector.quarantine("token", "m1", "Iris Cuarentena")

    create, modify = post.call_args_list
    assert create.args[0].endswith("/labels") and create.kwargs["json"]["name"] == "Iris Cuarentena"
    assert modify.args[0].endswith("/messages/m1/modify")
    assert modify.kwargs["json"] == {"addLabelIds": ["Label_9"], "removeLabelIds": ["INBOX"]}
    assert result.provider_message_id == "m1"
    assert result.previous_state["addedLabelIds"] == ["Label_9"]
    assert result.previous_state["removedLabelIds"] == ["INBOX"]


def test_gmail_reuses_an_existing_label():
    connector = GmailConnector(_CALLBACK)
    with mock.patch("requests.get", side_effect=_gmail_get(["INBOX"], [("Label_3", "Iris: sospechoso")])), \
            mock.patch("requests.post", return_value=_response()) as post:
        connector.label("token", "m1", "Iris: sospechoso")

    assert post.call_count == 1
    assert post.call_args.kwargs["json"] == {"addLabelIds": ["Label_3"], "removeLabelIds": []}


def test_gmail_report_phishing_moves_to_spam():
    connector = GmailConnector(_CALLBACK)
    with mock.patch("requests.get", side_effect=_gmail_get(["INBOX"])), \
            mock.patch("requests.post", return_value=_response()) as post:
        connector.report_phishing("token", "m1")

    assert post.call_args.kwargs["json"] == {"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}


def test_gmail_delete_goes_to_the_trash_and_undo_untrashes():
    connector = GmailConnector(_CALLBACK)
    with mock.patch("requests.post", return_value=_response()) as post:
        result = connector.delete("token", "m1")
        connector.undo("token", "delete", "m1", result.previous_state, "Iris: sospechoso")

    trash, untrash = post.call_args_list
    assert trash.args[0].endswith("/messages/m1/trash")
    assert untrash.args[0].endswith("/messages/m1/untrash")


def test_gmail_undo_reverts_only_what_the_action_changed():
    """El usuario leyó el correo después de la cuarentena: deshacer no lo vuelve a marcar como no leído."""
    connector = GmailConnector(_CALLBACK)
    previous = {"labelIds": ["INBOX", "UNREAD"], "addedLabelIds": ["Label_9"], "removedLabelIds": ["INBOX"]}
    with mock.patch("requests.post", return_value=_response()) as post:
        connector.undo("token", "quarantine", "m1", previous, "Iris: sospechoso")

    assert post.call_args.kwargs["json"] == {"addLabelIds": ["INBOX"], "removeLabelIds": ["Label_9"]}


def test_no_gmail_action_calls_the_permanent_delete_endpoint():
    connector = GmailConnector(_CALLBACK)
    with mock.patch("requests.get", side_effect=_gmail_get(["INBOX"], [("Label_1", "Q")])), \
            mock.patch("requests.post", return_value=_response()) as post, \
            mock.patch("requests.delete") as hard_delete:
        connector.quarantine("token", "m1", "Q")
        connector.report_phishing("token", "m1")
        connector.delete("token", "m1")

    hard_delete.assert_not_called()
    assert all(not call.args[0].rstrip("/").endswith("/messages/m1") for call in post.call_args_list)


# ------------------------------------------------------------------- Graph

def test_graph_quarantine_moves_to_a_created_folder_and_keeps_the_new_id():
    connector = GraphConnector(_CALLBACK)

    def get(url, **kwargs):
        if url.endswith("/me/mailFolders"):
            return _response({"value": []})
        return _response({"parentFolderId": "inbox-id"})

    with mock.patch("requests.get", side_effect=get), \
            mock.patch("requests.post", side_effect=[_response({"id": "folder-q"}), _response({"id": "m1-moved"})]) as post:
        result = connector.quarantine("token", "m1", "Iris Cuarentena")

    create, move = post.call_args_list
    assert create.kwargs["json"] == {"displayName": "Iris Cuarentena"}
    assert move.args[0].endswith("/me/messages/m1/move") and move.kwargs["json"] == {"destinationId": "folder-q"}
    assert result.provider_message_id == "m1-moved"
    assert result.previous_state == {"parentFolderId": "inbox-id"}


def test_graph_delete_moves_to_deleted_items_instead_of_deleting():
    connector = GraphConnector(_CALLBACK)
    with mock.patch("requests.get", return_value=_response({"parentFolderId": "inbox-id"})), \
            mock.patch("requests.post", return_value=_response({"id": "m1-deleted"})) as post, \
            mock.patch("requests.delete") as hard_delete:
        result = connector.delete("token", "m1")

    hard_delete.assert_not_called()
    assert post.call_args.kwargs["json"] == {"destinationId": "deleteditems"}
    assert result.provider_message_id == "m1-deleted"


def test_graph_report_phishing_moves_to_junk_and_undo_moves_it_back():
    connector = GraphConnector(_CALLBACK)
    with mock.patch("requests.get", return_value=_response({"parentFolderId": "inbox-id"})), \
            mock.patch("requests.post", side_effect=[_response({"id": "m1-junk"}), _response({"id": "m1-back"})]) as post:
        result = connector.report_phishing("token", "m1")
        restored_id = connector.undo("token", "report_phishing", result.provider_message_id,
                                     result.previous_state, "Iris: sospechoso")

    to_junk, back = post.call_args_list
    assert to_junk.kwargs["json"] == {"destinationId": "junkemail"}
    assert back.args[0].endswith("/me/messages/m1-junk/move") and back.kwargs["json"] == {"destinationId": "inbox-id"}
    assert restored_id == "m1-back"


def test_graph_label_adds_a_category_and_undo_removes_only_it():
    connector = GraphConnector(_CALLBACK)
    with mock.patch("requests.get", return_value=_response({"categories": ["Cliente"]})), \
            mock.patch("requests.patch", return_value=_response()) as patch:
        result = connector.label("token", "m1", "Iris: sospechoso")
    with mock.patch("requests.get", return_value=_response({"categories": ["Cliente", "Iris: sospechoso", "Urgente"]})), \
            mock.patch("requests.patch", return_value=_response()) as undo_patch:
        connector.undo("token", "label", "m1", result.previous_state, "Iris: sospechoso")

    assert patch.call_args.kwargs["json"] == {"categories": ["Cliente", "Iris: sospechoso"]}
    assert undo_patch.call_args.kwargs["json"] == {"categories": ["Cliente", "Urgente"]}
