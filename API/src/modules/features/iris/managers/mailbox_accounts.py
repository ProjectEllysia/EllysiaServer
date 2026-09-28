"""
IrisMailboxAccountManager — conectar buzones que no pasan por el flujo OAuth.

Dos formas de acceso además del inicio de sesión en Google o Microsoft:

- **IMAP** con usuario y contraseña de aplicación, para cualquier otro
  proveedor. La contraseña se guarda cifrada (``imap_password``) y se cambia
  con la rotación de credenciales, que la prueba contra el servidor antes de
  guardarla.
- **Cuenta de servicio** de la instalación (delegación de dominio en Google,
  permisos de aplicación en Microsoft), para leer un buzón sin que nadie
  inicie sesión. Solo se ofrece para buzones compartidos
  (``managers/shared_mailboxes.py``); aquí vive la comprobación.

Antes de guardar nada se prueba el acceso de verdad (listar las carpetas de
la cuenta), así que una conexión que se da de alta funciona en el momento, y
la carpeta elegida se valida contra las reales, igual que en el flujo OAuth.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests

import src.modules.system.config_reading as CR
from src.modules.accounts import LimitKey, QuotaManager
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.users import UserManager

from ..exceptions import (
    IrisMailboxCredentialsRejectedError,
    IrisMailboxInvalidFolderError,
    IrisMailboxQuotaExceededError,
    IrisSharedMailboxConflictError,
)
from ..model import IrisMailboxConnection, MailboxAuthMode, MailboxKind
from ..repositories import IrisMailboxConnectionRepository
from ..services.mailbox import (
    MAILBOX_CONNECTORS, ImapCredentials, MailboxAuthenticationError, MailboxFolder, get_connector,
)
from .mailbox import IrisMailboxManager

logger = logging.getLogger(__name__)

#: Descripción de los permisos de una conexión IMAP (no hay scopes OAuth).
IMAP_SCOPES = "imap (read-only)"


def _find_folder(folders: list[MailboxFolder], folder: Optional[str]) -> Optional[MailboxFolder]:
    """La carpeta elegida entre las reales de la cuenta.

    Args:
        folders: Carpetas de la cuenta.
        folder: Id elegido; ``None`` para la bandeja por defecto.

    Returns:
        Optional[MailboxFolder]: La carpeta, o ``None`` si se eligió la bandeja.

    Raises:
        IrisMailboxInvalidFolderError: Si no existe en la cuenta.
    """
    if folder is None:
        return None
    match = next((candidate for candidate in folders if candidate.provider_id == folder), None)
    if match is None:
        raise IrisMailboxInvalidFolderError(folder)
    return match


def build_imap_account_email(username: str, host: str) -> str:
    """Dirección con que se muestra una conexión IMAP.

    Args:
        username: Usuario IMAP.
        host: Servidor.

    Returns:
        str: El usuario si ya es una dirección; si no, ``usuario@servidor``.
    """
    username = username.strip()
    return username.lower() if "@" in username else f"{username}@{host.strip().lower()}"


class IrisMailboxAccountManager:
    """Alta de buzones por IMAP y comprobación de credenciales que no son OAuth."""

    @staticmethod
    def probe_imap(credentials: ImapCredentials, folder: Optional[str]) -> Optional[MailboxFolder]:
        """Prueba unas credenciales IMAP contra el servidor y valida la carpeta.

        Args:
            credentials: Servidor, puerto, usuario y contraseña.
            folder: Carpeta elegida; ``None`` para ``INBOX``.

        Returns:
            Optional[MailboxFolder]: La carpeta elegida, o ``None`` para ``INBOX``.

        Raises:
            IrisMailboxCredentialsRejectedError: ``credentials`` si el servidor
                rechaza usuario o contraseña; ``server`` si no es alcanzable,
                es de la red interna o el puerto no está admitido.
            IrisMailboxInvalidFolderError: Si la carpeta no existe.
        """
        connector = get_connector("imap", "", folder=folder, credentials=credentials)
        try:
            folders = connector.list_folders("")
        except MailboxAuthenticationError as e:
            raise IrisMailboxCredentialsRejectedError("credentials", str(e)) from e
        except (ValueError, OSError) as e:
            raise IrisMailboxCredentialsRejectedError("server", str(e)) from e
        return _find_folder(folders, folder)

    @staticmethod
    def probe_service_account(provider: str, mailbox_address: str,
                              folder: Optional[str]) -> Tuple[str, Optional[MailboxFolder]]:
        """Prueba que la cuenta de servicio de la instalación puede leer un buzón.

        Args:
            provider: ``gmail`` o ``microsoft``.
            mailbox_address: Buzón.
            folder: Carpeta elegida; ``None`` para la bandeja.

        Returns:
            Tuple[str, Optional[MailboxFolder]]: Los permisos del token y la
                carpeta elegida (``None`` para la bandeja).

        Raises:
            IrisMailboxCredentialsRejectedError: ``service_account`` si no está
                configurada, el proveedor no la admite o no alcanza al buzón.
            IrisMailboxInvalidFolderError: Si la carpeta no existe.
        """
        connector_class = MAILBOX_CONNECTORS.get(provider)
        if connector_class is None or not connector_class.supports_service_account:
            raise IrisMailboxCredentialsRejectedError("service_account", f"{provider} no admite cuentas de servicio")
        try:
            connector = get_connector(provider, "", folder=folder, mailbox_address=mailbox_address)
            token = connector.acquire_service_token(mailbox_address)
            folders = connector.list_folders(token.access_token)
        except (ValueError, requests.RequestException) as e:
            raise IrisMailboxCredentialsRejectedError("service_account", str(e)) from e
        return token.scopes, _find_folder(folders, folder)

    @classmethod
    def connect_imap(cls, user_id: int, *, host: str, port: int, username: str, password: str,  # pylint: disable=too-many-arguments
                     folder: Optional[str] = None, full_message_mode: bool = False) -> IrisMailboxConnection:
        """Conecta un buzón personal por IMAP.

        Cuenta para el mismo tope de buzones personales que los de OAuth y
        usa la misma superficie de lanzamiento (``mailboxConnectors``).

        Args:
            user_id: Dueño.
            host: Servidor IMAP.
            port: Puerto con TLS directo (ver ``features.iris.imap.allowedPorts``).
            username: Usuario IMAP.
            password: Contraseña de aplicación.
            folder: Carpeta que vigila; ``None`` para ``INBOX``.
            full_message_mode: Si se lee el mensaje completo y no solo las
                cabeceras. Por defecto ``False``.

        Returns:
            IrisMailboxConnection: La conexión creada o, si ya existía la
                misma cuenta, la actualizada con las credenciales nuevas.

        Raises:
            SurfaceDisabledError: Si la conexión de buzones está cerrada.
            IrisMailboxQuotaExceededError: Si ya tiene el máximo de buzones.
            IrisSharedMailboxConflictError: Si esa cuenta ya es un buzón
                compartido a su cargo.
            IrisMailboxCredentialsRejectedError: Si no se puede entrar.
            IrisMailboxInvalidFolderError: Si la carpeta no existe.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.MAILBOX_CONNECTORS, user_id)
        credentials = ImapCredentials(host=host, port=port, username=username, password=password)
        account_email = build_imap_account_email(credentials.username, credentials.host)
        existing = build_repository(IrisMailboxConnectionRepository).get_by_user_provider_email(
            user_id, "imap", account_email)
        if existing is not None and existing.kind != MailboxKind.PERSONAL.value:
            raise IrisSharedMailboxConflictError("already_connected")
        if existing is None:
            QuotaManager().consume(user_id, LimitKey.IRIS_MAILBOX_CONNECTIONS)
            count = build_repository(IrisMailboxConnectionRepository).count_for_user(user_id)
            maximum = CR.iris_config().max_connections_per_user
            if count >= maximum:
                raise IrisMailboxQuotaExceededError(f"Ya tienes {count} conexiones activas (máximo {maximum}).")
        folder_metadata = cls.probe_imap(credentials, folder)

        with UnitOfWork() as uow:
            repo = IrisMailboxConnectionRepository(uow)
            connection = repo.get_by_id(existing.id) if existing is not None else repo.save(IrisMailboxConnection(
                user_id=user_id, provider="imap", account_email=account_email,
                kind=MailboxKind.PERSONAL.value, auth_mode=MailboxAuthMode.IMAP.value,
                scopes=IMAP_SCOPES, additional_folders=[],
            ))
            apply_imap_settings(connection, credentials, folder, folder_metadata, full_message_mode)
            repo.update(connection)
            return connection

    @classmethod
    def rotate_imap_password(cls, connection_id: int, user_id: int, password: str) -> IrisMailboxConnection:
        """Cambia la contraseña de aplicación de una conexión IMAP, probándola antes.

        Si la conexión estaba pendiente de reconectar (el servidor rechazó la
        contraseña anterior), vuelve a quedar activa.

        Args:
            connection_id: Conexión.
            user_id: Quien la administra (su dueño o, en un buzón compartido,
                un responsable).
            password: Contraseña nueva.

        Returns:
            IrisMailboxConnection: La conexión actualizada.

        Raises:
            IrisMailboxConnectionNotFoundError: Si no existe o no puede administrarla.
            IrisMailboxCredentialsRejectedError: Si no es IMAP (``credentials``)
                o el servidor rechaza la contraseña nueva.
        """
        connection = IrisMailboxManager.assert_connection_ownership(connection_id, user_id)
        if connection.auth_mode != MailboxAuthMode.IMAP.value:
            raise IrisMailboxCredentialsRejectedError("credentials", "la conexión no es IMAP")
        credentials = ImapCredentials(host=connection.imap_host, port=connection.imap_port,
                                      username=connection.imap_username, password=password)
        cls.probe_imap(credentials, connection.folder)
        with UnitOfWork() as uow:
            repo = IrisMailboxConnectionRepository(uow)
            fresh = repo.get_by_id(connection_id)
            fresh.imap_password = password
            if fresh.status == "reauth_required":
                fresh.status = "active"
            fresh.last_error = None
            repo.update(fresh)
            return fresh


def apply_imap_settings(connection: IrisMailboxConnection, credentials: ImapCredentials, folder: Optional[str],
                        folder_metadata: Optional[MailboxFolder], full_message_mode: bool) -> None:
    """Escribe en una conexión los datos IMAP ya comprobados y la deja activa.

    Args:
        connection: Conexión (nueva o existente) dentro de una unidad de trabajo.
        credentials: Credenciales comprobadas.
        folder: Carpeta elegida; ``None`` para ``INBOX``.
        folder_metadata: Su nombre y tipo, o ``None``.
        full_message_mode: Si se lee el mensaje completo.
    """
    connection.imap_host = credentials.host.strip().lower()
    connection.imap_port = credentials.port
    connection.imap_username = credentials.username.strip()
    connection.imap_password = credentials.password
    connection.folder = folder
    connection.folder_display_name = folder_metadata.display_name if folder_metadata else None
    connection.folder_type = folder_metadata.folder_type if folder_metadata else None
    connection.full_message_mode = full_message_mode
    connection.status = "active"
    connection.last_error = None
