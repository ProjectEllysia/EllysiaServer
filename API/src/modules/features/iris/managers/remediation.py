"""
IrisRemediationManager — actuar sobre el correo del buzón conectado, con auditoría y deshacer.

Hasta aquí Iris detectaba y avisaba; ahora puede además poner en cuarentena,
marcar como sospechoso, mandar a spam o a la papelera un correo que llegó por
un buzón conectado (Gmail o Microsoft 365). Es la parte con más capacidad de
hacer daño de todo el roadmap —tocar el correo de una persona—, así que tiene
estas garantías, en este orden:

- **Nada automático.** Iris recomienda una acción según el veredicto
  (``services/remediation.recommend_action``); solo actúa cuando el usuario lo
  pide. Un falso positivo nunca mueve un correo por su cuenta.
- **Permiso propio.** Hace falta ``iris_mailbox_action``, distinto de
  ``iris_delete`` (que borra un análisis, no un correo), y que la conexión se
  hiciera con las acciones activadas y el proveedor concediera el permiso de
  escritura.
- **Motivo y confirmación.** Toda acción lleva el motivo del usuario; las que
  sacan el correo de la bandeja exigen además confirmarlas.
- **Auditoría.** Cada acción y cada deshacer es una fila ``IrisActionAudit``
  con actor, motivo, permiso y hora, escrita **antes** de hablar con el
  proveedor.
- **Idempotencia.** Repetir la petición con la misma clave, o pedir otra vez
  una acción que ya está aplicada, devuelve la que había sin repetirla; y no
  se admite otra acción sobre el mismo correo mientras una está en curso.
- **Deshacer.** Todas las acciones son reversibles en el proveedor (ninguna
  borra para siempre) y la auditoría guarda dónde estaba el correo.

La acción la hace un worker (cola ``iris.remediation``), encolada por la outbox
en la misma transacción que su fila de auditoría.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

import requests

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.system.taskqueue import TaskTrackingMixin, job_context
from src.modules.system.taskqueue.dispatcher import OutboxDispatcher
from src.modules.system.taskqueue.outbox import build_dispatch
from src.modules.system.taskqueue.outbox_repository import TaskDispatchRepository
from src.modules.users import AttributeType, UserManager

from ..exceptions import (
    IrisInvalidInputError,
    IrisMailboxActionConfirmationRequiredError,
    IrisMailboxActionInProgressError,
    IrisMailboxActionNotFoundError,
    IrisMailboxActionNotReversibleError,
    IrisMailboxActionUnavailableError,
    IrisMailboxReauthRequiredError,
)
from ..model import IrisActionAudit, IrisAnalysis, MailboxAction, MailboxActionStatus
from ..repositories import IrisActionAuditRepository, IrisAnalysisRepository, IrisMailboxConnectionRepository
from ..services.remediation import clean_reason, is_destructive, recommend_action
from .analysis import IrisManager
from .mailbox import IrisMailboxManager

logger = logging.getLogger(__name__)

#: Tiempo máximo del job en la cola, en segundos: unas pocas llamadas a la API
#: del proveedor, cada una con su propio tiempo máximo.
_JOB_TIMEOUT_SECONDS = 180

#: Una acción ``running`` más vieja que esto se da por abandonada al arrancar.
_STALE_AFTER = timedelta(minutes=15)

#: Motivo con que se cierra una acción que un worker dejó a medias. No se sabe
#: si el proveedor llegó a aplicarla: el usuario lo ve en su buzón.
_INTERRUPTED_ERROR = "interrupted: el worker se detuvo a mitad; comprueba el correo en tu buzón"

#: Longitud máxima del error que se guarda.
_MAX_ERROR_LENGTH = 1000


def _invalid_input(text: str) -> IrisInvalidInputError:
    """Error de validación cuyo mensaje se enseña tal cual al usuario.

    Args:
        text: Qué falló, en castellano.

    Returns:
        IrisInvalidInputError: Con ``user_message`` igual a ``text``.
    """
    return IrisInvalidInputError(text, user_message=text)


def _serialize(audit: IrisActionAudit) -> Dict[str, Any]:
    """Serializa una fila de auditoría para la API.

    Args:
        audit: Fila.

    Returns:
        dict: ``actionId``, ``analysisId``, ``connectionId``, ``provider``,
            ``action``, ``status``, ``isDestructive``, ``isRollback``,
            ``rollbackOfId``, ``reason``, ``actor``, ``permission``,
            ``wasRecommended``, ``error``, ``createdAt``, ``startedAt`` y
            ``completedAt``.
    """
    return {
        "actionId": audit.id,
        "analysisId": audit.analysis_id,
        "connectionId": audit.connection_id,
        "provider": audit.provider,
        "action": audit.action,
        "status": audit.status,
        "isDestructive": audit.is_destructive,
        "isRollback": audit.is_rollback,
        "rollbackOfId": audit.rollback_of_id,
        "reason": audit.reason,
        "actor": audit.actor_username,
        "permission": audit.permission,
        "wasRecommended": audit.was_recommended,
        "error": audit.error,
        "createdAt": isoformat_utc(audit.created_at),
        "startedAt": isoformat_utc(audit.started_at),
        "completedAt": isoformat_utc(audit.completed_at),
    }


def _unavailable_reason(analysis: IrisAnalysis) -> Optional[str]:
    """Por qué no se puede actuar sobre el correo de un análisis, o ``None`` si se puede.

    Args:
        analysis: Análisis.

    Returns:
        Optional[str]: ``not_from_mailbox``, ``connection_gone``,
            ``reauth_required``, ``missing_scope`` o ``None``.
    """
    if analysis.connection_id is None or not analysis.source_message_uid:
        return "not_from_mailbox"
    connection = build_repository(IrisMailboxConnectionRepository).get_by_id(analysis.connection_id)
    if connection is None:
        return "connection_gone"
    if connection.status == "reauth_required":
        return "reauth_required"
    if not IrisMailboxManager.can_act_on(connection):
        return "missing_scope"
    return None


def _raise_if_unavailable(analysis: IrisAnalysis) -> None:
    """Lanza el error que corresponde si no se puede actuar sobre el correo.

    Args:
        analysis: Análisis.

    Raises:
        IrisMailboxReauthRequiredError: Si hay que volver a conectar el buzón.
        IrisMailboxActionUnavailableError: Por cualquier otro motivo.
    """
    reason = _unavailable_reason(analysis)
    if reason == "reauth_required":
        raise IrisMailboxReauthRequiredError()
    if reason is not None:
        raise IrisMailboxActionUnavailableError(reason)


def _dispatch(audit: IrisActionAudit, uow: UnitOfWork, task_category: str, external_id: str) -> int:
    """Guarda en la outbox el job que hará una acción, en la transacción de su auditoría.

    Args:
        audit: Fila de auditoría ya guardada (con id).
        uow: Transacción en curso.
        task_category: Categoría de cola.
        external_id: Id lógico del job.

    Returns:
        int: Id de la fila de outbox, para publicarla tras el commit.
    """
    return TaskDispatchRepository(uow).save(build_dispatch(
        func=IrisRemediationManager.execute_mailbox_action,
        name=f"IrisMailboxAction-{audit.id}",
        category=task_category,
        args=(audit.id,),
        external_id=external_id,
        timeout=_JOB_TIMEOUT_SECONDS,
    )).id


def _apply(connector, access_token: str, audit: IrisActionAudit, original: Optional[IrisActionAudit]):
    """Hace la acción (o su deshacer) en el proveedor.

    Args:
        connector: Conector del proveedor.
        access_token: Token de acceso vigente.
        audit: Fila que se ejecuta.
        original: Fila que se deshace, si ``audit`` es un deshacer.

    Returns:
        tuple: ``(id del mensaje después, estado anterior)``; el estado es
            ``None`` en un deshacer.
    """
    config = CR.iris_remediation_config()
    message_id = audit.provider_message_id
    if audit.is_rollback:
        new_id = connector.undo(access_token, original.action, message_id, original.previous_state or {},
                                config.suspicious_label_name)
        return new_id, None
    if audit.action == MailboxAction.QUARANTINE.value:
        result = connector.quarantine(access_token, message_id, config.quarantine_folder_name)
    elif audit.action == MailboxAction.LABEL.value:
        result = connector.label(access_token, message_id, config.suspicious_label_name)
    elif audit.action == MailboxAction.REPORT_PHISHING.value:
        result = connector.report_phishing(access_token, message_id)
    else:
        result = connector.delete(access_token, message_id)
    return result.provider_message_id, result.previous_state


def _describe_error(error: Exception) -> str:
    """Motivo legible de un fallo del proveedor, para la auditoría.

    Args:
        error: La excepción.

    Returns:
        str: ``http_<código>`` con el principio de la respuesta si fue un error
            HTTP del proveedor; si no, el nombre y el texto de la excepción.
    """
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f"http_{error.response.status_code}: {error.response.text[:300]}"
    return f"{type(error).__name__}: {error}"[:_MAX_ERROR_LENGTH]


def _finish(audit_id: int, *, status: str, error: Optional[str] = None, message_id_after: Optional[str] = None,
            previous_state: Optional[dict] = None) -> None:
    """Anota cómo acabó una acción y, si se aplicó, sus efectos en el análisis y en la fila deshecha.

    Si el proveedor le dio al mensaje un id nuevo (Graph al moverlo), el
    análisis pasa a apuntar a él: así la siguiente acción, o el deshacer,
    encuentran el mensaje, y un sync que lo vuelva a ver (al deshacer una
    cuarentena vuelve a la bandeja) reconoce que ya está analizado.

    Args:
        audit_id: Acción.
        status: ``succeeded`` o ``failed``.
        error: Motivo del fallo. Por defecto ``None``.
        message_id_after: Id del mensaje tras la acción. Por defecto ``None``.
        previous_state: Dónde estaba antes (solo acciones, no deshacer). Por
            defecto ``None``.
    """
    now = utcnow_naive()
    with UnitOfWork() as uow:
        repo = IrisActionAuditRepository(uow)
        audit = repo.get_by_id(audit_id)
        if audit is None:
            return
        audit.status = status
        audit.error = error[:_MAX_ERROR_LENGTH] if error else None
        audit.completed_at = now
        if status != MailboxActionStatus.SUCCEEDED.value:
            return
        audit.provider_message_id_after = message_id_after
        if previous_state is not None:
            audit.previous_state = previous_state
        if audit.is_rollback and audit.rollback_of_id is not None:
            original = repo.get_by_id(audit.rollback_of_id)
            if original is not None:
                original.status = MailboxActionStatus.ROLLED_BACK.value
        if audit.analysis_id is not None and message_id_after and message_id_after != audit.provider_message_id:
            analysis = IrisAnalysisRepository(uow).get_by_id(audit.analysis_id)
            if analysis is not None:
                analysis.source_message_uid = message_id_after


def _run_mailbox_action(audit_id: int) -> None:
    """Cuerpo del job: reclama la acción, la hace en el proveedor y anota el resultado.

    Un segundo envío del mismo job no hace nada: solo actúa quien reclama la
    fila en ``pending``.

    Args:
        audit_id: Fila de auditoría de la acción (o del deshacer).
    """
    with job_context():
        with UnitOfWork() as uow:
            if not IrisActionAuditRepository(uow).claim_for_run(audit_id, utcnow_naive()):
                return
        audit = build_repository(IrisActionAuditRepository).get_by_id(audit_id)
        original = (build_repository(IrisActionAuditRepository).get_by_id(audit.rollback_of_id)
                    if audit.is_rollback else None)
        if audit.connection_id is None:
            _finish(audit_id, status=MailboxActionStatus.FAILED.value, error="connection_gone")
            return
        try:
            _, access_token, connector = IrisMailboxManager().authorize_connection(audit.connection_id)
            message_id_after, previous_state = _apply(connector, access_token, audit, original)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"La acción {audit_id} sobre el buzón falló: {e}")
            _finish(audit_id, status=MailboxActionStatus.FAILED.value, error=_describe_error(e))
            return
        _finish(audit_id, status=MailboxActionStatus.SUCCEEDED.value, message_id_after=message_id_after,
                previous_state=previous_state)
        logger.info(f"Acción {audit.action} aplicada sobre el correo del análisis {audit.analysis_id} ({audit_id})")


class IrisRemediationManager(TaskTrackingMixin):
    """Recomendaciones y acciones sobre el correo del buzón conectado, auditadas y reversibles."""

    EXTERNAL_ID_PREFIX = "iris-mailbox-action:"
    TASK_CATEGORY = "iris.remediation"

    @staticmethod
    def get_message_actions(analysis_id: int, user_id: int) -> Dict[str, Any]:
        """Qué recomienda Iris hacer con el correo de un análisis, qué se puede hacer y qué se hizo.

        Args:
            analysis_id: Análisis.
            user_id: Dueño.

        Returns:
            dict: ``analysisId``, ``verdict``, ``recommendedAction`` (o
                ``None``), ``canAct``, ``unavailableReason`` (``None`` si se
                puede actuar), ``actions`` (las cuatro, con ``isDestructive``)
                e ``history`` (la auditoría del correo, de la más antigua a la
                más reciente).

        Raises:
            IrisAnalysisNotFoundError: Si no existe o no es suyo.
        """
        analysis = IrisManager.assert_analysis_ownership(analysis_id, user_id)
        reason = _unavailable_reason(analysis)
        history = build_repository(IrisActionAuditRepository).get_by_analysis(analysis_id)
        return {
            "analysisId": analysis.id,
            "verdict": analysis.verdict,
            "recommendedAction": recommend_action(analysis.verdict),
            "canAct": reason is None,
            "unavailableReason": reason,
            "actions": [{"action": action.value, "isDestructive": is_destructive(action.value)}
                        for action in MailboxAction],
            "history": [_serialize(audit) for audit in history],
        }

    @staticmethod
    def list_actions(user_id: int, page: int = 1, per_page: int = 50) -> Dict[str, Any]:
        """Registro de todas las acciones sobre el buzón que ha hecho un usuario.

        Args:
            user_id: Usuario.
            page: Página, empezando en 1. Por defecto ``1``.
            per_page: Filas por página. Por defecto ``50``.

        Returns:
            dict: ``actions``, ``total``, ``page`` y ``perPage``.
        """
        audits, total = build_repository(IrisActionAuditRepository).get_page_by_actor(user_id, page, per_page)
        return {"actions": [_serialize(audit) for audit in audits], "total": total, "page": page, "perPage": per_page}

    def request_action(self, analysis_id: int, user_id: int, action: str, reason: str,
                       confirm: bool = False, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Pide una acción sobre el correo de un análisis; la hace un worker.

        Args:
            analysis_id: Análisis del correo.
            user_id: Quien la pide; debe ser el dueño del análisis.
            action: Valor de ``MailboxAction``.
            reason: Por qué (al menos ``MIN_REASON_LENGTH`` caracteres).
            confirm: Confirmación explícita; obligatoria en las acciones que
                sacan el correo de la bandeja. Por defecto ``False``.
            idempotency_key: Clave del cliente para que un reintento de la misma
                petición no la haga dos veces. Por defecto ``None``.

        Returns:
            dict: La acción (``_serialize``) con ``isRepeat``: ``True`` si ya
                existía (misma clave, o la acción ya estaba aplicada) y no se ha
                vuelto a hacer.

        Raises:
            SurfaceDisabledError: Si la superficie ``mailboxConnectors`` está
                cerrada para el usuario.
            IrisAnalysisNotFoundError: Si el análisis no existe o no es suyo.
            IrisInvalidInputError: Si la acción no existe o falta el motivo.
            IrisMailboxActionConfirmationRequiredError: Si es destructiva y no
                se confirmó.
            IrisMailboxActionUnavailableError / IrisMailboxReauthRequiredError:
                Si no se puede actuar sobre ese correo.
            IrisMailboxActionInProgressError: Si ya hay otra en curso sobre él.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.MAILBOX_CONNECTORS, user_id)
        audit_repo = build_repository(IrisActionAuditRepository)
        if idempotency_key:
            existing = audit_repo.get_by_idempotency_key(user_id, idempotency_key)
            if existing is not None:
                return {**_serialize(existing), "isRepeat": True}

        analysis = IrisManager.assert_analysis_ownership(analysis_id, user_id)
        if action not in {member.value for member in MailboxAction}:
            raise _invalid_input(f"Acción desconocida: {action!r}.")
        try:
            cleaned_reason = clean_reason(reason)
        except ValueError as e:
            raise _invalid_input(str(e)) from e
        if is_destructive(action) and not confirm:
            raise IrisMailboxActionConfirmationRequiredError()
        _raise_if_unavailable(analysis)

        standing = audit_repo.get_standing_action(analysis_id, action)
        if standing is not None:
            return {**_serialize(standing), "isRepeat": True}
        if audit_repo.has_in_flight_for_analysis(analysis_id):
            raise IrisMailboxActionInProgressError()

        actor = UserManager().get_user_by_id(user_id)
        connection = build_repository(IrisMailboxConnectionRepository).get_by_id(analysis.connection_id)
        with UnitOfWork() as uow:
            audit = IrisActionAuditRepository(uow).save(IrisActionAudit(
                actor_id=user_id, actor_username=actor.username if actor else str(user_id),
                connection_id=analysis.connection_id, analysis_id=analysis.id, provider=connection.provider,
                provider_message_id=analysis.source_message_uid, action=action,
                is_destructive=is_destructive(action), is_rollback=False,
                status=MailboxActionStatus.PENDING.value, reason=cleaned_reason,
                permission=AttributeType.IRIS_MAILBOX_ACTION.db_name,
                was_recommended=recommend_action(analysis.verdict) == action,
                idempotency_key=idempotency_key or None,
            ))
            dispatch_id = _dispatch(audit, uow, self.TASK_CATEGORY, self.external_id_for(audit.id))
            payload = {**_serialize(audit), "isRepeat": False}
            uow.commit_for_handoff()
        OutboxDispatcher.dispatch(dispatch_id, task_queue=self._task_queue)
        logger.info(f"Acción {action} pedida por el usuario {user_id} sobre el análisis {analysis_id}")
        return payload

    def request_rollback(self, action_id: int, user_id: int, reason: str) -> Dict[str, Any]:
        """Pide deshacer una acción aplicada; lo hace un worker.

        Args:
            action_id: Acción a deshacer; debe haberla hecho el usuario.
            user_id: Quien lo pide.
            reason: Por qué se deshace.

        Returns:
            dict: La fila del deshacer (``_serialize``), en ``pending``.

        Raises:
            SurfaceDisabledError: Si la superficie está cerrada.
            IrisMailboxActionNotFoundError: Si no existe o no la hizo el usuario.
            IrisInvalidInputError: Si falta el motivo.
            IrisMailboxActionNotReversibleError: Si no se aplicó, ya se deshizo
                o es ella misma un deshacer.
            IrisMailboxActionInProgressError: Si hay otra acción en curso sobre
                el mismo correo.
            IrisMailboxReauthRequiredError: Si hay que volver a conectar el buzón.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.MAILBOX_CONNECTORS, user_id)
        original = build_repository(IrisActionAuditRepository).get_by_id(action_id)
        if original is None or original.actor_id != user_id:
            raise IrisMailboxActionNotFoundError(action_id)
        try:
            cleaned_reason = clean_reason(reason)
        except ValueError as e:
            raise _invalid_input(str(e)) from e
        if original.is_rollback or original.status != MailboxActionStatus.SUCCEEDED.value:
            raise IrisMailboxActionNotReversibleError()
        if original.analysis_id is not None and build_repository(IrisActionAuditRepository).has_in_flight_for_analysis(
                original.analysis_id):
            raise IrisMailboxActionInProgressError()
        connection = (build_repository(IrisMailboxConnectionRepository).get_by_id(original.connection_id)
                      if original.connection_id is not None else None)
        if connection is None:
            raise IrisMailboxActionUnavailableError("connection_gone")
        if connection.status == "reauth_required":
            raise IrisMailboxReauthRequiredError()

        actor = UserManager().get_user_by_id(user_id)
        with UnitOfWork() as uow:
            audit = IrisActionAuditRepository(uow).save(IrisActionAudit(
                actor_id=user_id, actor_username=actor.username if actor else str(user_id),
                connection_id=original.connection_id, analysis_id=original.analysis_id,
                provider=original.provider,
                provider_message_id=original.provider_message_id_after or original.provider_message_id,
                action=original.action, is_destructive=False, is_rollback=True, rollback_of_id=original.id,
                status=MailboxActionStatus.PENDING.value, reason=cleaned_reason,
                permission=AttributeType.IRIS_MAILBOX_ACTION.db_name, was_recommended=False,
            ))
            dispatch_id = _dispatch(audit, uow, self.TASK_CATEGORY, self.external_id_for(audit.id))
            payload = _serialize(audit)
            uow.commit_for_handoff()
        OutboxDispatcher.dispatch(dispatch_id, task_queue=self._task_queue)
        logger.info(f"Deshacer de la acción {action_id} pedido por el usuario {user_id}")
        return payload

    @staticmethod
    def get_action(action_id: int, user_id: int) -> Dict[str, Any]:
        """Una acción del usuario, para sondear cómo acabó.

        Args:
            action_id: Acción.
            user_id: Quien la hizo.

        Returns:
            dict: La acción (``_serialize``).

        Raises:
            IrisMailboxActionNotFoundError: Si no existe o no la hizo el usuario.
        """
        audit = build_repository(IrisActionAuditRepository).get_by_id(action_id)
        if audit is None or audit.actor_id != user_id:
            raise IrisMailboxActionNotFoundError(action_id)
        return _serialize(audit)

    @staticmethod
    def reconcile_orphaned_actions() -> int:
        """Cierra como fallidas las acciones que un worker dejó a medias.

        Se llama al arrancar la API. No se sabe si el proveedor llegó a
        aplicarlas: el motivo que se anota se lo dice al usuario.

        Returns:
            int: Cuántas acciones se cerraron.
        """
        now = utcnow_naive()
        with UnitOfWork() as uow:
            return IrisActionAuditRepository(uow).fail_stale_running(now - _STALE_AFTER, _INTERRUPTED_ERROR, now)

    @staticmethod
    def execute_mailbox_action(audit_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            audit_id: Fila de auditoría de la acción o del deshacer.
        """
        _run_mailbox_action(audit_id)
