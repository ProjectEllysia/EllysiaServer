"""
IrisWebhookManager — eventos firmados de Iris hacia los sistemas del usuario.

Un usuario da de alta un webhook (una URL ``https`` y los eventos que quiere) y
Iris le avisa cuando termina un análisis, cambia un caso, se abre una campaña o
un buzón pide reautorización. Cada entrega va firmada con un secreto que solo
conocen Iris y el receptor (ver ``services/webhooks.py``).

El ciclo de una entrega:

1. **Emitir** (``services/webhook_events.emit_event``): una fila
   ``IrisWebhookDelivery`` en ``pending``, en la misma transacción que el
   cambio.
2. **Enviar** (``execute_webhook_delivery``, en el worker, cola
   ``iris.webhook``): se reclama la fila, se firma y se envía por la puerta de
   salida segura.
3. **Reintentar**: un fallo deja la fila en ``pending`` con su siguiente
   intento más tarde (espera exponencial). El barrido del scheduler
   (``submit_due_deliveries``) envía las que ya tocan. Tras ``maxAttempts``
   intentos queda ``failed``.
4. **Desactivar**: tras ``disableAfterConsecutiveFailures`` fallos seguidos,
   o si el receptor responde 410 («esta URL ya no existe»), la suscripción se
   desactiva sola y sus entregas pendientes se cierran.

El usuario puede **reenviar** a mano una entrega terminada (mismo ``event_id``,
para que el receptor la descarte si ya la procesó) y mandar un evento de
**prueba** (``ping``).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import assert_owned, isoformat_utc, utcnow_naive
from src.modules.system.taskqueue import ITaskQueue, TaskTrackingMixin, job_context
from src.modules.users import UserManager

from ..exceptions import (
    IrisInvalidInputError,
    IrisWebhookDeliveryInProgressError,
    IrisWebhookDeliveryNotFoundError,
    IrisWebhookInactiveError,
    IrisWebhookLimitReachedError,
    IrisWebhookSubscriptionNotFoundError,
)
from ..model import (
    SUBSCRIBABLE_WEBHOOK_EVENTS, IrisWebhookDelivery, IrisWebhookSubscription, WebhookDeliveryStatus,
    WebhookEventType,
)
from ..repositories import IrisWebhookDeliveryRepository, IrisWebhookSubscriptionRepository
from ..services.webhooks import (
    HTTP_GONE, build_delivery_headers, build_event_id, build_event_payload, compute_retry_delay_seconds,
    generate_webhook_secret, send_webhook, serialize_payload, sign_payload, validate_webhook_url,
)

logger = logging.getLogger(__name__)

#: Tiempo máximo del job de una entrega en la cola, en segundos. Una entrega
#: es una sola petición con su propio tiempo máximo de red; esto es el margen.
_JOB_TIMEOUT_SECONDS = 120

#: Una entrega ``delivering`` reclamada hace más que esto se da por abandonada
#: (el worker murió a mitad) y vuelve a ``pending``.
_STALE_CLAIM_AFTER = timedelta(minutes=10)

#: Entregas que el barrido envía como mucho en cada pasada.
_SWEEP_BATCH_SIZE = 200

#: Longitud máxima del motivo de fallo que se guarda en la suscripción.
_MAX_ERROR_LENGTH = 120

#: Motivos con que una suscripción se desactiva sola (``disabled_reason``).
_DISABLED_BY_FAILURES = "failures"
_DISABLED_BY_GONE = "gone"

#: Motivo con que se cierran las entregas pendientes de una suscripción que ya
#: no recibe.
_SUBSCRIPTION_DISABLED_ERROR = "subscription_disabled"


def _invalid_input(text: str) -> IrisInvalidInputError:
    """Error de validación cuyo mensaje se enseña tal cual al usuario.

    Args:
        text: Qué falló, en castellano.

    Returns:
        IrisInvalidInputError: Con ``user_message`` igual a ``text``.
    """
    return IrisInvalidInputError(text, user_message=text)


def _clean_url(url: str) -> str:
    """Valida la URL de un webhook y la devuelve limpia.

    Args:
        url: URL tal como la escribió el usuario.

    Returns:
        str: La URL sin espacios alrededor.

    Raises:
        IrisInvalidInputError: Si no puede ser destino de un webhook
            (``services/webhooks.validate_webhook_url`` dice por qué).
    """
    try:
        return validate_webhook_url(url)
    except ValueError as e:
        raise _invalid_input(str(e)) from e


def _clean_event_types(event_types: Iterable[str]) -> List[str]:
    """Normaliza la lista de eventos de una suscripción.

    Args:
        event_types: Eventos pedidos; valores de ``SUBSCRIBABLE_WEBHOOK_EVENTS``.

    Returns:
        List[str]: Sin repetidos, en el orden del catálogo.

    Raises:
        IrisInvalidInputError: Si no hay ninguno o alguno no existe.
    """
    requested = set(event_types or [])
    unknown = requested - set(SUBSCRIBABLE_WEBHOOK_EVENTS)
    if unknown:
        raise _invalid_input(f"Eventos desconocidos: {', '.join(sorted(unknown))}.")
    if not requested:
        raise _invalid_input("Elige al menos un evento que enviar.")
    return [event_type for event_type in SUBSCRIBABLE_WEBHOOK_EVENTS if event_type in requested]


def _clean_name(name: str) -> str:
    """Normaliza el nombre de una suscripción.

    Args:
        name: Nombre tal como lo escribió el usuario.

    Returns:
        str: Sin espacios alrededor.

    Raises:
        IrisInvalidInputError: Si queda vacío o pasa de 80 caracteres.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        raise _invalid_input("El webhook necesita un nombre.")
    if len(cleaned) > 80:
        raise _invalid_input("El nombre del webhook no puede pasar de 80 caracteres.")
    return cleaned


