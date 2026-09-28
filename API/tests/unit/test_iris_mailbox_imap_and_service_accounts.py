"""Conectores sin OAuth: IMAP de solo lectura, cuentas de servicio y varias carpetas por conexión.

Sin red: el servidor IMAP es un cliente falso que responde como uno de verdad,
y los proveedores se sustituyen en ``requests``. Fija que IMAP solo acepta TLS
contra servidores de internet, que nunca marca nada como leído, que el cursor
no hace backfill y se reinicia si cambia el ``UIDVALIDITY``; que las cuentas de
servicio piden solo lectura y, en Graph, leen el buzón indicado y no el propio;
y que el cursor compuesto de varias carpetas es compatible con el de una sola.
"""

from __future__ import annotations

import imaplib
import json
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.modules.features.iris.services.mailbox import (
    ImapCredentials, MailboxAuthenticationError, MessageRef,
)
from src.modules.features.iris.services.mailbox import imap as imap_module
from src.modules.features.iris.services.mailbox.folders import (
    build_watched_folders, join_cursor, list_new_in_folders, split_cursor,
)
from src.modules.features.iris.services.mailbox.gmail import GmailConnector
from src.modules.features.iris.services.mailbox.imap import (
    ImapConnector, build_message_id, open_session, parse_folder_list, parse_message_id,
)
from src.modules.features.iris.services.mailbox.microsoft import GraphConnector

pytestmark = pytest.mark.unit

_CREDENTIALS = ImapCredentials(host="imap.example.com", port=993, username="ana@example.com", password="app-pass")


class _FakeImap:
    """Servidor IMAP falso: una carpeta con UIDs y mensajes, y registro de lo que se pide."""

    def __init__(self, uids=(), uid_validity=b"7", messages=None):
        self.uids = list(uids)
        self.uid_validity = uid_validity
        self.messages = messages or {}
        self.commands: list[tuple] = []
        self.closed = False

    def select(self, mailbox, readonly=False):
        self.commands.append(("select", mailbox, readonly))
        self._last = {"UIDVALIDITY": [self.uid_validity], "UIDNEXT": [str((max(self.uids) if self.uids else 0) + 1).encode()]}
        return "OK", [b"1"]

    def response(self, code):
        return code, self._last.get(code, [None])

    def uid(self, command, *args):
        self.commands.append(("uid", command, *args))
        if command == "SEARCH":
            start = int(args[1].split()[1].split(":")[0])
            # Como un servidor real, «n:*» incluye el último aunque sea menor que n.
            found = [uid for uid in self.uids if uid >= start] or self.uids[-1:]
            return "OK", [" ".join(str(uid) for uid in found).encode()]
        if command == "FETCH":
            uid = int(args[0])
            return "OK", [(f"{uid} (UID {uid})".encode(), self.messages[uid]), b")"]
        raise AssertionError(command)

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "Enviados"',
                      b'(\\Noselect \\HasChildren) "/" "Archivo"', b'(\\HasNoChildren) "/" "Clientes/Proveedores"']

    def shutdown(self):
        self.closed = True


def _connector(fake, folder=None):
    patcher = mock.patch.object(imap_module, "open_session", return_value=fake)
    patcher.start()
    return ImapConnector("", folder=folder, credentials=_CREDENTIALS), patcher


# ------------------------------------------------------------------- IMAP: conexión segura

def test_imap_only_accepts_the_allowed_tls_ports():
    with pytest.raises(ValueError, match="Puerto IMAP no permitido"):
        open_session(ImapCredentials(host="imap.example.com", port=143, username="a", password="b"))


def test_imap_never_connects_to_the_internal_network():
    with mock.patch.object(imap_module, "PinnedImapClient") as client:
        with pytest.raises(ValueError, match="no es alcanzable desde internet"):
            open_session(ImapCredentials(host="10.0.0.5", port=993, username="a", password="b"))
        with pytest.raises(ValueError, match="no es alcanzable desde internet"):
            open_session(ImapCredentials(host="127.0.0.1", port=993, username="a", password="b"))
    client.assert_not_called()


def test_imap_connects_to_the_checked_address_and_reports_a_rejected_password():
    fake_client = mock.Mock()
    fake_client.login.side_effect = imaplib.IMAP4.error("AUTHENTICATIONFAILED")
    with mock.patch.object(imap_module.egress, "resolve_public_address", return_value="93.184.216.34"), \
            mock.patch.object(imap_module, "PinnedImapClient", return_value=fake_client) as client_class:
        with pytest.raises(MailboxAuthenticationError):
            open_session(_CREDENTIALS)
    assert client_class.call_args.args[:3] == ("imap.example.com", 993, "93.184.216.34")
    fake_client.shutdown.assert_called_once()


