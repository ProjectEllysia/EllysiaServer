"""
Emisión de eventos de Iris hacia los webhooks de su dueño.

Emitir un evento **no lo envía**: deja una fila ``IrisWebhookDelivery`` en
``pending`` por cada suscripción activa que lo quiere, dentro de la misma
transacción que el cambio que notifica. Esa fila es la intención de enviar,
igual que un ``TaskDispatch`` de la outbox: o se confirman juntos el cambio y
su aviso, o ninguno de los dos. El envío lo hace después un worker
(``IrisWebhookManager.execute_webhook_delivery``), y si nadie lo dispara en el
momento, el barrido periódico lo recoge.

Lo usan los managers (análisis, casos, buzones) y el servicio de campañas, por
eso vive aquí y no en un manager: un servicio no puede importar managers.

Los ``build_*_data`` fijan qué datos lleva cada evento. Son **metadatos**:
ids, veredictos, estados. Nunca el contenido de un correo ni una dirección de
correo de terceros; quien recibe el evento y necesita más lo pide a la API con
el id, con sus propios permisos.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.users import UserManager

from ..model import IrisAnalysis, IrisCase, IrisCaseEvent, IrisWebhookDelivery
from ..repositories import IrisWebhookDeliveryRepository, IrisWebhookSubscriptionRepository
from .webhooks import build_event_id, build_event_payload

logger = logging.getLogger(__name__)


def is_webhooks_surface_open_for(user_id: int) -> bool:
    """Si la superficie ``webhooks`` está abierta para un usuario.

    Cerrada en vista previa salvo para el administrador principal, igual que
    el resto de superficies (``UserManager.assert_launch_surface_enabled``).

    Args:
        user_id: Usuario dueño de lo que se notificaría.

    Returns:
        bool: ``True`` si se le pueden enviar eventos.
    """
    if CR.launch_config().is_surface_enabled(CR.LaunchSurface.WEBHOOKS):
        return True
    user = UserManager().get_user_by_id(user_id)
    return user is not None and user.role == "role_root"


def emit_event(uow: UnitOfWork, user_id: int, event_type: str, dedupe_key: str,
               data: Dict[str, Any], occurred_at: Optional[datetime] = None) -> List[int]:
    """Deja pendiente la entrega de un evento a cada webhook del usuario que lo quiere.

    Nunca lanza: un evento que no se puede emitir se registra en el log y no
    tumba el cambio que lo originó (el análisis ya tiene su veredicto, el caso
    ya cambió). La duplicación se evita comprobando antes de insertar, no
    dejando que salte la restricción única: un fallo de la base de datos dentro
    de la transacción del llamante la dejaría inservible para su propio commit.
    La restricción queda como red de seguridad para una carrera entre dos
    emisiones simultáneas del mismo hecho, que los llamantes ya evitan (solo
    emite quien gana la transición de estado que lo provoca).

    Args:
        uow: Transacción del cambio que se notifica; las entregas se
            confirman con él.
        user_id: Dueño de lo que cambió; solo sus suscripciones lo reciben.
        event_type: Valor de ``WebhookEventType``.
        dedupe_key: Descripción única del hecho (``"analysis.finished:42"``).
            Emitir dos veces la misma clave no crea una segunda entrega.
        data: Datos del evento (``build_*_data``).
        occurred_at: Cuándo pasó. Por defecto, ahora.

    Returns:
        List[int]: Ids de las entregas creadas, para enviarlas ya tras el
            commit (``IrisWebhookManager.dispatch_deliveries``); vacía si nadie
            lo quiere, si la superficie está cerrada o si ya se había emitido.
    """
    try:
        subscriptions = IrisWebhookSubscriptionRepository(uow).get_active_for_event(user_id, event_type)
        if not subscriptions or not is_webhooks_surface_open_for(user_id):
            return []
        now = occurred_at or utcnow_naive()
        event_id = build_event_id(dedupe_key)
        payload = build_event_payload(event_id, event_type, data, now)
        delivery_repo = IrisWebhookDeliveryRepository(uow)
        delivery_ids = []
        for subscription in subscriptions:
            if delivery_repo.exists_for_event(subscription.id, event_id):
                continue
            delivery = delivery_repo.save(IrisWebhookDelivery(
                subscription_id=subscription.id, event_id=event_id, event_type=event_type,
                payload=payload, next_attempt_at=now, created_at=now,
            ))
            delivery_ids.append(delivery.id)
        return delivery_ids
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"No se pudo emitir el evento {event_type} ({dedupe_key}): {e}", exc_info=True)
        return []


def build_analysis_finished_data(analysis: IrisAnalysis, verdict: str, total_score: float,
                                 analysis_quality: str, confidence: Optional[str],
                                 finished_at: datetime) -> Dict[str, Any]:
    """Datos de ``analysis.finished``.

    El resultado llega por parámetro y no se lee de ``analysis``: se emite en
    la misma transacción que lo escribe con un ``UPDATE``, y la instancia que
    haya en la sesión puede no reflejarlo todavía.

    Args:
        analysis: Análisis; de él se toman los datos que no cambian al
            terminar (id, título, conexión).
        verdict: Veredicto (``Legitimate``, ``Suspicious`` o ``Phishing``).
        total_score: Puntuación final.
        analysis_quality: ``complete`` o ``degraded``.
        confidence: Confianza ordinal del veredicto, o ``None`` sin evaluar.
        finished_at: Cuándo terminó.

    Returns:
        dict: ``analysisId``, ``title`` (el asunto del correo o el título que
            le dio el usuario), ``verdict``, ``totalScore``,
            ``analysisQuality``, ``confidence``, ``source`` (``mailbox`` si
            llegó por un buzón conectado, ``manual`` si no), ``connectionId``
            y ``finishedAt``.
    """
    return {
        "analysisId": analysis.id,
        "title": analysis.title,
        "verdict": verdict,
        "totalScore": total_score,
        "analysisQuality": analysis_quality,
        "confidence": confidence,
        "source": "mailbox" if analysis.connection_id is not None else "manual",
        "connectionId": analysis.connection_id,
        "finishedAt": isoformat_utc(finished_at),
    }


def build_case_updated_data(case: IrisCase, event: IrisCaseEvent) -> Dict[str, Any]:
    """Datos de ``case.updated``: cómo está el caso y qué acaba de cambiar.

    El texto de una nota no viaja (``hasNote``): puede ser largo y lo
    escribió una persona para su equipo, no para otro sistema.

    Args:
        case: Caso ya cambiado.
        event: Entrada de la timeline que describe el cambio.

    Returns:
        dict: ``caseId``, ``title``, ``status``, ``priority``, ``assigneeId``,
            ``tags``, ``analysisIds`` y ``change`` (``kind``, ``detail``,
            ``hasNote``, ``actorId``).
    """
    return {
        "caseId": case.id,
        "title": case.title,
        "status": case.status,
        "priority": case.priority,
        "assigneeId": case.assignee_id,
        "tags": list(case.tags or []),
        "analysisIds": [link.analysis_id for link in case.links],
        "change": {
            "kind": event.kind,
            "detail": event.detail,
            "hasNote": bool(event.note),
            "actorId": event.actor_id,
        },
    }


def build_campaign_detected_data(campaign_id: int, label: Optional[str], analysis_ids: List[int],
                                 matched_signals: List[str]) -> Dict[str, Any]:
    """Datos de ``campaign.detected``, en el momento en que se abre la campaña.

    Args:
        campaign_id: Campaña recién abierta.
        label: Su rótulo (asunto del mensaje que la abrió), o ``None``.
        analysis_ids: Los dos análisis con que nace.
        matched_signals: Tipos de señal que coincidieron (``url``, ``hash``…).

    Returns:
        dict: ``campaignId``, ``label``, ``analysisIds`` y ``matchedSignals``.
    """
    return {
        "campaignId": campaign_id,
        "label": label,
        "analysisIds": list(analysis_ids),
        "matchedSignals": list(matched_signals),
    }


def build_mailbox_reauth_data(connection_id: int, provider: str, account_email: str) -> Dict[str, Any]:
    """Datos de ``mailbox.reauth_required``.

    La dirección del buzón sí viaja: es del propio usuario y es lo que dice
    qué cuenta hay que volver a conectar.

    Args:
        connection_id: Conexión que dejó de sincronizarse.
        provider: ``gmail`` o ``microsoft``.
        account_email: Dirección del buzón conectado.

    Returns:
        dict: ``connectionId``, ``provider`` y ``accountEmail``.
    """
    return {"connectionId": connection_id, "provider": provider, "accountEmail": account_email}
