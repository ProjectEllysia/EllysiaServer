"""
Eventos firmados de Iris hacia sistemas externos: la parte que no toca la BD.

Un **webhook** es una petición HTTP que Ellysia hace a una URL del usuario
cuando pasa algo (termina un análisis, cambia un caso…), para que otro sistema
—un SIEM, un SOAR, un canal de chat— reaccione sin tener que preguntar cada
poco. Este fichero decide *qué* se envía y *cómo* se firma; guardar las
entregas y reintentarlas es cosa de ``managers/webhooks.py``.

**La firma.** Cualquiera que conozca la URL del receptor podría mandarle
eventos falsos. Por eso cada entrega lleva la cabecera
``X-Ellysia-Signature: t=<segundos>,v1=<hex>``, donde ``v1`` es el
HMAC-SHA256, con el secreto de la suscripción, de ``"<t>.<cuerpo>"``. El
receptor recalcula el HMAC con su copia del secreto y lo compara; y como la
marca de tiempo va dentro de lo firmado, puede rechazar además una entrega
vieja que alguien haya capturado y reenvíe (un *replay*), comparando ``t`` con
su reloj. Es el mismo esquema que usan Stripe o GitHub, así que los receptores
existentes saben verificarlo.

**El identificador del evento.** ``build_event_id`` deriva un UUID del hecho
que se notifica (``analysis.finished:42``): el mismo hecho da siempre el mismo
id. Eso es lo que permite que ni una emisión repetida ni un reintento lleguen
como dos eventos distintos.

Nada de aquí abre conexiones salvo ``send_webhook``, que pasa por la puerta de
salida segura de Iris (``services/enrichment/egress.py``): una URL de webhook
la escribe el usuario, y sin esa puerta bastaría con apuntarla a una dirección
interna para que el servidor hiciera peticiones dentro de su propia red.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from src.modules.shared import isoformat_utc, is_private_target

from .enrichment import egress
from .enrichment.egress import ALLOWED_PORTS, EgressBlockedError, describe_network_error

#: Versión del formato del cuerpo. Sube solo si cambia de forma incompatible
#: (un campo que se quita o cambia de significado); añadir campos no la sube.
EVENT_SCHEMA_VERSION = 1

#: Prefijo del secreto, para que quien lo encuentre pegado en un fichero sepa
#: qué es y de dónde salió.
_SECRET_PREFIX = "whsec_"

#: Espacio de nombres de los UUID de evento. Fijo: cambiarlo cambiaría el id de
#: todos los eventos y un receptor que deduplica volvería a procesarlos.
_EVENT_NAMESPACE = uuid.UUID("6f1e2d3c-9b8a-4c5d-8e7f-a1b2c3d4e5f6")

#: Cómo se presenta Ellysia al entregar un evento.
_USER_AGENT = "Ellysia-Iris-Webhooks/1.0"

#: Código con que un receptor dice «esta URL ya no existe, no insistas».
HTTP_GONE = 410


@dataclass(frozen=True)
class DeliveryOutcome:
    """Qué pasó al intentar entregar un evento.

    Attributes:
        is_delivered: Si el receptor respondió con un 2xx.
        status_code: Código HTTP de la respuesta; ``None`` si no llegó a
            responder (red, TLS, dirección bloqueada).
        error: Motivo estable del fallo (``http_500``, ``timeout``,
            ``private_address``…); ``None`` si llegó.
        response_excerpt: Primeros bytes de la respuesta en texto, para
            diagnosticar; ``None`` si no hubo respuesta.
    """

    is_delivered: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    response_excerpt: Optional[str] = None


def generate_webhook_secret() -> str:
    """Genera el secreto de firma de una suscripción.

    Returns:
        str: ``whsec_`` seguido de 32 bytes aleatorios en base64 URL
            (43 caracteres). Solo se enseña una vez; después vive cifrado.
    """
    return _SECRET_PREFIX + secrets.token_urlsafe(32)


def build_event_id(dedupe_key: str) -> str:
    """Identificador estable de un evento a partir del hecho que notifica.

    Args:
        dedupe_key: Descripción única del hecho, con la forma
            ``"<tipo>:<id>"`` (``"analysis.finished:42"``,
            ``"case.updated:event:7"``). Dos emisiones del mismo hecho deben
            pasar la misma clave.

    Returns:
        str: UUID versión 5 en texto (36 caracteres).
    """
    return str(uuid.uuid5(_EVENT_NAMESPACE, dedupe_key))


def build_event_payload(event_id: str, event_type: str, data: Dict[str, Any],
                        created_at: datetime) -> Dict[str, Any]:
    """Cuerpo completo de un evento, tal como lo recibe el receptor.

    Args:
        event_id: Id estable del evento (``build_event_id``).
        event_type: Valor de ``WebhookEventType``.
        data: Datos propios del evento, con claves en camelCase y valores
            JSON-serializables. Nunca el contenido de un correo.
        created_at: Cuándo pasó, en UTC naive.

    Returns:
        dict: ``id``, ``type``, ``createdAt`` (ISO 8601 con ``Z``),
            ``schemaVersion`` y ``data``.
    """
    return {
        "id": event_id,
        "type": event_type,
        "createdAt": isoformat_utc(created_at),
        "schemaVersion": EVENT_SCHEMA_VERSION,
        "data": data,
    }


def serialize_payload(payload: Dict[str, Any]) -> bytes:
    """Bytes exactos que se envían y se firman.

    Claves ordenadas y sin espacios: el mismo evento produce siempre los
    mismos bytes, así que la firma de un reintento coincide con la del primero
    (cambia solo por la marca de tiempo).

    Args:
        payload: Cuerpo del evento (``build_event_payload``).

    Returns:
        bytes: JSON en UTF-8.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    """Valor de la cabecera ``X-Ellysia-Signature`` de una entrega.

    Args:
        secret: Secreto de la suscripción (``whsec_…``).
        timestamp: Segundos desde la época Unix en el momento del envío.
        body: Bytes del cuerpo (``serialize_payload``).

    Returns:
        str: ``"t=<timestamp>,v1=<hex del HMAC-SHA256 de '<timestamp>.<body>'>"``.
    """
    signed = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def build_delivery_headers(event_id: str, event_type: str, attempt: int, signature: str) -> Dict[str, str]:
    """Cabeceras de una entrega.

    Args:
        event_id: Id del evento; el mismo en todos sus reintentos.
        event_type: Valor de ``WebhookEventType``.
        attempt: Número de este intento, empezando en ``1``.
        signature: Valor de ``sign_payload``.

    Returns:
        dict: ``Content-Type``, ``User-Agent``, ``X-Ellysia-Event``,
            ``X-Ellysia-Event-Id``, ``X-Ellysia-Delivery-Attempt`` y
            ``X-Ellysia-Signature``.
    """
    return {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": _USER_AGENT,
        "X-Ellysia-Event": event_type,
        "X-Ellysia-Event-Id": event_id,
        "X-Ellysia-Delivery-Attempt": str(attempt),
        "X-Ellysia-Signature": signature,
    }


