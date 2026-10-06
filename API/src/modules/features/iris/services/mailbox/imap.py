"""
ImapConnector — cualquier buzón con IMAP, con usuario y contraseña de aplicación.

Para buzones que no son de Google ni de Microsoft, o que la organización
prefiere no conectar por OAuth. Tres decisiones que no se ven en el código a
simple vista:

- **Solo IMAP sobre TLS directo** (993 por defecto, ``features.iris.imap.
  allowedPorts``) y con el certificado verificado contra el nombre del
  servidor. No se admite IMAP en claro ni STARTTLS, que un intermediario
  puede degradar a texto plano y exponer la contraseña.
- **Nunca contra la red interna.** El servidor lo escribe el usuario, así que
  es una puerta de SSRF como cualquier URL: se resuelve el nombre, se exige
  que todas sus direcciones sean públicas y se conecta a esa dirección fijada
  (``egress.resolve_public_address``), para que un DNS que cambie entre la
  comprobación y la conexión no la cuele.
- **Solo lectura.** La carpeta se abre con ``EXAMINE`` y los mensajes se leen
  con ``BODY.PEEK``: Iris no marca nada como leído ni puede mover o borrar.

El cursor es ``<UIDVALIDITY>:<último UID visto>``. Si el servidor cambia el
``UIDVALIDITY`` (los UID dejan de valer), se vuelve a arrancar sin backfill,
igual que con un cursor caducado de Gmail o Graph.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
import socket
import ssl
from dataclasses import dataclass
from email.policy import compat32
from typing import Optional

import src.modules.system.config_reading as CR

from ..enrichment import egress
from .base import (
    ActionResult, MailboxAuthenticationError, MailboxConnector, MailboxFolder, MessageRef, SubscriptionInfo,
    TokenSet,
)
from .registry import register_connector

logger = logging.getLogger(__name__)

_INBOX = "INBOX"

#: Marcas de uso especial (RFC 6154) que identifican una carpeta del sistema.
_SPECIAL_USE_FLAGS = {"\\sent", "\\drafts", "\\trash", "\\junk", "\\archive", "\\all", "\\flagged"}

_LIST_LINE = re.compile(r'^\((?P<flags>[^)]*)\) (?P<delimiter>"[^"]*"|NIL) (?P<name>.+)$')


@dataclass(frozen=True)
class ImapCredentials:
    """Dónde y con qué se entra en un buzón IMAP.

    Attributes:
        host: Nombre del servidor (``imap.proveedor.com``).
        port: Puerto IMAP con TLS directo.
        username: Usuario, normalmente la dirección de correo.
        password: Contraseña de aplicación.
    """
    host: str
    port: int
    username: str
    password: str


class PinnedImapClient(imaplib.IMAP4_SSL):
    """Cliente IMAP con TLS que conecta a una dirección ya comprobada.

    ``imaplib`` resuelve el nombre por su cuenta al conectar; aquí se conecta
    a la IP que ``egress.resolve_public_address`` ya validó como pública, y el
    certificado se verifica igualmente contra el nombre del servidor.
    """

    def __init__(self, host: str, port: int, pinned_address: str, timeout: float) -> None:
        """Abre la conexión TLS.

        Args:
            host: Nombre del servidor, para SNI y la verificación del certificado.
            port: Puerto.
            pinned_address: IP pública a la que se conecta.
            timeout: Segundos de espera por operación.
        """
        self.pinned_address = pinned_address
        super().__init__(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self.pinned_address, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def open_session(credentials: ImapCredentials) -> PinnedImapClient:
    """Conecta y se autentica contra un servidor IMAP, con todas las comprobaciones.

    Args:
        credentials: Servidor, puerto, usuario y contraseña.

    Returns:
        PinnedImapClient: Sesión autenticada. Quien la abre la cierra con ``logout()``.

    Raises:
        ValueError: Si el puerto no está permitido o el servidor no es de
            internet (red interna, nombre que no resuelve).
        MailboxAuthenticationError: Si el servidor rechaza usuario o contraseña.
        OSError: Si no se puede conectar o el certificado no es válido.
    """
    config = CR.iris_imap_config()
    if credentials.port not in {int(port) for port in config.allowed_ports}:
        raise ValueError(f"Puerto IMAP no permitido: {credentials.port}. Solo IMAP con TLS directo "
                         f"({', '.join(str(port) for port in config.allowed_ports)}).")
    try:
        address = egress.resolve_public_address(credentials.host, credentials.port)
    except egress.EgressBlockedError as e:
        raise ValueError(f"El servidor IMAP no es alcanzable desde internet: {e}") from e
    client = PinnedImapClient(credentials.host, credentials.port, address, config.timeout_seconds)
    try:
        client.login(credentials.username, credentials.password)
    except imaplib.IMAP4.error as e:
        client.shutdown()
        raise MailboxAuthenticationError(f"El servidor IMAP rechazó el usuario o la contraseña: {e}") from e
    return client


def parse_folder_list(lines: list) -> list[MailboxFolder]:
    """Convierte la respuesta de ``LIST`` en carpetas.

    Args:
        lines: Líneas de la respuesta (``bytes``), como
            ``(\\HasNoChildren \\Sent) "/" "Enviados"``.

    Returns:
        list[MailboxFolder]: Las carpetas seleccionables; ``system`` para
            ``INBOX`` y las de uso especial, ``user`` para el resto.
    """
    folders = []
    for raw in lines:
        if not isinstance(raw, bytes):
            continue
        match = _LIST_LINE.match(raw.decode("utf-8", errors="replace"))
        if match is None:
            continue
        flags = {flag.lower() for flag in match.group("flags").split()}
        if "\\noselect" in flags or "\\nonexistent" in flags:
            continue
        name = match.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        is_system = name.upper() == _INBOX or bool(flags & _SPECIAL_USE_FLAGS)
        folders.append(MailboxFolder(provider_id=name, display_name=name,
                                     folder_type="system" if is_system else "user"))
    return folders


def build_message_id(uid_validity: str, uid: int, folder: str) -> str:
    """Id de un mensaje IMAP: ``<UIDVALIDITY>:<UID>:<carpeta>``.

    Lleva la carpeta porque un UID solo es único dentro de ella, y el
    ``UIDVALIDITY`` para que un id de antes de un cambio no apunte a otro correo.

    Args:
        uid_validity: ``UIDVALIDITY`` de la carpeta.
        uid: UID del mensaje.
        folder: Carpeta.

    Returns:
        str: El id.
    """
    return f"{uid_validity}:{uid}:{folder}"


def parse_message_id(message_id: str) -> tuple[str, int, str]:
    """Inversa de ``build_message_id``.

    Args:
        message_id: Id construido por ``build_message_id``.

    Returns:
        tuple: ``(uid_validity, uid, carpeta)``.

    Raises:
        ValueError: Si el id no tiene esa forma.
    """
    uid_validity, uid, folder = message_id.split(":", 2)
    return uid_validity, int(uid), folder


def _quote_mailbox(name: str) -> str:
    """Nombre de carpeta entre comillas, como lo espera IMAP.

    Args:
        name: Nombre de la carpeta.

    Returns:
        str: El nombre entrecomillado y escapado.
    """
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _examine(client: PinnedImapClient, folder: str) -> tuple[str, int]:
    """Abre una carpeta en solo lectura.

    Args:
        client: Sesión autenticada.
        folder: Carpeta.

    Returns:
        tuple: ``(UIDVALIDITY, UIDNEXT)``.

    Raises:
        ValueError: Si la carpeta no existe.
    """
    status, _ = client.select(_quote_mailbox(folder), readonly=True)
    if status != "OK":
        raise ValueError(f"La carpeta IMAP {folder!r} no existe o no se puede abrir.")
    uid_validity = (client.response("UIDVALIDITY")[1] or [b"0"])[0]
    uid_next = (client.response("UIDNEXT")[1] or [None])[0]
    if uid_next is None:
        _, data = client.status(_quote_mailbox(folder), "(UIDNEXT)")
        found = re.search(rb"UIDNEXT (\d+)", data[0] or b"")
        uid_next = found.group(1) if found else b"1"
    return uid_validity.decode(), int(uid_next)


def _fetch_part(client: PinnedImapClient, message_id: str, part: str) -> bytes:
    """Lee una parte de un mensaje sin marcarlo como leído.

    Args:
        client: Sesión autenticada.
        message_id: Id de ``build_message_id``.
        part: ``BODY.PEEK[HEADER]`` o ``BODY.PEEK[]``.

    Returns:
        bytes: El contenido.

    Raises:
        ValueError: Si el mensaje ya no está o la carpeta cambió de ``UIDVALIDITY``.
    """
    uid_validity, uid, folder = parse_message_id(message_id)
    current_validity, _ = _examine(client, folder)
    if current_validity != uid_validity:
        raise ValueError("La carpeta IMAP cambió de UIDVALIDITY: el mensaje ya no se puede localizar.")
    status, data = client.uid("FETCH", str(uid), f"({part})")
    for item in data or []:
        if status == "OK" and isinstance(item, tuple) and len(item) == 2:
            return item[1]
    raise ValueError(f"El mensaje IMAP {uid} ya no está en {folder!r}.")


@register_connector("imap")
class ImapConnector(MailboxConnector):
    """Conector IMAP de solo lectura; no usa ``access_token`` (la sesión se abre con la contraseña)."""

    provider = "imap"
    supports_oauth = False
    supports_events = False

    def __init__(self, redirect_uri: str, folder: Optional[str] = None,
                 credentials: Optional[ImapCredentials] = None) -> None:
        """Prepara el conector de una conexión.

        Args:
            redirect_uri: No se usa (IMAP no tiene flujo OAuth); se acepta por
                la firma común de los conectores.
            folder: Carpeta que vigila; ``None`` para ``INBOX``.
            credentials: Servidor y credenciales. Obligatorias para hablar
                con el servidor.
        """
        self._folder = folder or _INBOX
        self._credentials = credentials

    def list_new(self, access_token: str, cursor: Optional[str]) -> tuple[list[MessageRef], str]:
        client = open_session(self.require_credentials())
        try:
            uid_validity, uid_next = _examine(client, self._folder)
            last_uid = None
            if cursor:
                cursor_validity, _, cursor_uid = cursor.partition(":")
                if cursor_validity == uid_validity and cursor_uid.isdigit():
                    last_uid = int(cursor_uid)
                else:
                    logger.warning("La carpeta IMAP cambió de UIDVALIDITY; se vuelve a arrancar sin backfill")
            if last_uid is None:
                return [], f"{uid_validity}:{uid_next - 1}"
            status, data = client.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            # «n:*» devuelve el último mensaje aunque su UID sea menor que n,
            # así que se filtra: solo cuenta lo posterior al cursor.
            uids = sorted(int(uid) for uid in (data[0] or b"").split() if int(uid) > last_uid) if status == "OK" else []
            uids = uids[:CR.iris_imap_config().max_messages_per_sync]
            refs = [MessageRef(provider_message_id=build_message_id(uid_validity, uid, self._folder)) for uid in uids]
            return refs, f"{uid_validity}:{uids[-1] if uids else last_uid}"
        finally:
            client.shutdown()

    def fetch_headers(self, access_token: str, message_ref: MessageRef) -> str:
        client = open_session(self.require_credentials())
        try:
            raw = _fetch_part(client, message_ref.provider_message_id, "BODY.PEEK[HEADER]")
        finally:
            client.shutdown()
        message = email.message_from_bytes(raw, policy=compat32)
        return "".join(f"{name}: {value}\r\n" for name, value in message.items())

    def fetch_raw(self, access_token: str, message_ref: MessageRef) -> str:
        client = open_session(self.require_credentials())
        try:
            raw = _fetch_part(client, message_ref.provider_message_id, "BODY.PEEK[]")
        finally:
            client.shutdown()
        return raw.decode("utf-8", errors="replace")

    def list_folders(self, access_token: str) -> list[MailboxFolder]:
        client = open_session(self.require_credentials())
        try:
            status, data = client.list()
        finally:
            client.shutdown()
        return parse_folder_list(data) if status == "OK" else []

    def require_credentials(self) -> ImapCredentials:
        """Las credenciales de la conexión.

        Returns:
            ImapCredentials: Las que se dieron al construirlo.

        Raises:
            ValueError: Si se construyó sin ellas.
        """
        if self._credentials is None:
            raise ValueError("Conexión IMAP sin credenciales.")
        return self._credentials

    # --- Lo que IMAP no tiene: OAuth, avisos de correo nuevo y acciones.

    def authorize_url(self, state: str, full_message_mode: bool, remediation_enabled: bool = False) -> str:
        raise NotImplementedError("IMAP no usa OAuth: se conecta con usuario y contraseña de aplicación.")

    def exchange_code(self, code: str) -> TokenSet:
        raise NotImplementedError("IMAP no usa OAuth.")

    def refresh(self, refresh_token: str) -> TokenSet:
        raise NotImplementedError("IMAP no usa OAuth.")

    def revoke(self, refresh_token: str) -> None:
        # No hay nada que revocar en el servidor: basta con borrar la contraseña guardada.
        return None

    def subscribe(self, access_token: str, notification_url: str, client_state: str) -> SubscriptionInfo:
        raise NotImplementedError("IMAP no avisa de correo nuevo; se sigue por sondeo.")

    def renew(self, access_token: str, external_id: Optional[str], notification_url: str,
              client_state: str) -> SubscriptionInfo:
        raise NotImplementedError("IMAP no avisa de correo nuevo; se sigue por sondeo.")

    def unsubscribe(self, access_token: str, external_id: Optional[str]) -> None:
        return None

    @staticmethod
    def can_act(scopes: str) -> bool:
        return False

    def quarantine(self, access_token: str, message_id: str, folder_name: str) -> ActionResult:
        raise NotImplementedError("Las conexiones IMAP son de solo lectura.")

    def label(self, access_token: str, message_id: str, label_name: str) -> ActionResult:
        raise NotImplementedError("Las conexiones IMAP son de solo lectura.")

    def report_phishing(self, access_token: str, message_id: str) -> ActionResult:
        raise NotImplementedError("Las conexiones IMAP son de solo lectura.")

    def delete(self, access_token: str, message_id: str) -> ActionResult:
        raise NotImplementedError("Las conexiones IMAP son de solo lectura.")

    def undo(self, access_token: str, action: str, message_id: str, previous_state: dict,
             label_name: str) -> str:
        raise NotImplementedError("Las conexiones IMAP son de solo lectura.")
