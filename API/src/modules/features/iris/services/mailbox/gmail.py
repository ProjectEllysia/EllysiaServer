"""
GmailConnector — Gmail API v1 sobre OAuth 2.0 de Google.

``requests`` (ya dependencia del proyecto, sin uso previo en ``src/`` —
verificado) en vez de ``google-auth``/``google-api-python-client``: la
superficie que necesitamos (token endpoint + 4 llamadas REST) no justifica
esas dependencias, mismo criterio que ``tools/scribe``/``tools/herald`` usan
SDKs nativos solo cuando el proveedor no tiene una API REST simple.

Scope según ``full_message_mode``: ``gmail.metadata`` (más restrictivo,
"como mínimo las cabeceras") o ``gmail.readonly`` (cuerpo completo) — a
diferencia de Microsoft Graph, Gmail sí tiene un scope granular para esto,
fijado en el consentimiento inicial y no ampliable después sin re-consentir.

Con una **cuenta de servicio** (``mailbox_address``) no hay consentimiento de
nadie: la instalación firma una aserción JWT con la clave de su cuenta de
servicio de Google Workspace, pidiendo actuar como ese buzón (delegación de
dominio) y solo con ``gmail.readonly``. El administrador de Workspace decide a
qué buzones alcanza esa delegación.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import jwt
import requests

import src.modules.system.config_reading as CR

from .base import (
    ActionResult, MailboxConnector, MailboxFolder, MessageRef, ServiceToken, SubscriptionInfo, TokenSet,
)
from .registry import register_connector

logger = logging.getLogger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_SCOPE_METADATA = "https://www.googleapis.com/auth/gmail.metadata"
_SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
# Leer y cambiar etiquetas, mover a spam y a la papelera. No incluye el
# borrado definitivo (eso sería https://mail.google.com/), a propósito.
_SCOPE_MODIFY = "https://www.googleapis.com/auth/gmail.modify"

# Etiquetas de sistema de Gmail que tocan las acciones.
_LABEL_INBOX = "INBOX"
_LABEL_SPAM = "SPAM"

# Cabeceras que alimentan las 40 reglas de Iris (ver services/shared.py y
# services/rules/*) — restringir a estas en vez de pedir todas mantiene el
# payload de format=metadata pequeño sin perder ninguna señal que el motor
# use hoy.
_METADATA_HEADERS = [
    "From", "To", "Cc", "Reply-To", "Return-Path", "Sender", "Envelope-From",
    "Subject", "Date", "Message-ID", "In-Reply-To", "References",
    "Received", "Authentication-Results", "Received-SPF",
    "ARC-Seal", "ARC-Message-Signature", "ARC-Authentication-Results",
    "DKIM-Signature", "List-Unsubscribe", "List-Unsubscribe-Post",
    "Content-Type", "Thread-Index", "Thread-Topic",
]

_TIMEOUT_SECONDS = 20

#: Validez que se pide para la aserción de la cuenta de servicio (Google admite una hora como mucho).
_SERVICE_ASSERTION_SECONDS = 3600


@register_connector("gmail")
class GmailConnector(MailboxConnector):
    provider = "gmail"
    supports_service_account = True

    def __init__(self, redirect_uri: str, folder: Optional[str] = None,
                 mailbox_address: Optional[str] = None) -> None:
        # Con cuenta de servicio no se usa la app OAuth, y una instalación
        # puede no tenerla configurada.
        env = CR.get_gmail_environment() if mailbox_address is None else {"client_id": "", "client_secret": ""}
        self._client_id = env["client_id"]
        self._client_secret = env["client_secret"]
        self._redirect_uri = redirect_uri
        # Gmail label id to restrict history.list to (e.g. "INBOX"); None =
        # every new message account-wide, Gmail's own default.
        self._label_id = folder

    def authorize_url(self, state: str, full_message_mode: bool, remediation_enabled: bool = False) -> str:
        # gmail.modify ya permite leer el mensaje entero, así que con acciones
        # no hace falta pedir además readonly.
        if remediation_enabled:
            scope = _SCOPE_MODIFY
        else:
            scope = _SCOPE_READONLY if full_message_mode else _SCOPE_METADATA
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": f"{scope} openid email",
            "state": state,
            "access_type": "offline",
            # "consent" fuerza a Google a devolver un refresh_token incluso
            # si el usuario ya había concedido este scope antes — sin esto,
            # una reconexión silenciosa no devuelve refresh_token.
            "prompt": "consent",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenSet:
        response = requests.post(_TOKEN_URL, data={
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        account_email = self._get_account_email(payload["access_token"])
        return self._token_set_from(payload, account_email)

    def refresh(self, refresh_token: str) -> TokenSet:
        response = requests.post(_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "refresh_token",
        }, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        # Google no siempre re-emite el refresh_token en un refresh -- el
        # llamante (IrisMailboxManager) mantiene el original si este viene vacío.
        payload.setdefault("refresh_token", refresh_token)
        account_email = self._get_account_email(payload["access_token"])
        return self._token_set_from(payload, account_email)

    def list_new(self, access_token: str, cursor: Optional[str]) -> tuple[list[MessageRef], str]:
        headers = {"Authorization": f"Bearer {access_token}"}

        if cursor is None:
            # Bootstrap: solo capturar el historyId actual, sin backfill.
            response = requests.get(f"{_API_BASE}/profile", headers=headers, timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
            return [], str(response.json()["historyId"])

        refs: list[MessageRef] = []
        new_cursor = cursor
        page_token: Optional[str] = None
        while True:
            params = {"startHistoryId": cursor, "historyTypes": "messageAdded"}
            if self._label_id:
                params["labelId"] = self._label_id
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(f"{_API_BASE}/history", headers=headers,
                                     params=params, timeout=_TIMEOUT_SECONDS)
            if response.status_code == 404:
                # historyId demasiado antiguo (fuera de la ventana de retención de
                # Gmail, ~7 días de inactividad) -- solo opción es re-bootstrapear.
                logger.warning("Gmail history cursor expirado, re-bootstrapping")
                return self.list_new(access_token, cursor=None)
            response.raise_for_status()
            data = response.json()

            for record in data.get("history", []):
                for added in record.get("messagesAdded", []):
                    message_id = added["message"]["id"]
                    refs.append(MessageRef(provider_message_id=message_id))

            new_cursor = str(data.get("historyId", new_cursor))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return refs, new_cursor

    def fetch_headers(self, access_token: str, message_ref: MessageRef) -> str:
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"format": "metadata", "metadataHeaders": _METADATA_HEADERS}
        response = requests.get(
            f"{_API_BASE}/messages/{message_ref.provider_message_id}",
            headers=headers, params=params, timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload_headers = response.json().get("payload", {}).get("headers", [])
        return "".join(f"{payload_header['name']}: {payload_header['value']}\r\n" for payload_header in payload_headers)

    def fetch_raw(self, access_token: str, message_ref: MessageRef) -> str:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            f"{_API_BASE}/messages/{message_ref.provider_message_id}",
            headers=headers, params={"format": "raw"}, timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_b64url = response.json()["raw"]
        padded = raw_b64url + "=" * (-len(raw_b64url) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

    def list_folders(self, access_token: str) -> list[MailboxFolder]:
        response = requests.get(
            f"{_API_BASE}/labels",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return [
            MailboxFolder(
                provider_id=label["id"], display_name=label["name"],
                # Gmail ya distingue system (INBOX, SENT, TRASH...) de user
                # (etiquetas creadas por la cuenta) -- se traslada tal cual.
                folder_type="system" if label.get("type") == "system" else "user",
            )
            for label in response.json().get("labels", [])
        ]

    def subscribe(self, access_token: str, notification_url: str, client_state: str) -> SubscriptionInfo:
        # Gmail no llama a una URL: publica en un tema de Pub/Sub, y es la
        # suscripción de empuje de ese tema (configurada en Google Cloud) la
        # que llama a /iris/mailbox/events/gmail. Por eso aquí solo se pide el
        # «watch» de la carpeta vigilada sobre ese tema.
        topic = CR.get_gmail_events_environment()["topic"]
        if not topic:
            raise ValueError("Falta GMAIL_PUBSUB_TOPIC: sin tema de Pub/Sub, Gmail sigue solo por sondeo.")
        response = requests.post(
            f"{_API_BASE}/watch", headers={"Authorization": f"Bearer {access_token}"},
            json={"topicName": topic, "labelIds": [self._label_id or _LABEL_INBOX], "labelFilterBehavior": "include"},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        expiration_ms = int(response.json()["expiration"])
        return SubscriptionInfo(expires_at=datetime.fromtimestamp(expiration_ms / 1000, tz=timezone.utc).replace(tzinfo=None))

    def renew(self, access_token: str, external_id: Optional[str], notification_url: str,
              client_state: str) -> SubscriptionInfo:
        # Renovar un «watch» de Gmail es volver a pedirlo: sustituye al anterior.
        return self.subscribe(access_token, notification_url, client_state)

    def unsubscribe(self, access_token: str, external_id: Optional[str]) -> None:
        response = requests.post(f"{_API_BASE}/stop", headers={"Authorization": f"Bearer {access_token}"},
                                 timeout=_TIMEOUT_SECONDS)
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()

    def acquire_service_token(self, mailbox_address: str) -> ServiceToken:
        key = _load_service_account()
        now = datetime.now(timezone.utc)
        assertion = jwt.encode({
            "iss": key["client_email"], "sub": mailbox_address, "scope": _SCOPE_READONLY,
            "aud": key.get("token_uri") or _TOKEN_URL,
            "iat": int(now.timestamp()), "exp": int(now.timestamp()) + _SERVICE_ASSERTION_SECONDS,
        }, key["private_key"], algorithm="RS256")
        response = requests.post(key.get("token_uri") or _TOKEN_URL, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion,
        }, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        return ServiceToken(
            access_token=data["access_token"],
            expires_at=(now + timedelta(seconds=int(data.get("expires_in", 3600)))).replace(tzinfo=None),
            scopes=_SCOPE_READONLY,
        )

    @staticmethod
    def can_act(scopes: str) -> bool:
        return _SCOPE_MODIFY in (scopes or "").split()

    def quarantine(self, access_token: str, message_id: str, folder_name: str) -> ActionResult:
        label_id = _ensure_label(self, access_token, folder_name)
        return _change_labels(access_token, message_id, add=[label_id], remove=[_LABEL_INBOX])

    def label(self, access_token: str, message_id: str, label_name: str) -> ActionResult:
        label_id = _ensure_label(self, access_token, label_name)
        return _change_labels(access_token, message_id, add=[label_id], remove=[])

    def report_phishing(self, access_token: str, message_id: str) -> ActionResult:
        return _change_labels(access_token, message_id, add=[_LABEL_SPAM], remove=[_LABEL_INBOX])

    def delete(self, access_token: str, message_id: str) -> ActionResult:
        response = requests.post(
            f"{_API_BASE}/messages/{message_id}/trash",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return ActionResult(provider_message_id=message_id, previous_state={"trashed": True})

    def undo(self, access_token: str, action: str, message_id: str, previous_state: dict,
             label_name: str) -> str:
        if previous_state.get("trashed"):
            response = requests.post(
                f"{_API_BASE}/messages/{message_id}/untrash",
                headers={"Authorization": f"Bearer {access_token}"}, timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return message_id
        # Se revierte exactamente lo que cambió la acción, no el estado entero
        # de antes: si el usuario ha leído o archivado el correo después, eso
        # se respeta.
        _modify(access_token, message_id, add=previous_state.get("removedLabelIds", []),
                     remove=previous_state.get("addedLabelIds", []))
        return message_id

    def revoke(self, refresh_token: str) -> None:
        response = requests.post(_REVOKE_URL, data={"token": refresh_token}, timeout=_TIMEOUT_SECONDS)
        # Un token ya revocado/expirado devuelve 400 -- no es un fallo real
        # del lado del usuario que está desconectando su cuenta.
        if response.status_code not in (200, 400):
            response.raise_for_status()

    @staticmethod
    def _get_account_email(access_token: str) -> str:
        response = requests.get(
            f"{_API_BASE}/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["emailAddress"]

    @staticmethod
    def _token_set_from(payload: dict, account_email: str) -> TokenSet:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        return TokenSet(
            refresh_token=payload["refresh_token"],
            access_token=payload["access_token"],
            access_token_expires_at=expires_at,
            scopes=payload.get("scope", ""),
            account_email=account_email,
        )


def _change_labels(access_token: str, message_id: str, add: list, remove: list) -> ActionResult:
    """Añade y quita etiquetas a un mensaje y anota exactamente qué cambió.

    Solo se añade lo que no tenía y solo se quita lo que tenía, para que el
    deshacer revierta la acción y nada más.

    Args:
        access_token: Token de acceso vigente.
        message_id: Id del mensaje en Gmail.
        add: Etiquetas a poner.
        remove: Etiquetas a quitar.

    Returns:
        ActionResult: El mismo id (Gmail no lo cambia) y, en
            ``previous_state``, ``labelIds`` (las de antes), ``addedLabelIds``
            y ``removedLabelIds``.
    """
    current = set(_message_labels(access_token, message_id))
    added = [label for label in add if label not in current]
    removed = [label for label in remove if label in current]
    _modify(access_token, message_id, add=added, remove=removed)
    return ActionResult(provider_message_id=message_id, previous_state={
        "labelIds": sorted(current), "addedLabelIds": added, "removedLabelIds": removed,
    })


def _message_labels(access_token: str, message_id: str) -> list:
    """Etiquetas actuales de un mensaje.

    Args:
        access_token: Token de acceso vigente.
        message_id: Id del mensaje en Gmail.

    Returns:
        list: Ids de etiqueta (``INBOX``, ``UNREAD``, ``Label_12``…).
    """
    response = requests.get(
        f"{_API_BASE}/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"}, params={"format": "minimal"},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("labelIds", [])


def _modify(access_token: str, message_id: str, add: list, remove: list) -> None:
    """Pone y quita etiquetas de un mensaje en una sola llamada; nada si no hay cambios.

    Args:
        access_token: Token de acceso vigente.
        message_id: Id del mensaje en Gmail.
        add: Etiquetas a poner.
        remove: Etiquetas a quitar.
    """
    if not add and not remove:
        return
    response = requests.post(
        f"{_API_BASE}/messages/{message_id}/modify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"addLabelIds": add, "removeLabelIds": remove}, timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _ensure_label(connector: "GmailConnector", access_token: str, name: str) -> str:
    """Id de una etiqueta de usuario por su nombre, creándola si no existe.

    Args:
        connector: Conector, para listar las etiquetas de la cuenta.
        access_token: Token de acceso vigente.
        name: Nombre visible de la etiqueta.

    Returns:
        str: Id de la etiqueta.
    """
    match = next((folder for folder in connector.list_folders(access_token) if folder.display_name == name), None)
    if match is not None:
        return match.provider_id
    response = requests.post(
        f"{_API_BASE}/labels", headers={"Authorization": f"Bearer {access_token}"},
        json={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["id"]


def _load_service_account() -> dict:
    """Lee el JSON de la cuenta de servicio de Google (``GMAIL_SERVICE_ACCOUNT_FILE``).

    Returns:
        dict: Al menos ``client_email`` y ``private_key``.

    Raises:
        ValueError: Si la variable no está definida o el fichero no es una
            cuenta de servicio válida.
    """
    path = CR.get_mailbox_service_account_environment()["gmail_service_account_file"]
    if not path:
        raise ValueError("Falta GMAIL_SERVICE_ACCOUNT_FILE: sin cuenta de servicio no se puede leer el buzón.")
    try:
        with open(path, encoding="utf-8") as handle:
            key = json.load(handle)
    except (OSError, ValueError) as e:
        raise ValueError(f"No se pudo leer la cuenta de servicio de Google: {e}") from e
    if not isinstance(key, dict) or not key.get("client_email") or not key.get("private_key"):
        raise ValueError("El fichero de la cuenta de servicio de Google no tiene client_email y private_key.")
    return key