def _serialize_subscription(subscription: IrisWebhookSubscription,
                            secret: Optional[str] = None) -> Dict[str, Any]:
    """Serializa una suscripción para la API.

    Args:
        subscription: Suscripción.
        secret: Secreto en claro, solo al crearla o rotarlo; por defecto
            ``None`` (el secreto no se vuelve a enseñar nunca).

    Returns:
        dict: ``subscriptionId``, ``name``, ``url``, ``eventTypes``,
            ``isActive``, ``disabledReason``, ``disabledAt``,
            ``consecutiveFailures``, ``lastSuccessAt``, ``lastFailureAt``,
            ``lastError``, ``createdAt``, ``updatedAt`` y, solo si se pasa,
            ``secret``.
    """
    payload = {
        "subscriptionId": subscription.id,
        "name": subscription.name,
        "url": subscription.url,
        "eventTypes": list(subscription.event_types or []),
        "isActive": subscription.is_active,
        "disabledReason": subscription.disabled_reason,
        "disabledAt": isoformat_utc(subscription.disabled_at),
        "consecutiveFailures": subscription.consecutive_failures,
        "lastSuccessAt": isoformat_utc(subscription.last_success_at),
        "lastFailureAt": isoformat_utc(subscription.last_failure_at),
        "lastError": subscription.last_error,
        "createdAt": isoformat_utc(subscription.created_at),
        "updatedAt": isoformat_utc(subscription.updated_at),
    }
    if secret is not None:
        payload["secret"] = secret
    return payload


def _serialize_delivery(delivery: IrisWebhookDelivery) -> Dict[str, Any]:
    """Serializa una entrega para el historial.

    Args:
        delivery: Entrega.

    Returns:
        dict: ``deliveryId``, ``eventId``, ``eventType``, ``status``,
            ``attempts``, ``nextAttemptAt`` (solo si está pendiente),
            ``lastStatusCode``, ``lastError``, ``lastResponseExcerpt``,
            ``createdAt``, ``deliveredAt`` y ``payload`` (lo que se envía).
    """
    is_pending = delivery.status == WebhookDeliveryStatus.PENDING.value
    return {
        "deliveryId": delivery.id,
        "eventId": delivery.event_id,
        "eventType": delivery.event_type,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "nextAttemptAt": isoformat_utc(delivery.next_attempt_at) if is_pending else None,
        "lastStatusCode": delivery.last_status_code,
        "lastError": delivery.last_error,
        "lastResponseExcerpt": delivery.last_response_excerpt,
        "createdAt": isoformat_utc(delivery.created_at),
        "deliveredAt": isoformat_utc(delivery.delivered_at),
        "payload": delivery.payload,
    }