# ------------------------------------------------------------------- IMAP: lectura

def test_the_first_imap_sync_does_not_backfill():
    fake = _FakeImap(uids=[3, 4, 5])
    connector, patcher = _connector(fake)
    try:
        refs, cursor = connector.list_new("", None)
    finally:
        patcher.stop()
    assert refs == []
    assert cursor == "7:5"
    # EXAMINE: la carpeta se abre en solo lectura.
    assert fake.commands[0] == ("select", '"INBOX"', True)
    assert fake.closed


def test_imap_returns_only_messages_after_the_cursor():
    fake = _FakeImap(uids=[3, 4, 5, 6])
    connector, patcher = _connector(fake)
    try:
        refs, cursor = connector.list_new("", "7:4")
        again, same_cursor = connector.list_new("", "7:6")
    finally:
        patcher.stop()
    assert [ref.provider_message_id for ref in refs] == ["7:5:INBOX", "7:6:INBOX"]
    assert cursor == "7:6"
    # Sin nada nuevo, «7:*» devuelve el 6 y se descarta.
    assert again == [] and same_cursor == "7:6"


def test_a_uidvalidity_change_restarts_without_backfill():
    fake = _FakeImap(uids=[1, 2], uid_validity=b"99")
    connector, patcher = _connector(fake)
    try:
        refs, cursor = connector.list_new("", "7:500")
    finally:
        patcher.stop()
    assert refs == [] and cursor == "99:2"


def test_imap_caps_the_messages_per_sync(monkeypatch):
    import src.modules.system.config_reading as CR
    monkeypatch.setattr(CR, "iris_imap_config", lambda: CR.IrisImapConfig(max_messages_per_sync=2))
    fake = _FakeImap(uids=[1, 2, 3, 4, 5])
    connector, patcher = _connector(fake)
    try:
        refs, cursor = connector.list_new("", "7:0")
    finally:
        patcher.stop()
    assert len(refs) == 2 and cursor == "7:2"


def test_imap_reads_without_marking_messages_as_seen():
    raw = b"From: a@evil.example\r\nSubject: hola\r\n\r\ncuerpo"
    fake = _FakeImap(uids=[5], messages={5: raw})
    connector, patcher = _connector(fake, folder="Clientes/Proveedores")
    try:
        headers = connector.fetch_headers("", MessageRef(provider_message_id="7:5:Clientes/Proveedores"))
        full = connector.fetch_raw("", MessageRef(provider_message_id="7:5:Clientes/Proveedores"))
    finally:
        patcher.stop()
    fetches = [command for command in fake.commands if command[:2] == ("uid", "FETCH")]
    assert [command[3] for command in fetches] == ["(BODY.PEEK[HEADER])", "(BODY.PEEK[])"]
    assert ("select", '"Clientes/Proveedores"', True) in fake.commands
    assert "Subject: hola" in headers
    assert full.endswith("cuerpo")


def test_imap_folders_skip_the_non_selectable_ones():
    folders = parse_folder_list(_FakeImap().list()[1])
    assert [(folder.provider_id, folder.folder_type) for folder in folders] == [
        ("INBOX", "system"), ("Enviados", "system"), ("Clientes/Proveedores", "user"),
    ]


def test_imap_message_ids_keep_the_folder_even_with_colons():
    message_id = build_message_id("7", 12, "Trabajo:Clientes")
    assert parse_message_id(message_id) == ("7", 12, "Trabajo:Clientes")


def test_imap_is_read_only_and_has_no_oauth_or_events():
    connector = ImapConnector("", credentials=_CREDENTIALS)
    assert ImapConnector.can_act("anything") is False
    assert not ImapConnector.supports_oauth and not ImapConnector.supports_events
    for call in (lambda: connector.quarantine("", "m", "f"), lambda: connector.delete("", "m"),
                 lambda: connector.authorize_url("s", False), lambda: connector.subscribe("", "u", "c")):
        with pytest.raises(NotImplementedError):
            call()


# ------------------------------------------------------------------- cuentas de servicio