def compute_retry_delay_seconds(attempts: int, base_seconds: int, max_seconds: int) -> int:
    """Espera antes del siguiente intento de una entrega que acaba de fallar.

    Crece exponencialmente (``base``, ``2·base``, ``4·base``…) para no
    martillear a un receptor caído, con un techo para que un receptor que
    vuelve no tarde horas en recibir lo que se le debe.

    Args:
        attempts: Intentos hechos, contando el que acaba de fallar (``≥ 1``).
        base_seconds: Espera tras el primer fallo.
        max_seconds: Espera máxima.

    Returns:
        int: Segundos, entre ``base_seconds`` y ``max_seconds``.
    """
    exponent = max(attempts - 1, 0)
    # El exponente se acota antes de elevar: con muchos intentos, 2**n crecería
    # sin necesidad cuando el techo ya manda.
    return min(base_seconds * (2 ** min(exponent, 30)), max_seconds)


def validate_webhook_url(url: str) -> str:
    """Comprueba que una URL puede ser el destino de un webhook.

    Solo mira la forma, sin resolver el nombre: la comprobación de que no
    apunta a una red interna la repite la puerta de salida en **cada**
    entrega, que es la que cuenta, porque un nombre puede cambiar de dirección
    después de darlo de alta.

    Args:
        url: URL tal como la escribió el usuario.

    Returns:
        str: La URL sin espacios alrededor.

    Raises:
        ValueError: Con el motivo en castellano, para enseñárselo al usuario,
            si no es ``https``, no tiene servidor, lleva usuario y contraseña,
            usa un puerto que no es web o apunta a una dirección interna
            evidente (``localhost``, ``10.0.0.5``, ``nas.local``…).
    """
    cleaned = (url or "").strip()
    parts = urlsplit(cleaned)
    if parts.scheme.lower() != "https":
        raise ValueError("La dirección del webhook tiene que empezar por https://.")
    if not parts.hostname:
        raise ValueError("La dirección del webhook no tiene servidor.")
    if parts.username or parts.password:
        raise ValueError("La dirección del webhook no puede llevar usuario ni contraseña.")
    try:
        port = parts.port or 443
    except ValueError as e:
        raise ValueError("El puerto de la dirección del webhook no es válido.") from e
    if port not in ALLOWED_PORTS:
        allowed = ", ".join(str(allowed_port) for allowed_port in sorted(ALLOWED_PORTS))
        raise ValueError(f"El webhook solo puede usar los puertos {allowed}.")
    if _is_internal_host(parts.hostname):
        raise ValueError("El webhook no puede apuntar a una dirección de una red interna.")
    return cleaned