def _assert_subscription(subscription_id: int, user_id: int,
                         uow: Optional[UnitOfWork] = None) -> IrisWebhookSubscription:
    """Carga una suscripción y comprueba que es del usuario.

    Args:
        subscription_id: Suscripción pedida.
        user_id: Usuario que la pide.
        uow: Transacción en curso, si la hay. Por defecto ``None`` (lectura).

    Returns:
        IrisWebhookSubscription: La suscripción.

    Raises:
        IrisWebhookSubscriptionNotFoundError: Si no existe o no es suya.
    """
    return assert_owned(IrisWebhookSubscriptionRepository, subscription_id, user_id,
                        IrisWebhookSubscriptionNotFoundError, uow=uow)


def _submit_delivery(task_queue: ITaskQueue, delivery_id: int, attempts: int, external_id: str) -> None:
    """Encola el envío de una entrega.

    Se encola directamente, sin outbox: la fila de la entrega ya existe y es
    ella la intención persistida. Si este encolado se pierde (Redis caído),
    el barrido del scheduler la vuelve a encolar en su siguiente pasada.

    Args:
        task_queue: Cola en la que publicar.
        delivery_id: Entrega.
        attempts: Intentos ya hechos; forma parte del nombre del job para que
            cada intento sea un job distinto y un reintento no choque con el
            anterior todavía guardado en RQ.
        external_id: Id lógico del job (``IrisWebhookManager.external_id_for``).
    """
    task_queue.submit(
        func=IrisWebhookManager.execute_webhook_delivery,
        name=f"IrisWebhookDelivery-{delivery_id}-{attempts}",
        category=IrisWebhookManager.TASK_CATEGORY,
        args=(delivery_id,),
        external_id=external_id,
        timeout=_JOB_TIMEOUT_SECONDS,
    )


def _record_delivered(uow: UnitOfWork, delivery: IrisWebhookDelivery, status_code: Optional[int],
                      excerpt: Optional[str]) -> None:
    """Anota una entrega que llegó y pone a cero los fallos de su suscripción.

    Args:
        uow: Transacción en curso.
        delivery: Entrega recién enviada.
        status_code: Código HTTP de la respuesta.
        excerpt: Primeros bytes de la respuesta.
    """
    now = utcnow_naive()
    delivery.status = WebhookDeliveryStatus.DELIVERED.value
    delivery.delivered_at = now
    delivery.last_status_code = status_code
    delivery.last_error = None
    delivery.last_response_excerpt = excerpt
    IrisWebhookSubscriptionRepository(uow).reset_failures(delivery.subscription_id, now)