def _response(json_data=None, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.raise_for_status.side_effect = None
    return response


def test_gmail_service_account_signs_a_read_only_delegation_for_the_mailbox(tmp_path, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
    key_file = tmp_path / "sa.json"
    key_file.write_text(json.dumps({"client_email": "iris@proyecto.iam.gserviceaccount.com", "private_key": pem,
                                    "token_uri": "https://oauth2.googleapis.com/token"}))
    monkeypatch.setenv("GMAIL_SERVICE_ACCOUNT_FILE", str(key_file))
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)

    with mock.patch("requests.post", return_value=_response({"access_token": "tok", "expires_in": 3600})) as post:
        token = GmailConnector("", mailbox_address="soporte@empresa.com").acquire_service_token("soporte@empresa.com")

    assertion = post.call_args.kwargs["data"]["assertion"]
    claims = jwt.decode(assertion, private_key.public_key(), algorithms=["RS256"],
                        audience="https://oauth2.googleapis.com/token")
    assert claims["sub"] == "soporte@empresa.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert token.access_token == "tok"
    assert not GmailConnector.can_act(token.scopes)


def test_gmail_service_account_without_a_key_file_is_refused(monkeypatch):
    monkeypatch.delenv("GMAIL_SERVICE_ACCOUNT_FILE", raising=False)
    with mock.patch("requests.post") as post, pytest.raises(ValueError, match="GMAIL_SERVICE_ACCOUNT_FILE"):
        GmailConnector("", mailbox_address="soporte@empresa.com").acquire_service_token("soporte@empresa.com")
    post.assert_not_called()


def test_graph_service_account_uses_client_credentials_and_reads_the_named_mailbox(monkeypatch):
    monkeypatch.setenv("GRAPH_SERVICE_TENANT_ID", "tenant-1")
    monkeypatch.setenv("GRAPH_SERVICE_CLIENT_ID", "app-1")
    monkeypatch.setenv("GRAPH_SERVICE_CLIENT_SECRET", "secreto")
    monkeypatch.delenv("GRAPH_CLIENT_ID", raising=False)
    connector = GraphConnector("", mailbox_address="soporte@empresa.com")

    with mock.patch("requests.post", return_value=_response({"access_token": "tok", "expires_in": 3599})) as post:
        token = connector.acquire_service_token("soporte@empresa.com")
    assert post.call_args.args[0] == "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token"
    assert post.call_args.kwargs["data"]["grant_type"] == "client_credentials"
    assert not GraphConnector.can_act(token.scopes)

    with mock.patch("requests.get", return_value=_response({"value": [], "@odata.deltaLink": "d"})) as get:
        connector.list_new("tok", None)
        connector.list_folders("tok")
    urls = [call.args[0] for call in get.call_args_list]
    assert all("/users/soporte@empresa.com/" in url and "/me/" not in url for url in urls)


def test_graph_service_account_without_configuration_is_refused(monkeypatch):
    for name in ("GRAPH_SERVICE_TENANT_ID", "GRAPH_SERVICE_CLIENT_ID", "GRAPH_SERVICE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="GRAPH_SERVICE_CLIENT_SECRET"):
        GraphConnector("", mailbox_address="x@empresa.com").acquire_service_token("x@empresa.com")


# ------------------------------------------------------------------- varias carpetas

def test_a_single_folder_keeps_the_plain_cursor():
    assert split_cursor("history-123", [None]) == {"": "history-123"}
    assert join_cursor({"": "history-124"}) == "history-124"


def test_adding_a_folder_keeps_the_old_cursor_on_the_primary_one():
    folders = build_watched_folders("INBOX", [{"id": "Label_1"}, {"id": "INBOX"}, {"id": "Label_2"}])
    assert folders == ["INBOX", "Label_1", "Label_2"]
    assert split_cursor("7:10", folders) == {"INBOX": "7:10", "Label_1": None, "Label_2": None}


def test_each_folder_advances_its_own_cursor_and_duplicates_are_dropped():
    class _PerFolder:
        def __init__(self, folder):
            self.folder = folder

        def list_new(self, access_token, cursor):
            if self.folder is None:
                return [MessageRef("m1"), MessageRef("m2")], "c-inbox-2"
            if cursor is None:
                return [], "c-label-1"
            return [MessageRef("m2"), MessageRef("m3")], "c-label-2"

    folders = [None, "Label_1"]
    refs, cursor = list_new_in_folders(_PerFolder, folders, "tok", "c-inbox-1")
    assert [ref.provider_message_id for ref in refs] == ["m1", "m2"]
    assert json.loads(cursor) == {"folders": {"": "c-inbox-2", "Label_1": "c-label-1"}}

    refs, cursor = list_new_in_folders(_PerFolder, folders, "tok", cursor)
    assert [ref.provider_message_id for ref in refs] == ["m1", "m2", "m3"]
    assert json.loads(cursor)["folders"]["Label_1"] == "c-label-2"