def send_webhook(url: str, body: bytes, headers: Dict[str, str], *, timeout_seconds: float,
                 max_response_bytes: int) -> DeliveryOutcome:
    """Envía una entrega por la puerta de salida segura. Nunca lanza.

    No sigue redirects: un receptor que responde 3xx cuenta como fallo. Seguir
    una redirección mandaría el evento firmado a un sitio que el usuario no
    eligió.

    Args:
        url: Destino (``https``).
        body: Cuerpo ya serializado.
        headers: Cabeceras de ``build_delivery_headers``.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_response_bytes: Bytes de la respuesta que se leen.

    Returns:
        DeliveryOutcome: Llegó con un 2xx, o el motivo del fallo.
    """
    try:
        # Por el módulo y no importada suelta: así la sustituyen los tests en
        # la misma costura que el resto del enriquecimiento.
        response = egress.fetch(url, method="POST", body=body, extra_headers=headers, accept="*/*",
                                timeout_seconds=timeout_seconds, max_bytes=max_response_bytes)
    except EgressBlockedError as e:
        return DeliveryOutcome(is_delivered=False, error=e.reason)
    except (OSError, http.client.HTTPException) as e:
        return DeliveryOutcome(is_delivered=False, error=describe_network_error(e))
    excerpt = response.body.decode("utf-8", errors="replace") or None
    if 200 <= response.status < 300:
        return DeliveryOutcome(is_delivered=True, status_code=response.status, response_excerpt=excerpt)
    return DeliveryOutcome(is_delivered=False, status_code=response.status,
                           error=f"http_{response.status}", response_excerpt=excerpt)


def _is_internal_host(host: str) -> bool:
    """Si un servidor es evidentemente interno, sin resolverlo.

    Args:
        host: Nombre o IP literal de la URL.

    Returns:
        bool: ``True`` para una IP que no es de internet, para ``localhost`` y
            para los sufijos de red local; también para un nombre sin punto,
            que solo se resuelve dentro de una red.
    """
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return is_private_target(host) or "." not in host
    return not ip.is_global