def _record_failed(uow: UnitOfWork, delivery: IrisWebhookDelivery, status_code: Optional[int],
                   error: str, excerpt: Optional[str]) -> None:
    """Anota un intento fallido: reintento programado, entrega fallida o suscripción desactivada.

    Args:
        uow: Transacción en curso.
        delivery: Entrega recién intentada (``attempts`` ya incluye este intento).
        status_code: Código HTTP de la respuesta, o ``None`` si no respondió.
        error: Motivo estable del fallo.
        excerpt: Primeros bytes de la respuesta, o ``None``.
    """
    config = CR.iris_webhooks_config()
    now = utcnow_naive()
    subscription_repo = IrisWebhookSubscriptionRepository(uow)
    delivery.last_status_code = status_code
    delivery.last_error = error[:_MAX_ERROR_LENGTH]
    delivery.last_response_excerpt = excerpt
    failures = subscription_repo.increment_failures(delivery.subscription_id, now, error[:_MAX_ERROR_LENGTH])

    disabled_reason = None
    if status_code == HTTP_GONE:
        disabled_reason = _DISABLED_BY_GONE
    elif failures >= config.disable_after_consecutive_failures:
        disabled_reason = _DISABLED_BY_FAILURES

    if disabled_reason is not None or delivery.attempts >= config.max_attempts:
        delivery.status = WebhookDeliveryStatus.FAILED.value
    else:
        delivery.status = WebhookDeliveryStatus.PENDING.value
        delivery.next_attempt_at = now + timedelta(seconds=compute_retry_delay_seconds(
            delivery.attempts, config.retry_base_seconds, config.retry_max_seconds,
        ))
    delivery.claimed_at = None

    if disabled_reason is not None and subscription_repo.deactivate_if_active(
            delivery.subscription_id, disabled_reason, now):
        closed = IrisWebhookDeliveryRepository(uow).fail_pending_of_subscription(
            delivery.subscription_id, _SUBSCRIPTION_DISABLED_ERROR,
        )
        logger.warning(
            f"Webhook {delivery.subscription_id} desactivado ({disabled_reason}); "
            f"{closed} entrega(s) pendiente(s) cerradas"
        )


def _run_webhook_delivery(delivery_id: int) -> None:
    """Cuerpo del job: reclama una entrega, la firma, la envía y anota el resultado.

    Un segundo envío del mismo job no hace nada: solo envía quien reclama la
    fila en ``pending`` con su intento ya vencido.

    Args:
        delivery_id: Entrega.
    """
    with job_context():
        with UnitOfWork() as uow:
            repo = IrisWebhookDeliveryRepository(uow)
            if not repo.claim_for_attempt(delivery_id, utcnow_naive()):
                return
            delivery = repo.get_by_id(delivery_id)
            subscription = delivery.subscription
            if not subscription.is_active:
                delivery.status = WebhookDeliveryStatus.FAILED.value
                delivery.last_error = _SUBSCRIPTION_DISABLED_ERROR
                delivery.claimed_at = None
                return
            delivery.attempts += 1
            attempt = delivery.attempts
            url, secret = subscription.url, subscription.secret
            event_id, event_type, payload = delivery.event_id, delivery.event_type, delivery.payload

        config = CR.iris_webhooks_config()
        body = serialize_payload(payload)
        # La marca de tiempo es la del envío, no la de la emisión: un receptor
        # que rechaza firmas viejas no debe rechazar un reintento legítimo.
        signature = sign_payload(secret, int(time.time()), body)
        outcome = send_webhook(url, body, build_delivery_headers(event_id, event_type, attempt, signature),
                               timeout_seconds=config.timeout_seconds,
                               max_response_bytes=config.max_response_bytes)

        with UnitOfWork() as uow:
            delivery = IrisWebhookDeliveryRepository(uow).get_by_id(delivery_id)
            if delivery is None:
                return
            if outcome.is_delivered:
                _record_delivered(uow, delivery, outcome.status_code, outcome.response_excerpt)
            else:
                _record_failed(uow, delivery, outcome.status_code, outcome.error or "unknown",
                               outcome.response_excerpt)


