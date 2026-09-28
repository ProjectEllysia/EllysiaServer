"""
GraphConnector — Microsoft Graph API v1.0 sobre OAuth 2.0 de Entra ID
(Azure AD).

Mismo criterio que ``gmail.py``: ``requests`` puro, sin ``msal``.

**Matiz que el plan no cubre (decisión de diseño de esta sesión):** Graph no
tiene un scope "solo metadata" para correo como Gmail (``gmail.metadata``);
el permiso delegado ``Mail.Read`` da acceso al cuerpo completo siempre. Para
este conector, "solo cabeceras" se aplica a nivel de *aplicación* — el
conector simplemente nunca pide ``$value``/el cuerpo del mensaje cuando
``full_message_mode`` es False — no a nivel de scope OAuth. El usuario que
conecta una cuenta Microsoft con el modo completo desactivado sigue
concediendo un permiso que técnicamente permite más de lo que Iris
efectivamente usa; es una limitación de la plataforma, no de este código.

Las acciones sobre el buzón (cuarentena, spam, papelera, categoría de
sospechoso) necesitan ``Mail.ReadWrite``, que solo se pide si el usuario
activa las acciones al conectar. Mover un mensaje en Graph le da un id nuevo:
cada acción devuelve el id resultante para que el siguiente paso lo use.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import requests

import src.modules.system.config_reading as CR

from .base import ActionResult, MailboxConnector, MailboxFolder, MessageRef, SubscriptionInfo, TokenSet
from .registry import register_connector

logger = logging.getLogger(__name__)

_GRAPH_API = "https://graph.microsoft.com/v1.0"

# Mismo criterio que _METADATA_HEADERS de gmail.py: solo lo que las 40
# reglas de Iris usan.
_SELECT_FIELDS = "internetMessageHeaders"

_TIMEOUT_SECONDS = 20

# Permiso delegado para mover y categorizar mensajes del propio usuario.
_SCOPE_READ_WRITE = "Mail.ReadWrite"

# Carpetas bien conocidas de Graph adonde van «no deseado» y «papelera».
_FOLDER_JUNK = "junkemail"
_FOLDER_DELETED = "deleteditems"


@register_connector("microsoft")
class GraphConnector(MailboxConnector):
    provider = "microsoft"

    def __init__(self, redirect_uri: str, folder: Optional[str] = None) -> None:
        env = CR.get_graph_environment()
        self._client_id = env["client_id"]
        self._client_secret = env["client_secret"]
        self._tenant = env["tenant"]
        self._redirect_uri = redirect_uri
        # Nombre bien conocido ("inbox") o id de mailFolder de Graph.
        self._folder = folder or "inbox"

    @property
    def _authority(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant}"

    def authorize_url(self, state: str, full_message_mode: bool, remediation_enabled: bool = False) -> str:
        # full_message_mode no cambia el scope aquí (ver docstring del
        # módulo) -- se aplica en fetch_raw/list_new, no en el consentimiento.
        # Las acciones sí: mover o categorizar exige Mail.ReadWrite.
        mail_scope = _SCOPE_READ_WRITE if remediation_enabled else "Mail.Read"
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "response_mode": "query",
            "scope": f"offline_access openid email {mail_scope}",
            "state": state,
        }
        return f"{self._authority}/oauth2/v2.0/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenSet:
        response = requests.post(f"{self._authority}/oauth2/v2.0/token", data={
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        account_email = self._get_account_email(payload["access_token"])
        return self._token_set_from(payload, account_email)

    def refresh(self, refresh_token: str) -> TokenSet:
        response = requests.post(f"{self._authority}/oauth2/v2.0/token", data={
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        payload.setdefault("refresh_token", refresh_token)
        account_email = self._get_account_email(payload["access_token"])
        return self._token_set_from(payload, account_email)

    def list_new(self, access_token: str, cursor: Optional[str]) -> tuple[list[MessageRef], str]:
        headers = {"Authorization": f"Bearer {access_token}"}

        if cursor is None:
            # Bootstrap: paginar el delta completo UNA vez, descartando el
            # contenido, hasta obtener el deltaLink final -- sin backfill.
            url = (
                f"{_GRAPH_API}/me/mailFolders/{self._folder}/messages/delta"
                f"?$select={_SELECT_FIELDS}"
            )
            while True:
                response = requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
                response.raise_for_status()
                data = response.json()
                if "@odata.deltaLink" in data:
                    return [], data["@odata.deltaLink"]
                url = data["@odata.nextLink"]

        refs: list[MessageRef] = []
        url = cursor
        new_cursor = cursor
        while True:
            response = requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
            if response.status_code == 410:
                # Gone: el deltaLink expiró (ventana de retención de Graph) --
                # única opción es re-bootstrapear, igual que el 404 de Gmail.
                logger.warning("Graph delta cursor expirado, re-bootstrapping")
                return self.list_new(access_token, cursor=None)
            response.raise_for_status()
            data = response.json()

            for item in data.get("value", []):
                refs.append(MessageRef(
                    provider_message_id=item["id"],
                    raw={"internetMessageHeaders": item.get("internetMessageHeaders", [])},
                ))

            if "@odata.deltaLink" in data:
                new_cursor = data["@odata.deltaLink"]
                break
            url = data["@odata.nextLink"]

        return refs, new_cursor

    def fetch_headers(self, access_token: str, message_ref: MessageRef) -> str:
        cached = message_ref.raw.get("internetMessageHeaders")
        if cached is None:
            response = requests.get(
                f"{_GRAPH_API}/me/messages/{message_ref.provider_message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"$select": _SELECT_FIELDS}, timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            cached = response.json().get("internetMessageHeaders", [])
        return "".join(f"{header['name']}: {header['value']}\r\n" for header in cached)

    def fetch_raw(self, access_token: str, message_ref: MessageRef) -> str:
        response = requests.get(
            f"{_GRAPH_API}/me/messages/{message_ref.provider_message_id}/$value",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.text

    def list_folders(self, access_token: str) -> list[MailboxFolder]:
        headers = {"Authorization": f"Bearer {access_token}"}
        folders: list[MailboxFolder] = []
        # Solo carpetas de primer nivel -- Gmail tampoco anida etiquetas, y
        # bajar a subcarpetas exigiría recorrer el árbol entero por cuenta.
        url = f"{_GRAPH_API}/me/mailFolders?$top=250"
        while url:
            response = requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            for item in data.get("value", []):
                folders.append(MailboxFolder(
                    provider_id=item["id"], display_name=item["displayName"],
                    # wellKnownName solo está presente en carpetas propias de
                    # Graph (inbox, sentitems, deleteditems...); su ausencia
                    # es la señal de que la creó el usuario.
                    folder_type="system" if item.get("wellKnownName") else "user",
                ))
            url = data.get("@odata.nextLink")
        return folders

    def subscribe(self, access_token: str, notification_url: str, client_state: str) -> SubscriptionInfo:
        expires_at = _subscription_expiry()
        response = requests.post(
            f"{_GRAPH_API}/subscriptions", headers={"Authorization": f"Bearer {access_token}"},
            json={
                "changeType": "created",
                "notificationUrl": notification_url,
                "resource": f"me/mailFolders('{self._folder}')/messages",
                "expirationDateTime": expires_at.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                "clientState": client_state,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return SubscriptionInfo(expires_at=expires_at, external_id=response.json()["id"])

    def renew(self, access_token: str, external_id: Optional[str], notification_url: str,
              client_state: str) -> SubscriptionInfo:
        if not external_id:
            return self.subscribe(access_token, notification_url, client_state)
        expires_at = _subscription_expiry()
        response = requests.patch(
            f"{_GRAPH_API}/subscriptions/{external_id}", headers={"Authorization": f"Bearer {access_token}"},
            json={"expirationDateTime": expires_at.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")},
            timeout=_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            # Graph ya la borró (caducó): se crea otra en su lugar.
            return self.subscribe(access_token, notification_url, client_state)
        response.raise_for_status()
        return SubscriptionInfo(expires_at=expires_at, external_id=external_id)

    def unsubscribe(self, access_token: str, external_id: Optional[str]) -> None:
        if not external_id:
            return
        response = requests.delete(f"{_GRAPH_API}/subscriptions/{external_id}",
                                   headers={"Authorization": f"Bearer {access_token}"}, timeout=_TIMEOUT_SECONDS)
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()

    @staticmethod
    def can_act(scopes: str) -> bool:
        return _SCOPE_READ_WRITE.lower() in (scopes or "").lower().split()

    def quarantine(self, access_token: str, message_id: str, folder_name: str) -> ActionResult:
        return _move_message(access_token, message_id, _ensure_folder(access_token, folder_name))

    def label(self, access_token: str, message_id: str, label_name: str) -> ActionResult:
        categories = _message_field(access_token, message_id, "categories") or []
        if label_name not in categories:
            _patch_categories(access_token, message_id, [*categories, label_name])
        return ActionResult(provider_message_id=message_id, previous_state={"categories": categories})

    def report_phishing(self, access_token: str, message_id: str) -> ActionResult:
        return _move_message(access_token, message_id, _FOLDER_JUNK)

    def delete(self, access_token: str, message_id: str) -> ActionResult:
        # Mover a «Elementos eliminados», no DELETE: un DELETE de Graph lo saca
        # también de ahí y ya no se puede deshacer.
        return _move_message(access_token, message_id, _FOLDER_DELETED)

    def undo(self, access_token: str, action: str, message_id: str, previous_state: dict,
             label_name: str) -> str:
        if "categories" in previous_state:
            current = _message_field(access_token, message_id, "categories") or []
            _patch_categories(access_token, message_id, [category for category in current if category != label_name])
            return message_id
        return _move_message(access_token, message_id, previous_state["parentFolderId"]).provider_message_id

    def revoke(self, refresh_token: str) -> None:
        # Microsoft Graph no expone una API para que una app confidencial
        # revoque un refresh_token concreto emitido a un usuario (a
        # diferencia de Google) -- solo el propio usuario
        # (myaccount.microsoft.com) o un admin de Entra ID pueden hacerlo.
        # Documentado explícitamente en vez de fingir una llamada que no
        # existe: borrar la fila localmente sigue siendo correcto (el
        # conector guarda lo mínimo), el token simplemente sigue siendo válido en
        # el lado de Microsoft hasta que expire o el usuario lo revoque allí.
        logger.warning(
            "Microsoft Graph no soporta revocación de refresh_token por la "
            "app; la conexión se borra localmente pero el token puede "
            "seguir siendo válido hasta que el usuario lo revoque en "
            "myaccount.microsoft.com."
        )

    @staticmethod
    def _get_account_email(access_token: str) -> str:
        response = requests.get(
            f"{_GRAPH_API}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "mail,userPrincipalName"}, timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        profile = response.json()
        # "mail" es NULL para algunas cuentas (p.ej. algunas de solo-Azure-AD
        # sin buzón Exchange asociado a ese campo); userPrincipalName es el
        # identificador que siempre existe.
        return profile.get("mail") or profile["userPrincipalName"]

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


def _message_field(access_token: str, message_id: str, field_name: str):
    """Un campo de un mensaje de Graph (``parentFolderId``, ``categories``…).

    Args:
        access_token: Token de acceso vigente.
        message_id: Id del mensaje en Graph.
        field_name: Propiedad del recurso ``message``.

    Returns:
        El valor del campo, o ``None`` si no viene.
    """
    response = requests.get(
        f"{_GRAPH_API}/me/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"$select": field_name}, timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get(field_name)


def _move_message(access_token: str, message_id: str, destination_id: str) -> ActionResult:
    """Mueve un mensaje a otra carpeta y devuelve su id nuevo y la carpeta de origen.

    Args:
        access_token: Token de acceso vigente.
        message_id: Id actual del mensaje.
        destination_id: Id de carpeta o nombre bien conocido (``junkemail``…).

    Returns:
        ActionResult: El id que Graph le da tras moverlo (cambia en cada
            movimiento) y ``{"parentFolderId": <carpeta de antes>}``.
    """
    parent_folder_id = _message_field(access_token, message_id, "parentFolderId")
    response = requests.post(
        f"{_GRAPH_API}/me/messages/{message_id}/move",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"destinationId": destination_id}, timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return ActionResult(provider_message_id=response.json().get("id", message_id),
                        previous_state={"parentFolderId": parent_folder_id})


def _patch_categories(access_token: str, message_id: str, categories: list) -> None:
    """Sustituye las categorías de un mensaje.

    Args:
        access_token: Token de acceso vigente.
        message_id: Id del mensaje en Graph.
        categories: Lista completa de categorías que debe quedar.
    """
    response = requests.patch(
        f"{_GRAPH_API}/me/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"categories": categories}, timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _ensure_folder(access_token: str, name: str) -> str:
    """Id de una carpeta de primer nivel por su nombre, creándola si no existe.

    Args:
        access_token: Token de acceso vigente.
        name: Nombre visible de la carpeta.

    Returns:
        str: Id de la carpeta.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    escaped = name.replace("'", "''")
    response = requests.get(
        f"{_GRAPH_API}/me/mailFolders", headers=headers,
        params={"$filter": f"displayName eq '{escaped}'"}, timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    existing = response.json().get("value", [])
    if existing:
        return existing[0]["id"]
    response = requests.post(f"{_GRAPH_API}/me/mailFolders", headers=headers,
                             json={"displayName": name}, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()["id"]


def _subscription_expiry() -> datetime:
    """Caducidad que se pide para una suscripción de Graph: ahora más ``graphSubscriptionMinutes``.

    Returns:
        datetime: En UTC, naive.
    """
    minutes = CR.iris_mailbox_events_config().graph_subscription_minutes
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes)
