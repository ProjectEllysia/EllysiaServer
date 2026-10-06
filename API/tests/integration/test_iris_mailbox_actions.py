"""Acciones sobre el buzón conectado: nada sin permiso, motivo y confirmación; todo auditado y reversible.

El proveedor se sustituye por un conector falso que anota cada llamada, y el
job del worker se ejecuta directamente. Fija el gate de la fase: no hay acción
automática, cada acción deja actor, motivo, permiso y hora, repetirla no la
repite, dos acciones no se pisan, y cualquiera se puede deshacer.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest

import src.modules.system.config_reading as CR
import src.modules.features.iris.managers.mailbox as mailbox_managers_mod
from src.modules.features.iris.managers.remediation import IrisRemediationManager
from src.modules.features.iris.model import IrisActionAudit, IrisAnalysis, IrisMailboxConnection
from src.modules.features.iris.repositories import (
    IrisActionAuditRepository, IrisAnalysisRepository, IrisMailboxConnectionRepository,
)
from src.modules.features.iris.services.mailbox import ActionResult
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_BASE_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE, AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]
_ACTING_ATTRIBUTES = [*_BASE_ATTRIBUTES, AttributeType.IRIS_MAILBOX_ACTION.db_name]
_REASON = "Phishing confirmado por el analista"


class _ActingConnector:
    """Proveedor falso: anota las acciones y, como Graph, da un id nuevo al mover."""

    def __init__(self, fail_with: Exception | None = None):
        self.calls: list[tuple] = []
        self._fail_with = fail_with

    @staticmethod
    def can_act(scopes):
        return "gmail.modify" in (scopes or "")

    def _record(self, name, message_id, *extra):
        if self._fail_with is not None:
            raise self._fail_with
        self.calls.append((name, message_id, *extra))

    def quarantine(self, access_token, message_id, folder_name):
        self._record("quarantine", message_id, folder_name)
        return ActionResult(provider_message_id=f"{message_id}-q", previous_state={"parentFolderId": "inbox"})

    def label(self, access_token, message_id, label_name):
        self._record("label", message_id, label_name)
        return ActionResult(provider_message_id=message_id, previous_state={"categories": []})

    def report_phishing(self, access_token, message_id):
        self._record("report_phishing", message_id)
        return ActionResult(provider_message_id=f"{message_id}-junk", previous_state={"parentFolderId": "inbox"})

    def delete(self, access_token, message_id):
        self._record("delete", message_id)
        return ActionResult(provider_message_id=f"{message_id}-trash", previous_state={"parentFolderId": "inbox"})

    def undo(self, access_token, action, message_id, previous_state, label_name):
        self._record("undo", message_id, action, previous_state)
        return f"{message_id}-back"


@pytest.fixture
def owner(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_ACTING_ATTRIBUTES)
    return user, auth_headers(user)


def _mailbox_analysis(app, user_id: int, *, verdict: str = "Phishing", remediation_enabled: bool = True,
                      scopes: str = "openid https://www.googleapis.com/auth/gmail.modify",
                      status: str = "active") -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            connection = IrisMailboxConnectionRepository(uow).save(IrisMailboxConnection(
                user_id=user_id, provider="gmail", account_email="ana@corp.example", scopes=scopes,
                refresh_token="refresh", access_token="access",
                access_token_expires_at=utcnow_naive() + timedelta(hours=1),
                status=status, remediation_enabled=remediation_enabled,
            ))
            analysis = IrisAnalysisRepository(uow).save(IrisAnalysis(
                raw_headers="From: a@evil.example\r\nSubject: x\r\n", user_id=user_id, status="finished",
                verdict=verdict, total_score=10.0, connection_id=connection.id, source_message_uid="m1",
            ))
            return analysis.id


def _request(client, headers, analysis_id, action="quarantine", **body):
    return client.post(f"/iris/mailbox/messages/{analysis_id}/actions", headers=headers,
                       json={"action": action, "reason": _REASON, "confirm": True, **body})


def _run(app, connector, action_id: int) -> None:
    with app.app_context(), mock.patch.object(mailbox_managers_mod, "get_connector", return_value=connector):
        IrisRemediationManager.execute_mailbox_action(action_id)


def _audit(app, action_id: int) -> IrisActionAudit:
    with app.app_context():
        return build_repository(IrisActionAuditRepository).get_by_id(action_id)


# --------------------------------------------------------------------------- recomendar no es actuar

def test_iris_recommends_but_does_nothing_on_its_own(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id, verdict="Phishing")

    body = client.get(f"/iris/mailbox/messages/{analysis_id}/actions", headers=headers).get_json()

    assert body["recommendedAction"] == "quarantine" and body["canAct"] is True
    assert {option["action"]: option["isDestructive"] for option in body["actions"]} == {
        "quarantine": True, "label": False, "report_phishing": True, "delete": True}
    assert body["history"] == [], "ver el correo no crea ninguna acción"


def test_a_suspicious_email_is_recommended_a_label(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id, verdict="Suspicious")
    assert client.get(f"/iris/mailbox/messages/{analysis_id}/actions",
                      headers=headers).get_json()["recommendedAction"] == "label"


# --------------------------------------------------------------------------- permiso, motivo, confirmación

def test_a_destructive_action_needs_explicit_confirmation(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)

    response = _request(client, headers, analysis_id, confirm=False)

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "irisMailboxActionConfirmationRequired"


def test_labelling_does_not_need_confirmation(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    assert _request(client, headers, analysis_id, action="label", confirm=False).status_code == 202


def test_an_action_needs_a_reason(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    assert _request(client, headers, analysis_id, reason="ok").status_code == 400


def test_without_the_mailbox_permission_nothing_can_be_done(client, app, make_user, auth_headers):
    """iris_delete (borrar un análisis) no autoriza a tocar el buzón."""
    user = make_user(role="role_user", attributes=_BASE_ATTRIBUTES)
    headers = auth_headers(user)
    analysis_id = _mailbox_analysis(app, user.id)

    assert client.get(f"/iris/mailbox/messages/{analysis_id}/actions", headers=headers).status_code == 200
    assert _request(client, headers, analysis_id).status_code == 403


def test_the_surface_is_closed_in_preview(client, app, owner, monkeypatch):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    monkeypatch.delenv("LAUNCH_MODE", raising=False)
    monkeypatch.setattr(CR, "launch_config", lambda: CR.LaunchConfig(
        configured_mode="preview", surfaces={surface.value: True for surface in CR.LaunchSurface}))
    assert _request(client, headers, analysis_id).status_code == 403


# --------------------------------------------------------------------------- cuándo no se puede

def test_a_read_only_connection_cannot_act(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id, remediation_enabled=False)

    options = client.get(f"/iris/mailbox/messages/{analysis_id}/actions", headers=headers).get_json()
    response = _request(client, headers, analysis_id)

    assert options["canAct"] is False and options["unavailableReason"] == "missing_scope"
    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisMailboxActionMissingScope"


def test_asking_for_actions_but_not_getting_the_scope_is_still_read_only(client, app, owner):
    """El usuario desmarcó el permiso de escritura en la pantalla de Google."""
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id, scopes="https://www.googleapis.com/auth/gmail.readonly")
    assert _request(client, headers, analysis_id).get_json()["messageKey"] == "irisMailboxActionMissingScope"


def test_an_email_that_did_not_come_from_a_mailbox_cannot_be_acted_on(client, app, owner):
    user, headers = owner
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysisRepository(uow).save(IrisAnalysis(
                raw_headers="From: a@b\r\n", user_id=user.id, status="finished", verdict="Phishing"))
            analysis_id = analysis.id

    response = _request(client, headers, analysis_id)
    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisMailboxActionNotFromMailbox"


def test_a_mailbox_that_needs_reconnection_cannot_act(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id, status="reauth_required")
    response = _request(client, headers, analysis_id)
    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisMailboxReauthRequired"


def test_the_email_of_another_user_does_not_exist(client, app, owner, make_user):
    _, headers = owner
    other = make_user(role="role_user", attributes=_ACTING_ATTRIBUTES)
    analysis_id = _mailbox_analysis(app, other.id)

    assert _request(client, headers, analysis_id).status_code == 404
    assert client.get(f"/iris/mailbox/messages/{analysis_id}/actions", headers=headers).status_code == 404


# --------------------------------------------------------------------------- auditoría y ejecución

def test_a_confirmed_action_is_audited_before_and_applied_by_the_worker(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    connector = _ActingConnector()

    requested = _request(client, headers, analysis_id)
    assert requested.status_code == 202
    body = requested.get_json()
    assert body["status"] == "pending" and connector.calls == [], "se audita antes de tocar el buzón"
    assert body["actor"] == user.username and body["reason"] == _REASON
    assert body["permission"] == "iris_mailbox_action" and body["createdAt"]
    assert body["wasRecommended"] is True and body["isDestructive"] is True

    _run(app, connector, body["actionId"])

    assert connector.calls == [("quarantine", "m1", "Iris Cuarentena")]
    audit = _audit(app, body["actionId"])
    assert audit.status == "succeeded" and audit.completed_at is not None
    assert audit.provider_message_id == "m1" and audit.provider_message_id_after == "m1-q"
    with app.app_context():
        analysis = build_repository(IrisAnalysisRepository).get_by_id(analysis_id)
    assert analysis.source_message_uid == "m1-q", "el análisis sigue al mensaje aunque el proveedor le cambie el id"


def test_the_same_job_twice_acts_once(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    connector = _ActingConnector()
    action_id = _request(client, headers, analysis_id).get_json()["actionId"]

    _run(app, connector, action_id)
    _run(app, connector, action_id)

    assert len(connector.calls) == 1


def test_asking_again_for_an_applied_action_does_not_repeat_it(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    connector = _ActingConnector()
    first = _request(client, headers, analysis_id).get_json()
    _run(app, connector, first["actionId"])

    again = _request(client, headers, analysis_id).get_json()

    assert again["isRepeat"] is True and again["actionId"] == first["actionId"]


def test_an_idempotency_key_returns_the_same_action(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)

    first = _request(client, headers, analysis_id, idempotencyKey="cliente-123456").get_json()
    retry = _request(client, headers, analysis_id, idempotencyKey="cliente-123456").get_json()

    assert retry["actionId"] == first["actionId"] and retry["isRepeat"] is True


def test_two_actions_on_the_same_email_do_not_overlap(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    _request(client, headers, analysis_id)

    response = _request(client, headers, analysis_id, action="delete")
    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisMailboxActionInProgress"


def test_a_provider_failure_is_recorded_and_changes_nothing(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    action_id = _request(client, headers, analysis_id).get_json()["actionId"]

    _run(app, _ActingConnector(fail_with=RuntimeError("proveedor caído")), action_id)

    audit = _audit(app, action_id)
    assert audit.status == "failed" and "proveedor caído" in audit.error
    with app.app_context():
        assert build_repository(IrisAnalysisRepository).get_by_id(analysis_id).source_message_uid == "m1"


# --------------------------------------------------------------------------- deshacer

def test_an_action_can_be_undone_and_is_audited_too(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    connector = _ActingConnector()
    action_id = _request(client, headers, analysis_id).get_json()["actionId"]
    _run(app, connector, action_id)

    rollback = client.post(f"/iris/mailbox/actions/{action_id}/rollback", headers=headers,
                           json={"reason": "Falso positivo: era la factura real"})
    assert rollback.status_code == 202
    rollback_body = rollback.get_json()
    assert rollback_body["isRollback"] is True and rollback_body["rollbackOfId"] == action_id
    _run(app, connector, rollback_body["actionId"])

    assert connector.calls[-1] == ("undo", "m1-q", "quarantine", {"parentFolderId": "inbox"})
    assert _audit(app, action_id).status == "rolled_back"
    assert _audit(app, rollback_body["actionId"]).status == "succeeded"
    history = client.get(f"/iris/mailbox/messages/{analysis_id}/actions", headers=headers).get_json()["history"]
    assert [entry["isRollback"] for entry in history] == [False, True]
    with app.app_context():
        assert build_repository(IrisAnalysisRepository).get_by_id(analysis_id).source_message_uid == "m1-q-back"


def test_an_undone_or_failed_action_cannot_be_undone_again(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    connector = _ActingConnector()
    action_id = _request(client, headers, analysis_id).get_json()["actionId"]
    _run(app, connector, action_id)
    rollback_id = client.post(f"/iris/mailbox/actions/{action_id}/rollback", headers=headers,
                              json={"reason": "Falso positivo"}).get_json()["actionId"]
    _run(app, connector, rollback_id)

    for target in (action_id, rollback_id):
        response = client.post(f"/iris/mailbox/actions/{target}/rollback", headers=headers,
                               json={"reason": "Otra vez, por si acaso"})
        assert response.status_code == 409
        assert response.get_json()["messageKey"] == "irisMailboxActionNotReversible"


def test_the_action_of_another_user_cannot_be_undone(client, app, owner, make_user, auth_headers):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    action_id = _request(client, headers, analysis_id).get_json()["actionId"]
    _run(app, _ActingConnector(), action_id)
    intruder = auth_headers(make_user(role="role_user", attributes=_ACTING_ATTRIBUTES))

    response = client.post(f"/iris/mailbox/actions/{action_id}/rollback", headers=intruder,
                           json={"reason": "No es mío"})
    assert response.status_code == 404
    assert client.get(f"/iris/mailbox/actions/{action_id}", headers=intruder).status_code == 404


# --------------------------------------------------------------------------- registro y huérfanos

def test_the_user_sees_the_log_of_every_action(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    connector = _ActingConnector()
    action_id = _request(client, headers, analysis_id, action="label", confirm=False).get_json()["actionId"]
    _run(app, connector, action_id)

    log = client.get("/iris/mailbox/actions", headers=headers).get_json()
    assert log["total"] == 1 and log["actions"][0]["action"] == "label"
    assert client.get(f"/iris/mailbox/actions/{action_id}", headers=headers).get_json()["status"] == "succeeded"


def test_an_action_a_worker_left_half_done_is_closed_at_startup(client, app, owner):
    user, headers = owner
    analysis_id = _mailbox_analysis(app, user.id)
    action_id = _request(client, headers, analysis_id).get_json()["actionId"]
    with app.app_context():
        with UnitOfWork() as uow:
            audit = IrisActionAuditRepository(uow).get_by_id(action_id)
            audit.status = "running"
            audit.started_at = utcnow_naive() - timedelta(hours=1)
        assert IrisRemediationManager.reconcile_orphaned_actions() == 1

    audit = _audit(app, action_id)
    assert audit.status == "failed" and audit.error.startswith("interrupted")


def test_the_connection_says_whether_it_can_act(client, app, owner):
    user, headers = owner
    _mailbox_analysis(app, user.id)
    connection = client.get("/iris/mailbox/connections", headers=headers).get_json()["connections"][0]
    assert connection["remediationEnabled"] is True and connection["canAct"] is True