class IrisWebhookManager(TaskTrackingMixin):
    """Suscripciones de webhooks de un usuario y entrega de sus eventos."""

    EXTERNAL_ID_PREFIX = "iris-webhook-delivery:"
    TASK_CATEGORY = "iris.webhook"

    # =========================================================================
    # Suscripciones
    # =========================================================================

    @staticmethod
    def list_subscriptions(user_id: int) -> Dict[str, Any]:
        """Webhooks del usuario y los eventos que se pueden suscribir.

        Args:
            user_id: Dueño.

        Returns:
            dict: ``subscriptions`` (sin secretos) y ``availableEventTypes``.
        """
        subscriptions = build_repository(IrisWebhookSubscriptionRepository).get_by_user(user_id)
        return {
            "subscriptions": [_serialize_subscription(subscription) for subscription in subscriptions],
            "availableEventTypes": list(SUBSCRIBABLE_WEBHOOK_EVENTS),
        }

    @staticmethod
    def create_subscription(user_id: int, name: str, url: str, event_types: Iterable[str]) -> Dict[str, Any]:
        """Da de alta un webhook y devuelve su secreto de firma, por única vez.

        Args:
            user_id: Dueño.
            name: Nombre para reconocerlo (hasta 80 caracteres).
            url: Destino ``https``.
            event_types: Eventos que quiere recibir.

        Returns:
            dict: La suscripción (``_serialize_subscription``) con ``secret``.

        Raises:
            SurfaceDisabledError: Si la superficie ``webhooks`` está cerrada y
                el usuario no es el administrador principal.
            IrisInvalidInputError: Si el nombre, la URL o los eventos no valen.
            IrisWebhookLimitReachedError: Si ya tiene el máximo de webhooks.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.WEBHOOKS, user_id)
        cleaned_name = _clean_name(name)
        cleaned_url = _clean_url(url)
        cleaned_events = _clean_event_types(event_types)
        limit = CR.iris_webhooks_config().max_subscriptions_per_user
        if build_repository(IrisWebhookSubscriptionRepository).count_by_user(user_id) >= limit:
            raise IrisWebhookLimitReachedError(limit)

        secret = generate_webhook_secret()
        now = utcnow_naive()
        with UnitOfWork() as uow:
            subscription = IrisWebhookSubscriptionRepository(uow).save(IrisWebhookSubscription(
                user_id=user_id, name=cleaned_name, url=cleaned_url, secret=secret,
                event_types=cleaned_events, is_active=True, consecutive_failures=0,
                created_at=now, updated_at=now,
            ))
            return _serialize_subscription(subscription, secret=secret)

    @staticmethod
    def update_subscription(subscription_id: int, user_id: int, *, name: Optional[str] = None,
                            url: Optional[str] = None, event_types: Optional[Iterable[str]] = None,
                            is_active: Optional[bool] = None) -> Dict[str, Any]:
        """Cambia un webhook: solo lo que se pasa.

        Reactivarlo (``is_active=True``) pone a cero su cuenta de fallos y
        borra el motivo por el que se desactivó solo.

        Args:
            subscription_id: Suscripción.
            user_id: Dueño.
            name: Nombre nuevo. Por defecto ``None`` (no cambia).
            url: Destino nuevo. Por defecto ``None``.
            event_types: Eventos nuevos. Por defecto ``None``.
            is_active: Activarlo o desactivarlo. Por defecto ``None``.

        Returns:
            dict: La suscripción, sin secreto.

        Raises:
            IrisWebhookSubscriptionNotFoundError: Si no existe o no es suya.
            IrisInvalidInputError: Si algún valor no vale.
            SurfaceDisabledError: Si se reactiva con la superficie cerrada.
        """
        if is_active:
            UserManager().assert_launch_surface_enabled(CR.LaunchSurface.WEBHOOKS, user_id)
        with UnitOfWork() as uow:
            subscription = _assert_subscription(subscription_id, user_id, uow)
            if name is not None:
                subscription.name = _clean_name(name)
            if url is not None:
                subscription.url = _clean_url(url)
            if event_types is not None:
                subscription.event_types = _clean_event_types(event_types)
            if is_active is True and not subscription.is_active:
                subscription.is_active = True
                subscription.consecutive_failures = 0
                subscription.disabled_reason = None
                subscription.disabled_at = None
            elif is_active is False and subscription.is_active:
                subscription.is_active = False
                subscription.disabled_reason = None
                subscription.disabled_at = None
                IrisWebhookDeliveryRepository(uow).fail_pending_of_subscription(
                    subscription.id, _SUBSCRIPTION_DISABLED_ERROR)
            subscription.updated_at = utcnow_naive()
            return _serialize_subscription(subscription)

    @staticmethod
    def rotate_secret(subscription_id: int, user_id: int) -> Dict[str, Any]:
        """Cambia el secreto de firma de un webhook y lo devuelve, por única vez.

        El secreto anterior deja de valer en el acto: las entregas siguientes,
        incluidos los reintentos de las pendientes, se firman con el nuevo.

        Args:
            subscription_id: Suscripción.
            user_id: Dueño.

        Returns:
            dict: La suscripción con ``secret``.

        Raises:
            IrisWebhookSubscriptionNotFoundError: Si no existe o no es suya.
        """
        secret = generate_webhook_secret()
        with UnitOfWork() as uow:
            subscription = _assert_subscription(subscription_id, user_id, uow)
            subscription.secret = secret
            subscription.updated_at = utcnow_naive()
            return _serialize_subscription(subscription, secret=secret)

    @staticmethod
    def delete_subscription(subscription_id: int, user_id: int) -> None:
        """Borra un webhook y su historial de entregas.

        Args:
            subscription_id: Suscripción.
            user_id: Dueño.

        Raises:
            IrisWebhookSubscriptionNotFoundError: Si no existe o no es suya.
        """
        with UnitOfWork() as uow:
            subscription = _assert_subscription(subscription_id, user_id, uow)
            IrisWebhookSubscriptionRepository(uow).delete(subscription)

    # =========================================================================
    # Historial, reenvío y prueba
    # =========================================================================

    @staticmethod
    def list_deliveries(subscription_id: int, user_id: int, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """Historial de entregas de un webhook, de la más nueva a la más antigua.

        Args:
            subscription_id: Suscripción.
            user_id: Dueño.
            page: Página, empezando en 1. Por defecto ``1``.
            per_page: Entregas por página. Por defecto ``20``.

        Returns:
            dict: ``deliveries``, ``total``, ``page`` y ``perPage``.

        Raises:
            IrisWebhookSubscriptionNotFoundError: Si no existe o no es suya.
        """
        _assert_subscription(subscription_id, user_id)
        deliveries, total = build_repository(IrisWebhookDeliveryRepository).get_page_of_subscription(
            subscription_id, page, per_page)
        return {
            "deliveries": [_serialize_delivery(delivery) for delivery in deliveries],
            "total": total,
            "page": page,
            "perPage": per_page,
        }

    def replay_delivery(self, subscription_id: int, delivery_id: int, user_id: int) -> Dict[str, Any]:
        """Vuelve a enviar una entrega terminada (llegada o fallida).

        Se envía el mismo cuerpo con el mismo ``event_id``: un receptor que ya
        la procesó puede descartarla. La entrega recupera todos sus intentos.

        Args:
            subscription_id: Suscripción a la que pertenece.
            delivery_id: Entrega.
            user_id: Dueño.

        Returns:
            dict: La entrega, ya en ``pending``.

        Raises:
            IrisWebhookSubscriptionNotFoundError: Si el webhook no existe o no es suyo.
            IrisWebhookDeliveryNotFoundError: Si la entrega no es de ese webhook.
            IrisWebhookInactiveError: Si el webhook está desactivado.
            IrisWebhookDeliveryInProgressError: Si la entrega sigue pendiente o
                enviándose.
            SurfaceDisabledError: Si la superficie está cerrada.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.WEBHOOKS, user_id)
        with UnitOfWork() as uow:
            subscription = _assert_subscription(subscription_id, user_id, uow)
            delivery = IrisWebhookDeliveryRepository(uow).get_by_id(delivery_id)
            if delivery is None or delivery.subscription_id != subscription.id:
                raise IrisWebhookDeliveryNotFoundError(delivery_id)
            if not subscription.is_active:
                raise IrisWebhookInactiveError()
            if delivery.status in (WebhookDeliveryStatus.PENDING.value, WebhookDeliveryStatus.DELIVERING.value):
                raise IrisWebhookDeliveryInProgressError()
            delivery.status = WebhookDeliveryStatus.PENDING.value
            delivery.attempts = 0
            delivery.next_attempt_at = utcnow_naive()
            delivery.delivered_at = None
            delivery.claimed_at = None
            payload = _serialize_delivery(delivery)
            uow.commit_for_handoff()
        self.dispatch_deliveries([delivery_id])
        return payload

    def send_test_event(self, subscription_id: int, user_id: int) -> Dict[str, Any]:
        """Manda un evento ``ping`` a un webhook para comprobar el receptor.

        Args:
            subscription_id: Suscripción.
            user_id: Dueño.

        Returns:
            dict: La entrega creada, en ``pending``; su resultado se ve en el
                historial en unos segundos.

        Raises:
            IrisWebhookSubscriptionNotFoundError: Si no existe o no es suya.
            IrisWebhookInactiveError: Si está desactivado.
            SurfaceDisabledError: Si la superficie está cerrada.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.WEBHOOKS, user_id)
        now = utcnow_naive()
        with UnitOfWork() as uow:
            subscription = _assert_subscription(subscription_id, user_id, uow)
            if not subscription.is_active:
                raise IrisWebhookInactiveError()
            event_id = build_event_id(f"ping:{subscription.id}:{uuid.uuid4()}")
            payload = build_event_payload(event_id, WebhookEventType.PING.value, {
                "subscriptionId": subscription.id,
                "message": "Evento de prueba de Ellysia Iris.",
            }, now)
            delivery = IrisWebhookDeliveryRepository(uow).save(IrisWebhookDelivery(
                subscription_id=subscription.id, event_id=event_id, event_type=WebhookEventType.PING.value,
                payload=payload, next_attempt_at=now, created_at=now,
            ))
            delivery_id = delivery.id
            serialized = _serialize_delivery(delivery)
            uow.commit_for_handoff()
        self.dispatch_deliveries([delivery_id])
        return serialized

    # =========================================================================
    # Envío (worker y scheduler)
    # =========================================================================

    def dispatch_deliveries(self, delivery_ids: Iterable[int]) -> None:
        """Encola ya el envío de entregas recién emitidas y confirmadas.

        Es el camino rápido; si falla (Redis caído), no pasa nada: las
        entregas siguen ``pending`` y las recoge el barrido. Nunca lanza.

        Args:
            delivery_ids: Entregas ya confirmadas en la base de datos (el
                worker es otro proceso y no vería una fila sin confirmar).
        """
        for delivery_id in delivery_ids:
            try:
                _submit_delivery(self._task_queue, delivery_id, 0, self.external_id_for(delivery_id))
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(f"No se pudo encolar la entrega de webhook {delivery_id}; la recogerá el barrido: {e}")

    def submit_due_deliveries(self) -> int:
        """Barrido: rescata entregas abandonadas y encola las que ya tocan.

        Lo llama el scheduler de Iris cada ``retrySweepIntervalSeconds``.

        Returns:
            int: Cuántas entregas se encolaron.
        """
        now = utcnow_naive()
        with UnitOfWork() as uow:
            rescued = IrisWebhookDeliveryRepository(uow).release_stale_claims(now - _STALE_CLAIM_AFTER)
        if rescued:
            logger.warning(f"{rescued} entrega(s) de webhook abandonadas a mitad vuelven a la cola")
        due = build_repository(IrisWebhookDeliveryRepository).get_due_ids(now, _SWEEP_BATCH_SIZE)
        submitted = 0
        for delivery_id, attempts in due:
            try:
                _submit_delivery(self._task_queue, delivery_id, attempts, self.external_id_for(delivery_id))
                submitted += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(f"No se pudo encolar la entrega de webhook {delivery_id}: {e}")
        return submitted

    @staticmethod
    def purge_expired_deliveries() -> int:
        """Borra el historial de entregas terminadas más viejo que ``deliveryRetentionDays``.

        Returns:
            int: Cuántas entregas se borraron.
        """
        cutoff = utcnow_naive() - timedelta(days=CR.iris_webhooks_config().delivery_retention_days)
        with UnitOfWork() as uow:
            return IrisWebhookDeliveryRepository(uow).purge_finished_older_than(cutoff)

    @staticmethod
    def execute_webhook_delivery(delivery_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            delivery_id: Entrega a enviar.
        """
        _run_webhook_delivery(delivery_id)
