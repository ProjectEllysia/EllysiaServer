"""Buzones compartidos, IMAP y varias carpetas: quién los conecta, quién ve qué y cómo se recuperan.

Monta dos organizaciones y recorre la API real con el proveedor sustituido en
la costura del conector. Fija el criterio de cierre de la iniciativa: un buzón
compartido se conecta con un modelo de propiedad explícito (lo conecta el
dueño de la organización y queda a su cargo) y **ningún usuario ve mensajes
fuera de su alcance**: sin acceso explícito, desde otra organización o tras
salir de la suya, el buzón y sus análisis no existen para él.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

import src.modules.features.iris.managers.analysis as analysis_managers_mod
import src.modules.features.iris.managers.mailbox as mailbox_managers_mod
import src.modules.features.iris.managers.mailbox_accounts as mailbox_accounts_mod
import src.modules.system.config_reading as CR
from src.modules.accounts.model import Organization, OrganizationMember
from src.modules.features.iris.managers.mailbox import IrisMailboxManager
from src.modules.features.iris.managers.mailbox_events import IrisMailboxEventManager
from src.modules.features.iris.model import IrisAnalysis, IrisMailboxConnection
from src.modules.features.iris.repositories import IrisAnalysisRepository, IrisMailboxConnectionRepository
from src.modules.features.iris.services.mailbox import (
    MailboxAuthenticationError, MailboxFolder, MessageRef, ServiceToken,
)
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_BASE_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE, AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]
_OWNER_ATTRIBUTES = [*_BASE_ATTRIBUTES, AttributeType.IRIS_SHARED_MAILBOX.db_name]
_SHARED = "soporte@acme.example"


class _Provider:
    """Proveedor falso: cuenta de servicio, carpetas y un correo nuevo tras el primer sync."""

    def __init__(self, folders=("INBOX", "Label_Facturas"), rejects_service_account=False,
                 rejects_password=False):
        self.folders = [MailboxFolder(provider_id=folder, display_name=folder, folder_type="user")
                        for folder in folders]
        self.rejects_service_account = rejects_service_account
        self.rejects_password = rejects_password
        self.listed: list = []

    def acquire_service_token(self, mailbox_address):
        if self.rejects_service_account:
            raise ValueError("Falta GRAPH_SERVICE_CLIENT_SECRET")
        return ServiceToken(access_token="service-token", expires_at=utcnow_naive() + timedelta(hours=1),
                            scopes="Mail.Read (application)")

    def list_folders(self, access_token):
        if self.rejects_password:
            raise MailboxAuthenticationError("AUTHENTICATIONFAILED")
        return self.folders

    def list_new(self, access_token, cursor):
        if self.rejects_password:
            raise MailboxAuthenticationError("AUTHENTICATIONFAILED")
        self.listed.append(cursor)
        if cursor is None:
            return [], "cursor-1"
        return [MessageRef(provider_message_id="msg-1")], "cursor-2"

    def fetch_headers(self, access_token, message_ref):
        return "From: ceo@acme-nominas.example\r\nSubject: Nomina de Ana\r\n"

    def fetch_raw(self, access_token, message_ref):
        return self.fetch_headers(access_token, message_ref) + "\r\ncuerpo"


class _NoLock:
    """Sustituye el lock de Redis del sync: la suite no tiene Redis."""

    def __init__(self, *args, **kwargs):
        pass

    def acquire(self):
        return True

    def release(self):
        return None

    def renew(self):
        return True


class _FakeQueue:
    def __init__(self):
        self.submitted = []

    def submit(self, **kwargs):
        self.submitted.append(kwargs)


def _organization(app, make_user, slug: str, size: int, owner_attributes=None):
    """Una organización con su dueño (con permiso de buzones compartidos) y ``size - 1`` miembros."""
    users = [make_user(role="role_user", attributes=(owner_attributes or _OWNER_ATTRIBUTES) if position == 0
                       else _BASE_ATTRIBUTES) for position in range(size)]
    with app.app_context():
        with UnitOfWork() as uow:
            organization = Organization(name=slug.title(), slug=slug, owner_user_id=users[0].id)
            uow.session.add(organization)
            uow.session.flush()
            for position, user in enumerate(users):
                uow.session.add(OrganizationMember(organization_id=organization.id, user_id=user.id,
                                                   member_role="owner" if position == 0 else "member"))
    return users


def _leave_organization(app, user_id: int) -> None:
    with app.app_context():
        with UnitOfWork() as uow:
            uow.session.query(OrganizationMember).filter(OrganizationMember.user_id == user_id).delete()


def _create_shared(client, headers, fake=None, **body):
    payload = {"provider": "microsoft", "address": _SHARED, **body}
    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=fake or _Provider()):
        return client.post("/iris/mailbox/shared", headers=headers, json=payload)


def _sync(app, connection_id: int, provider) -> None:
    with app.app_context(), \
            mock.patch.object(mailbox_managers_mod, "get_connector", return_value=provider), \
            mock.patch.object(mailbox_managers_mod, "MailboxSyncLock", _NoLock), \
            mock.patch.object(analysis_managers_mod.TaskQueue, "get_instance", return_value=_FakeQueue()):
        IrisMailboxManager.execute_sync_connection(connection_id)


def _connection(app, connection_id: int) -> IrisMailboxConnection:
    with app.app_context():
        return build_repository(IrisMailboxConnectionRepository).get_by_id(connection_id)


def _shared_with_mail(client, app, owner, owner_headers) -> tuple[int, int]:
    """Un buzón compartido con un correo ya analizado; devuelve ``(buzón, análisis)``."""
    connection_id = _create_shared(client, owner_headers).get_json()["id"]
    provider = _Provider()
    _sync(app, connection_id, provider)
    _sync(app, connection_id, provider)
    with app.app_context():
        with UnitOfWork() as uow:
            analyses = IrisAnalysisRepository(uow).get_by_connection_paginated(connection_id, 1, 10)[0]
            assert len(analyses) == 1
            # El job de análisis no corre en la suite: se deja como terminado.
            analyses[0].status, analyses[0].verdict, analyses[0].total_score = "finished", "Phishing", 12.0
            analyses[0].finished_at = utcnow_naive()
            return connection_id, analyses[0].id


# --------------------------------------------------------------------------- quién lo conecta

def test_the_organization_owner_connects_a_shared_mailbox_with_the_service_account(client, app, make_user,
                                                                                   auth_headers):
    owner, _ = _organization(app, make_user, "acme", 2)
    response = _create_shared(client, auth_headers(owner), folder="Label_Facturas")

    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["accountEmail"] == _SHARED and body["authMode"] == "service_account"
    assert body["myAccess"] == "manager" and body["folder"] == "Label_Facturas"
    connection = _connection(app, body["id"])
    assert connection.kind == "shared" and connection.user_id == owner.id
    assert connection.refresh_token is None
    # Un buzón compartido no aparece entre los personales de nadie.
    listed = client.get("/iris/mailbox/connections", headers=auth_headers(owner)).get_json()
    assert listed["connections"] == []


def test_a_member_who_is_not_the_owner_cannot_connect_one(client, app, make_user, auth_headers):
    _, member = _organization(app, make_user, "acme", 2)
    with app.app_context():
        with UnitOfWork() as uow:
            from src.modules.users.model import UserAttribute
            uow.session.add(UserAttribute(user_id=member.id, attribute_name=AttributeType.IRIS_SHARED_MAILBOX.db_name))
    assert _create_shared(client, auth_headers(member)).status_code == 403


def test_without_the_shared_mailbox_permission_the_owner_cannot_either(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1, owner_attributes=_BASE_ATTRIBUTES)
    assert _create_shared(client, auth_headers(owner)).status_code == 403


def test_someone_outside_any_organization_cannot_connect_one(client, make_user, auth_headers):
    loner = make_user(role="role_user", attributes=_OWNER_ATTRIBUTES)
    assert _create_shared(client, auth_headers(loner)).status_code == 403


def test_access_is_verified_before_anything_is_saved(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    response = _create_shared(client, auth_headers(owner), fake=_Provider(rejects_service_account=True))
    assert response.status_code == 422
    assert response.get_json()["messageKey"] == "irisMailboxServiceAccountRejected"
    bad_folder = _create_shared(client, auth_headers(owner), folder="No_Existe")
    assert bad_folder.status_code == 400
    assert client.get("/iris/mailbox/shared", headers=auth_headers(owner)).get_json()["mailboxes"] == []


def test_the_same_mailbox_cannot_be_connected_twice_and_there_is_a_limit(client, app, make_user, auth_headers,
                                                                         monkeypatch):
    owner, = _organization(app, make_user, "acme", 1)
    assert _create_shared(client, auth_headers(owner)).status_code == 201
    again = _create_shared(client, auth_headers(owner), address="SOPORTE@acme.example")
    assert again.status_code == 409
    assert again.get_json()["messageKey"] == "irisSharedMailboxAlreadyConnected"
    monkeypatch.setattr(CR, "iris_shared_mailboxes_config",
                        lambda: CR.IrisSharedMailboxesConfig(max_per_organization=1))
    limit = _create_shared(client, auth_headers(owner), address="facturas@acme.example")
    assert limit.status_code == 409
    assert limit.get_json()["messageKey"] == "irisSharedMailboxMailboxLimit"


def test_a_shared_mailbox_can_be_connected_by_imap(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    response = _create_shared(client, auth_headers(owner), provider="imap", address=None, imap={
        "host": "imap.acme.example", "port": 993, "username": "soporte@acme.example", "password": "app-pass",
    })
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["authMode"] == "imap"
    assert "password" not in response.get_json()
    connection_id = response.get_json()["id"]
    with app.app_context():
        stored = build_repository(IrisMailboxConnectionRepository).get_by_id(connection_id)
        assert stored.imap_password == "app-pass" and stored.imap_port == 993


# --------------------------------------------------------------------------- quién ve qué

def test_only_people_with_explicit_access_see_the_shared_mailbox_and_its_analyses(client, app, make_user,
                                                                                  auth_headers):
    owner, viewer, outsider = _organization(app, make_user, "acme", 3)
    connection_id, analysis_id = _shared_with_mail(client, app, owner, auth_headers(owner))
    assert client.put(f"/iris/mailbox/shared/{connection_id}/members/{viewer.id}", headers=auth_headers(owner),
                      json={"access": "viewer"}).status_code == 200

    listed = client.get("/iris/mailbox/shared", headers=auth_headers(viewer)).get_json()["mailboxes"]
    assert [(mailbox["id"], mailbox["myAccess"]) for mailbox in listed] == [(connection_id, "viewer")]
    analyses = client.get(f"/iris/mailbox/shared/{connection_id}/analyses", headers=auth_headers(viewer)).get_json()
    assert [item["analysisId"] for item in analyses["analyses"]] == [analysis_id]
    report = client.get(f"/iris/mailbox/shared/{connection_id}/analyses/{analysis_id}", headers=auth_headers(viewer))
    assert report.status_code == 200

    # Un miembro de la misma organización sin acceso explícito no ve nada.
    assert client.get("/iris/mailbox/shared", headers=auth_headers(outsider)).get_json()["mailboxes"] == []
    for url in (f"/iris/mailbox/shared/{connection_id}/analyses",
                f"/iris/mailbox/shared/{connection_id}/analyses/{analysis_id}"):
        assert client.get(url, headers=auth_headers(outsider)).status_code == 404
    # Ni por la ruta de siempre de los análisis personales.
    assert client.get(f"/iris/results/{analysis_id}", headers=auth_headers(viewer)).status_code == 404
    assert client.get(f"/iris/results/{analysis_id}", headers=auth_headers(outsider)).status_code == 404


def test_another_organization_never_sees_it_even_if_granted(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    stranger_owner, = _organization(app, make_user, "globex", 1)
    connection_id, analysis_id = _shared_with_mail(client, app, owner, auth_headers(owner))

    grant = client.put(f"/iris/mailbox/shared/{connection_id}/members/{stranger_owner.id}",
                       headers=auth_headers(owner), json={"access": "manager"})
    assert grant.status_code == 409
    assert grant.get_json()["messageKey"] == "irisSharedMailboxMemberNotInOrganization"
    for url in (f"/iris/mailbox/shared/{connection_id}/analyses",
                f"/iris/mailbox/shared/{connection_id}/analyses/{analysis_id}",
                f"/iris/mailbox/shared/{connection_id}/members",
                f"/iris/mailbox/connections/{connection_id}/health"):
        assert client.get(url, headers=auth_headers(stranger_owner)).status_code == 404


def test_leaving_the_organization_removes_access_at_once(client, app, make_user, auth_headers):
    owner, viewer = _organization(app, make_user, "acme", 2)
    connection_id, analysis_id = _shared_with_mail(client, app, owner, auth_headers(owner))
    client.put(f"/iris/mailbox/shared/{connection_id}/members/{viewer.id}", headers=auth_headers(owner),
               json={"access": "viewer"})
    _leave_organization(app, viewer.id)
    assert client.get("/iris/mailbox/shared", headers=auth_headers(viewer)).get_json()["mailboxes"] == []
    assert client.get(f"/iris/mailbox/shared/{connection_id}/analyses/{analysis_id}",
                      headers=auth_headers(viewer)).status_code == 404


def test_an_analysis_of_another_mailbox_is_not_reachable_through_a_shared_one(client, app, make_user,
                                                                             auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    with app.app_context():
        with UnitOfWork() as uow:
            personal = IrisAnalysisRepository(uow).save(IrisAnalysis(
                raw_headers="Subject: privado\n", title="privado", user_id=owner.id, status="finished"))
            personal_id = personal.id
    response = client.get(f"/iris/mailbox/shared/{connection_id}/analyses/{personal_id}",
                          headers=auth_headers(owner))
    assert response.status_code == 404


def test_only_managers_decide_who_has_access(client, app, make_user, auth_headers):
    owner, viewer, other = _organization(app, make_user, "acme", 3)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    client.put(f"/iris/mailbox/shared/{connection_id}/members/{viewer.id}", headers=auth_headers(owner),
               json={"access": "viewer"})

    assert client.put(f"/iris/mailbox/shared/{connection_id}/members/{other.id}", headers=auth_headers(viewer),
                      json={"access": "viewer"}).status_code == 404
    assert client.get(f"/iris/mailbox/shared/{connection_id}/members", headers=auth_headers(viewer)).status_code == 404
    assert client.delete(f"/iris/mailbox/connections/{connection_id}", headers=auth_headers(viewer)).status_code == 404

    members = client.get(f"/iris/mailbox/shared/{connection_id}/members", headers=auth_headers(owner)).get_json()
    assert {(member["userId"], member["access"]) for member in members["members"]} == {
        (owner.id, "manager"), (viewer.id, "viewer")}


def test_a_delegated_manager_can_administer_but_the_last_manager_cannot_be_removed(client, app, make_user,
                                                                                   auth_headers):
    owner, deputy = _organization(app, make_user, "acme", 2)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    client.put(f"/iris/mailbox/shared/{connection_id}/members/{deputy.id}", headers=auth_headers(owner),
               json={"access": "manager"})

    # El responsable delegado usa los mismos endpoints de conexión que un dueño.
    health = client.get(f"/iris/mailbox/connections/{connection_id}/health", headers=auth_headers(deputy))
    assert health.status_code == 200
    assert client.delete(f"/iris/mailbox/shared/{connection_id}/members/{owner.id}",
                         headers=auth_headers(deputy)).status_code == 204
    last = client.delete(f"/iris/mailbox/shared/{connection_id}/members/{deputy.id}", headers=auth_headers(deputy))
    assert last.status_code == 409
    assert last.get_json()["messageKey"] == "irisSharedMailboxLastManager"
    demote = client.put(f"/iris/mailbox/shared/{connection_id}/members/{deputy.id}", headers=auth_headers(deputy),
                        json={"access": "viewer"})
    assert demote.status_code == 409


def test_the_member_limit_is_enforced(client, app, make_user, auth_headers, monkeypatch):
    owner, first, second = _organization(app, make_user, "acme", 3)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    monkeypatch.setattr(CR, "iris_shared_mailboxes_config",
                        lambda: CR.IrisSharedMailboxesConfig(max_members_per_mailbox=2))
    assert client.put(f"/iris/mailbox/shared/{connection_id}/members/{first.id}", headers=auth_headers(owner),
                      json={"access": "viewer"}).status_code == 200
    over = client.put(f"/iris/mailbox/shared/{connection_id}/members/{second.id}", headers=auth_headers(owner),
                      json={"access": "viewer"})
    assert over.status_code == 409 and over.get_json()["messageKey"] == "irisSharedMailboxMemberLimit"


def test_no_actions_are_offered_on_a_shared_mailbox(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    with app.app_context():
        with UnitOfWork() as uow:
            connection = IrisMailboxConnectionRepository(uow).get_by_id(connection_id)
            connection.remediation_enabled = True
            connection.scopes = "Mail.ReadWrite"
    assert IrisMailboxManager.can_act_on(_connection(app, connection_id)) is False


# --------------------------------------------------------------------------- sync, reautenticación y rotación

def test_the_shared_mailbox_is_read_with_the_service_account_token(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    connection_id, _ = _shared_with_mail(client, app, owner, auth_headers(owner))
    connection = _connection(app, connection_id)
    assert connection.last_error is None and connection.status == "active"
    with app.app_context():
        stored = build_repository(IrisMailboxConnectionRepository).get_by_id(connection_id)
        assert stored.access_token == "service-token"


def test_if_the_person_who_connected_it_leaves_the_mailbox_stops_syncing(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    _leave_organization(app, owner.id)
    provider = _Provider()
    _sync(app, connection_id, provider)
    assert provider.listed == []
    connection = _connection(app, connection_id)
    assert connection.status == "paused" and "ya no pertenece" in connection.last_error


def test_a_rejected_service_account_asks_for_reconnection(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    connection_id = _create_shared(client, auth_headers(owner)).get_json()["id"]
    import requests
    provider = _Provider()
    rejected = requests.HTTPError(response=mock.Mock(status_code=401))
    provider.acquire_service_token = mock.Mock(side_effect=rejected)
    with mock.patch.object(mailbox_managers_mod.OutboxDispatcher, "dispatch"):
        _sync(app, connection_id, provider)
    assert _connection(app, connection_id).status == "reauth_required"


def test_a_personal_imap_mailbox_is_verified_and_the_password_never_leaves(client, app, regular_user, auth_headers):
    headers = auth_headers(regular_user)
    body = {"host": "imap.correo.example", "port": 993, "username": "ana@correo.example", "password": "app-pass"}
    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider(rejects_password=True)):
        rejected = client.post("/iris/mailbox/imap", headers=headers, json=body)
    assert rejected.status_code == 422 and rejected.get_json()["messageKey"] == "irisMailboxCredentialsRejected"

    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider()):
        response = client.post("/iris/mailbox/imap", headers=headers, json=body)
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["provider"] == "imap" and response.get_json()["authMode"] == "imap"
    listed = client.get("/iris/mailbox/connections", headers=headers).get_json()["connections"]
    assert [connection["accountEmail"] for connection in listed] == ["ana@correo.example"]
    assert "app-pass" not in str(listed)


def test_an_imap_port_other_than_tls_is_rejected_before_connecting(client, regular_user, auth_headers):
    response = client.post("/iris/mailbox/imap", headers=auth_headers(regular_user), json={
        "host": "imap.correo.example", "port": 143, "username": "ana@correo.example", "password": "x"})
    assert response.status_code == 422
    assert response.get_json()["messageKey"] == "irisMailboxServerUnreachable"


def test_a_changed_imap_password_asks_for_reconnection_and_rotation_fixes_it(client, app, regular_user,
                                                                            auth_headers):
    headers = auth_headers(regular_user)
    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider()):
        connection_id = client.post("/iris/mailbox/imap", headers=headers, json={
            "host": "imap.correo.example", "port": 993, "username": "ana@correo.example", "password": "vieja",
        }).get_json()["connectionId"]

    with mock.patch.object(mailbox_managers_mod.OutboxDispatcher, "dispatch"):
        _sync(app, connection_id, _Provider(rejects_password=True))
    assert _connection(app, connection_id).status == "reauth_required"

    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider(rejects_password=True)):
        still_wrong = client.put(f"/iris/mailbox/connections/{connection_id}/credentials", headers=headers,
                                 json={"password": "tampoco"})
    assert still_wrong.status_code == 422
    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider()):
        rotated = client.put(f"/iris/mailbox/connections/{connection_id}/credentials", headers=headers,
                             json={"password": "nueva"})
    assert rotated.status_code == 200 and rotated.get_json()["status"] == "active"
    with app.app_context():
        assert build_repository(IrisMailboxConnectionRepository).get_by_id(connection_id).imap_password == "nueva"


def test_imap_connections_are_never_subscribed_to_events(client, app, regular_user, auth_headers, monkeypatch):
    monkeypatch.setattr(CR, "iris_mailbox_events_config", lambda: CR.IrisMailboxEventsConfig(enabled=True))
    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider()):
        client.post("/iris/mailbox/imap", headers=auth_headers(regular_user), json={
            "host": "imap.correo.example", "port": 993, "username": "ana@correo.example", "password": "x"})
    queue = _FakeQueue()
    with app.app_context():
        assert IrisMailboxEventManager(task_queue=queue).run_maintenance() == 0


# --------------------------------------------------------------------------- varias carpetas

def test_a_connection_can_watch_several_validated_folders(client, app, make_user, auth_headers, monkeypatch):
    owner, = _organization(app, make_user, "acme", 1)
    headers = auth_headers(owner)
    connection_id = _create_shared(client, headers).get_json()["id"]
    provider = _Provider(folders=("INBOX", "Label_Facturas", "Label_Proveedores"))

    with mock.patch.object(mailbox_managers_mod, "get_connector", return_value=provider):
        missing = client.put(f"/iris/mailbox/connections/{connection_id}/folders", headers=headers,
                             json={"folders": ["No_Existe"]})
        assert missing.status_code == 400
        monkeypatch.setattr(CR, "iris_shared_mailboxes_config",
                            lambda: CR.IrisSharedMailboxesConfig(max_folders_per_connection=2))
        too_many = client.put(f"/iris/mailbox/connections/{connection_id}/folders", headers=headers,
                              json={"folders": ["Label_Facturas", "Label_Proveedores"]})
        assert too_many.status_code == 400
        monkeypatch.undo()
        response = client.put(f"/iris/mailbox/connections/{connection_id}/folders", headers=headers,
                              json={"folders": ["Label_Facturas", "Label_Proveedores"]})
    assert response.status_code == 200, response.get_json()
    assert [folder["id"] for folder in response.get_json()["additionalFolders"]] == ["Label_Facturas",
                                                                                    "Label_Proveedores"]

    _sync(app, connection_id, provider)
    # Una lectura por carpeta vigilada, cada una con su cursor (ninguno aún).
    assert provider.listed == [None, None, None]
    assert _connection(app, connection_id).sync_cursor.startswith('{"folders":')


def test_a_personal_and_a_shared_connection_of_the_same_account_do_not_mix(client, app, make_user, auth_headers):
    owner, = _organization(app, make_user, "acme", 1)
    headers = auth_headers(owner)
    imap = {"host": "imap.acme.example", "port": 993, "username": "soporte@acme.example", "password": "x"}
    assert _create_shared(client, headers, provider="imap", address=None, imap=imap).status_code == 201
    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider()):
        personal = client.post("/iris/mailbox/imap", headers=headers, json=imap)
    assert personal.status_code == 409
    assert personal.get_json()["messageKey"] == "irisSharedMailboxAlreadyConnected"

    with mock.patch.object(mailbox_accounts_mod, "get_connector", return_value=_Provider()):
        client.post("/iris/mailbox/imap", headers=headers, json={**imap, "username": "ana@acme.example"})
    shared_over_personal = _create_shared(client, headers, provider="imap", address=None,
                                          imap={**imap, "username": "ana@acme.example"})
    assert shared_over_personal.status_code == 409
