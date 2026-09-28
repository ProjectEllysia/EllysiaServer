"""
IrisMailboxEventManager — ingesta casi en tiempo real: el proveedor avisa y eso despierta el sync.

Sin eventos, un correo nuevo tarda hasta ``pollIntervalMinutes`` en analizarse,
porque Iris pregunta cada cierto tiempo. Gmail («watch» sobre Pub/Sub) y
Microsoft Graph (*change notifications*) pueden avisar en cuanto llega. Este
manager:

- **Mantiene las suscripciones** (``IrisMailboxSubscription``): las crea para
  las conexiones activas, las renueva antes de que caduquen (Gmail dura 7
  días; Graph, unos 3) y reintenta las que fallaron. Lo hace un job del
  worker (cola ``iris.ingest``), porque son llamadas al proveedor.
- **Recibe los avisos** en dos endpoints públicos autenticados por secreto
  (``services/mailbox/events.py``) y, por cada uno válido, **encola el sync
  de siempre** de esa conexión. El aviso no se usa como evidencia: lo que se
  analiza lo lee el sync con su propio token.

Tres defensas frente a lo que llega de fuera: el secreto (sin él, 401), la
agrupación de ráfagas (un aviso por conexión cada ``debounceSeconds``
despierta un sync; los demás solo se cuentan) y, en Gmail, el ``historyId``
creciente (un aviso repetido o antiguo no despierta nada).

El **sondeo sigue siempre**: con la suscripción sana se espacia a
``fallbackPollIntervalMinutes``; si falla o caduca, vuelve a su ritmo normal
sin que nadie tenga que hacer nada.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import SurfaceDisabledError, isoformat_utc, utcnow_naive
from src.modules.system.taskqueue import TaskTrackingMixin, job_context

from ..exceptions import IrisMailboxEventRejectedError
from ..model import IrisMailboxSubscription, MailboxSubscriptionStatus
from ..repositories import IrisMailboxConnectionRepository, IrisMailboxSubscriptionRepository
from ..services.mailbox.events import (
    MAX_VALIDATION_TOKEN_LENGTH,
    generate_client_state,
    hash_client_state,
    is_client_state_valid,
    is_history_newer,
    is_push_token_valid,
    parse_gmail_push,
    parse_graph_notifications,
)
from .mailbox import IrisMailboxManager

logger = logging.getLogger(__name__)

#: Una suscripción fallida (o pedida y sin respuesta) se reintenta pasado este tiempo.
_RETRY_AFTER = timedelta(hours=1)

#: Suscripciones que se crean o renuevan como mucho en cada pasada de mantenimiento.
_MAINTENANCE_BATCH_SIZE = 50

#: Tiempo máximo del job de crear o renovar una suscripción, en segundos.
_JOB_TIMEOUT_SECONDS = 120

#: Longitud máxima del error que se guarda.
_MAX_ERROR_LENGTH = 2000


def _notification_url() -> str:
    """URL pública a la que Graph manda los avisos.

    Returns:
        str: ``<PUBLIC_WEB_URL>/iris/mailbox/events/microsoft``.
    """
    return f"{CR.general_config().public_url}/iris/mailbox/events/microsoft"


def _wake(manager: IrisMailboxManager, connection_id: int) -> bool:
    """Encola el sync de una conexión por un aviso. Nunca lanza.

    Args:
        manager: Manager de buzones, que sabe encolar el sync.
        connection_id: Conexión.

    Returns:
        bool: ``True`` si se encoló; ``False`` si la superficie está cerrada
            o ya había un sync en cola (el que hay recogerá lo nuevo).
    """
    try:
        manager.submit_sync(connection_id)
        return True
    except SurfaceDisabledError:
        return False
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(f"Aviso de la conexión {connection_id}: no se encoló otro sync ({e})")
        return False


def _record_subscription(connection_id: int, provider: str, *, status: str, expires_at=None,
                         external_id: Optional[str] = None, client_state_sha256: Optional[str] = None,
                         error: Optional[str] = None) -> None:
    """Crea o actualiza la fila de suscripción de una conexión con el resultado de hablar con el proveedor.

    Args:
        connection_id: Conexión.
        provider: ``gmail`` o ``microsoft``.
        status: ``active`` o ``failed``.
        expires_at: Caducidad en el proveedor, si se creó o renovó.
        external_id: Id en Graph, si lo hay.
        client_state_sha256: Huella del secreto de Graph, si se creó uno nuevo.
        error: Motivo del fallo, si falló.
    """
    now = utcnow_naive()
    with UnitOfWork() as uow:
        repo = IrisMailboxSubscriptionRepository(uow)
        subscription = repo.get_by_connection(connection_id) or repo.save(IrisMailboxSubscription(
            connection_id=connection_id, provider=provider, created_at=now, updated_at=now,
        ))
        subscription.status = status
        subscription.updated_at = now
        subscription.last_error = error[:_MAX_ERROR_LENGTH] if error else None
        if status == MailboxSubscriptionStatus.ACTIVE.value:
            subscription.expires_at = expires_at
            subscription.last_renewed_at = now
            subscription.external_id = external_id
            if client_state_sha256 is not None:
                subscription.client_state_sha256 = client_state_sha256


def _run_ensure_subscription(connection_id: int) -> None:
    """Cuerpo del job: crea o renueva la suscripción a eventos de una conexión.

    Renovar en Graph no cambia el ``clientState``; crear uno nuevo sí. Si el
    proveedor la rechaza, la suscripción queda ``failed`` con el motivo y la
    conexión sigue por sondeo normal.

    Args:
        connection_id: Conexión.
    """
    with job_context():
        if not CR.iris_mailbox_events_config().enabled:
            return
        connection = build_repository(IrisMailboxConnectionRepository).get_by_id(connection_id)
        if connection is None or connection.status != "active":
            return
        current = build_repository(IrisMailboxSubscriptionRepository).get_by_connection(connection_id)
        try:
            _, access_token, connector = IrisMailboxManager().authorize_connection(connection_id)
            # Un secreto nuevo por si hace falta crear la suscripción (primera
            # vez, o Graph ya había borrado la anterior); si solo se alarga la
            # existente, sigue valiendo el de antes.
            client_state = generate_client_state()
            is_renewal = current is not None and current.status == MailboxSubscriptionStatus.ACTIVE.value
            if is_renewal:
                info = connector.renew(access_token, current.external_id, _notification_url(), client_state)
            else:
                info = connector.subscribe(access_token, _notification_url(), client_state)
            is_new_subscription = not is_renewal or info.external_id != current.external_id
            _record_subscription(
                connection_id, connection.provider, status=MailboxSubscriptionStatus.ACTIVE.value,
                expires_at=info.expires_at, external_id=info.external_id,
                client_state_sha256=hash_client_state(client_state) if is_new_subscription else None,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"No se pudo crear o renovar la suscripción a eventos de la conexión {connection_id}: {e}")
            _record_subscription(connection_id, connection.provider, status=MailboxSubscriptionStatus.FAILED.value,
                                 error=f"{type(e).__name__}: {e}")


class IrisMailboxEventManager(TaskTrackingMixin):
    """Suscripciones a avisos de correo nuevo y recepción de esos avisos."""

    EXTERNAL_ID_PREFIX = "iris-mailbox-subscription:"
    TASK_CATEGORY = "iris.ingest"

    # =========================================================================
    # Avisos (endpoints públicos)
    # =========================================================================

    def handle_gmail_push(self, token: Optional[str], body: Any) -> Dict[str, Any]:
        """Atiende un aviso de Gmail llegado por la suscripción de empuje de Pub/Sub.

        Args:
            token: El ``token`` de la query de la petición.
            body: Cuerpo JSON (el sobre de Pub/Sub).

        Returns:
            dict: ``accepted`` (si el aviso era válido y reciente) y ``woken``
                (cuántas conexiones se despertaron).

        Raises:
            IrisMailboxEventRejectedError: Si el secreto de empuje falta, no
                está configurado o no coincide.
        """
        if not is_push_token_valid(token, CR.get_gmail_events_environment()["push_token"]):
            raise IrisMailboxEventRejectedError("secreto de empuje de Gmail")
        push = parse_gmail_push(body)
        if push is None:
            return {"accepted": False, "woken": 0}
        config = CR.iris_mailbox_events_config()
        now = utcnow_naive()
        if push.published_at is not None and now - push.published_at > timedelta(minutes=config.max_event_age_minutes):
            return {"accepted": False, "woken": 0}

        woken = 0
        quiet_since = now - timedelta(seconds=config.debounce_seconds)
        mailbox_manager = IrisMailboxManager(task_queue=self._task_queue)
        for subscription in build_repository(IrisMailboxSubscriptionRepository).get_active_for_gmail_account(
                push.email_address):
            if not is_history_newer(push.history_id, subscription.last_history_id):
                continue
            with UnitOfWork() as uow:
                is_claimed = IrisMailboxSubscriptionRepository(uow).claim_event(
                    subscription.id, now, quiet_since, history_id=push.history_id)
            if is_claimed and _wake(mailbox_manager, subscription.connection_id):
                woken += 1
        return {"accepted": True, "woken": woken}

    def handle_graph_notifications(self, body: Any) -> Dict[str, Any]:
        """Atiende un lote de avisos de Microsoft Graph.

        Un aviso cuyo ``clientState`` no coincide con el de su suscripción se
        descarta sin decir nada: Graph espera un 202 rápido, y a quien falsifica
        no hay que darle pistas.

        Args:
            body: Cuerpo JSON (``{"value": [...]}``).

        Returns:
            dict: ``accepted`` (avisos válidos) y ``woken`` (conexiones despertadas).
        """
        config = CR.iris_mailbox_events_config()
        now = utcnow_naive()
        quiet_since = now - timedelta(seconds=config.debounce_seconds)
        mailbox_manager = IrisMailboxManager(task_queue=self._task_queue)
        accepted = woken = 0
        for notification in parse_graph_notifications(body):
            subscription = build_repository(IrisMailboxSubscriptionRepository).get_by_external_id(
                notification.subscription_id)
            if subscription is None or not is_client_state_valid(notification.client_state,
                                                                 subscription.client_state_sha256):
                continue
            accepted += 1
            with UnitOfWork() as uow:
                is_claimed = IrisMailboxSubscriptionRepository(uow).claim_event(subscription.id, now, quiet_since)
            if is_claimed and _wake(mailbox_manager, subscription.connection_id):
                woken += 1
        return {"accepted": accepted, "woken": woken}

    @staticmethod
    def build_validation_echo(validation_token: str) -> str:
        """Texto con el que se responde a la validación de Graph al crear una suscripción.

        Antes de crear una suscripción, Graph llama a la URL de avisos con un
        ``validationToken`` en la query y espera recibirlo de vuelta tal cual,
        en texto plano, para comprobar que la URL es de quien se suscribe. Se
        recorta a ``MAX_VALIDATION_TOKEN_LENGTH`` para no reflejar texto
        arbitrario de gran tamaño.

        Args:
            validation_token: El ``validationToken`` recibido.

        Returns:
            str: El token, recortado si hace falta.
        """
        return validation_token[:MAX_VALIDATION_TOKEN_LENGTH]

    # =========================================================================
    # Mantenimiento de suscripciones
    # =========================================================================

    def request_subscription(self, connection_id: int) -> bool:
        """Encola la creación de la suscripción de una conexión recién conectada. Nunca lanza.

        Se encola directamente: si se pierde, el mantenimiento periódico la
        crea en su siguiente pasada.

        Args:
            connection_id: Conexión.

        Returns:
            bool: ``True`` si se encoló; ``False`` si los eventos están
                apagados o no se pudo encolar.
        """
        if not CR.iris_mailbox_events_config().enabled:
            return False
        try:
            self._task_queue.submit(
                func=IrisMailboxEventManager.execute_ensure_subscription,
                args=(connection_id,),
                name=f"IrisMailboxSubscription-{connection_id}-{int(utcnow_naive().timestamp())}",
                category=self.TASK_CATEGORY,
                external_id=self.external_id_for(connection_id),
                timeout=_JOB_TIMEOUT_SECONDS,
            )
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"No se pudo encolar la suscripción a eventos de la conexión {connection_id}: {e}")
            return False

    def run_maintenance(self) -> int:
        """Crea las suscripciones que faltan, reintenta las fallidas y renueva las que caducan.

        Lo llama el scheduler de Iris cada ``renewCheckIntervalMinutes``. Con
        los eventos apagados no hace nada.

        Returns:
            int: Cuántos trabajos de crear o renovar se encolaron.
        """
        config = CR.iris_mailbox_events_config()
        if not config.enabled:
            return 0
        now = utcnow_naive()
        connection_ids = [connection.id for connection in build_repository(
            IrisMailboxConnectionRepository).get_active_without_healthy_subscription(now - _RETRY_AFTER,
                                                                                     _MAINTENANCE_BATCH_SIZE)]
        connection_ids += [subscription.connection_id for subscription in build_repository(
            IrisMailboxSubscriptionRepository).get_due_for_renewal(now + timedelta(hours=config.renew_before_hours),
                                                                   _MAINTENANCE_BATCH_SIZE)]
        return sum(1 for connection_id in dict.fromkeys(connection_ids) if self.request_subscription(connection_id))

    @staticmethod
    def describe_subscription(connection_id: int) -> Optional[Dict[str, Any]]:
        """Estado de la suscripción a eventos de una conexión, para su salud.

        Args:
            connection_id: Conexión.

        Returns:
            Optional[dict]: ``status``, ``expiresAt``, ``lastEventAt``,
                ``eventsReceived`` y ``lastError``; ``None`` si no tiene.
        """
        subscription = build_repository(IrisMailboxSubscriptionRepository).get_by_connection(connection_id)
        if subscription is None:
            return None
        return {
            "status": subscription.status,
            "expiresAt": isoformat_utc(subscription.expires_at),
            "lastEventAt": isoformat_utc(subscription.last_event_at),
            "eventsReceived": subscription.events_received,
            "lastError": subscription.last_error,
        }

    @staticmethod
    def execute_ensure_subscription(connection_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            connection_id: Conexión cuya suscripción se crea o renueva.
        """
        _run_ensure_subscription(connection_id)
