"""
Avisos de correo nuevo de Gmail y Microsoft Graph: leerlos y validarlos, sin BD ni red.

Un aviso llega a un endpoint público, sin sesión de usuario, así que todo lo
que trae se trata como no fiable:

- **Autenticidad.** Gmail avisa a través de una suscripción de empuje de
  Google Cloud Pub/Sub, que llama a nuestra URL con un secreto de la
  instalación en la query (``?token=``). Graph devuelve en cada aviso el
  ``clientState`` que se le dio al crear la suscripción. Los dos se comparan
  en tiempo constante.
- **Contenido.** Del aviso solo se usa a quién despertar (la cuenta de Gmail o
  el id de suscripción de Graph) y, en Gmail, el ``historyId`` para descartar
  repetidos. Nunca se analiza nada de lo que trae: el sync lee el buzón por su
  cuenta, con su propio token.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

#: Longitud máxima del ``validationToken`` de Graph que se devuelve tal cual.
#: Los de Microsoft son mucho más cortos; el tope evita reflejar texto
#: arbitrario de gran tamaño.
MAX_VALIDATION_TOKEN_LENGTH = 1024


@dataclass(frozen=True)
class GmailPush:
    """Un aviso de Gmail sacado del sobre de Pub/Sub.

    Attributes:
        email_address: Cuenta de Gmail que tiene correo nuevo, en minúsculas.
        history_id: ``historyId`` de Gmail en el momento del aviso.
        published_at: Cuándo lo publicó Pub/Sub (UTC naive), o ``None``.
    """

    email_address: str
    history_id: str
    published_at: Optional[datetime]


@dataclass(frozen=True)
class GraphNotification:
    """Un aviso de una suscripción de Graph.

    Attributes:
        subscription_id: Id de la suscripción en Graph.
        client_state: Secreto que devolvió Graph.
    """

    subscription_id: str
    client_state: str


def generate_client_state() -> str:
    """Secreto que se da a Graph al crear una suscripción.

    Returns:
        str: 32 bytes aleatorios en base64 URL.
    """
    return secrets.token_urlsafe(32)


def hash_client_state(client_state: str) -> str:
    """Huella SHA-256 del ``clientState``, que es lo que se guarda.

    Args:
        client_state: El secreto.

    Returns:
        str: 64 caracteres hexadecimales.
    """
    return hashlib.sha256(client_state.encode("utf-8")).hexdigest()


def is_client_state_valid(received: Optional[str], stored_sha256: Optional[str]) -> bool:
    """Si el ``clientState`` de un aviso es el de la suscripción, en tiempo constante.

    Args:
        received: El que trae el aviso.
        stored_sha256: ``IrisMailboxSubscription.client_state_sha256``.

    Returns:
        bool: ``True`` si coincide; ``False`` si falta cualquiera de los dos.
    """
    if not received or not stored_sha256:
        return False
    return hmac.compare_digest(hash_client_state(received), stored_sha256)


def is_push_token_valid(received: Optional[str], expected: str) -> bool:
    """Si el secreto de empuje de un aviso de Gmail es el de la instalación.

    Args:
        received: El ``token`` de la query.
        expected: ``IRIS_GMAIL_PUSH_TOKEN``.

    Returns:
        bool: ``True`` si coincide; ``False`` si no está configurado (nunca
            se acepta un aviso sin secreto) o no coincide.
    """
    if not expected or not received:
        return False
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


def parse_gmail_push(body: Any) -> Optional[GmailPush]:
    """Saca el aviso de Gmail del sobre de Pub/Sub.

    El sobre es ``{"message": {"data": <base64 de {"emailAddress", "historyId"}>,
    "publishTime": ...}, "subscription": ...}``.

    Args:
        body: Cuerpo JSON ya decodificado de la petición.

    Returns:
        Optional[GmailPush]: El aviso, o ``None`` si el cuerpo no tiene esa
            forma (se ignora, no es un error del servidor).
    """
    if not isinstance(body, dict) or not isinstance(body.get("message"), dict):
        return None
    message = body["message"]
    try:
        payload = json.loads(base64.b64decode(message.get("data") or "", validate=False).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    email_address = str(payload.get("emailAddress") or "").strip().lower()
    history_id = str(payload.get("historyId") or "").strip()
    if not email_address or not history_id.isdigit():
        return None
    return GmailPush(email_address=email_address, history_id=history_id,
                     published_at=_parse_timestamp(message.get("publishTime")))


def parse_graph_notifications(body: Any) -> List[GraphNotification]:
    """Saca los avisos de un lote de Graph (``{"value": [...]}``).

    Args:
        body: Cuerpo JSON ya decodificado de la petición.

    Returns:
        List[GraphNotification]: Los avisos con id de suscripción; los que no
            lo traen se descartan.
    """
    if not isinstance(body, dict) or not isinstance(body.get("value"), list):
        return []
    notifications = []
    for item in body["value"]:
        if isinstance(item, dict) and item.get("subscriptionId"):
            notifications.append(GraphNotification(subscription_id=str(item["subscriptionId"]),
                                                   client_state=str(item.get("clientState") or "")))
    return notifications


def is_history_newer(history_id: str, last_history_id: Optional[str]) -> bool:
    """Si un ``historyId`` de Gmail es posterior al último que despertó un sync.

    Args:
        history_id: El del aviso.
        last_history_id: El último aceptado, o ``None`` si no hubo ninguno.

    Returns:
        bool: ``True`` si es mayor (o no había ninguno); ``False`` si es un
            aviso repetido o fuera de orden.
    """
    if not last_history_id:
        return True
    return int(history_id) > int(last_history_id)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Convierte una marca RFC 3339 de Pub/Sub a UTC naive.

    Args:
        value: Texto como ``2026-09-28T10:00:00.123Z``.

    Returns:
        Optional[datetime]: La hora, o ``None`` si falta o no se entiende.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)
