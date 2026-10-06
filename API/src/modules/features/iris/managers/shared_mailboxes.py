"""
IrisSharedMailboxManager — buzones de la organización y quién ve sus análisis.

Un buzón compartido (``soporte@empresa.com``, ``facturas@empresa.com``) no es
de una persona, así que el modelo de propiedad de los buzones personales («solo
lo ve su dueño») no sirve. La política es explícita y cerrada:

- **Lo conecta el dueño de la organización**, con el permiso
  ``iris_shared_mailbox``, por cuenta de servicio o por IMAP (nunca con su
  sesión personal: el buzón no debe depender de que esa persona siga
  conectada). Queda a su nombre (``user_id``) y los análisis también: es quien
  responde del buzón.
- **Lo ven solo las personas con acceso explícito** (``IrisMailboxMember``):
  ``viewer`` ve los análisis de sus correos; ``manager`` además decide quién
  más los ve, cambia carpetas y credenciales y lo desconecta.
- **Todo acceso exige seguir en la organización.** Salir de ella quita el
  acceso en el acto; y si quien lo conectó sale, el buzón deja de
  sincronizarse (``IrisMailboxManager``).
- **Mismo error para «no existe» y «no tienes acceso»**, para no revelar qué
  buzones hay.

Las acciones sobre el correo (cuarentena, spam) no se ofrecen en un buzón
compartido: decidir quién responde de cada acción en un buzón de varios es una
política aparte.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import src.modules.system.config_reading as CR
from src.modules.accounts import OrganizationManager
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.users import UserManager

from ..exceptions import (
    IrisAnalysisNotFoundError,
    IrisMailboxConnectionNotFoundError,
    IrisSharedMailboxConflictError,
    IrisSharedMailboxLimitError,
    IrisSharedMailboxOwnerRequiredError,
)
from ..model import IrisMailboxConnection, IrisMailboxMember, MailboxAuthMode, MailboxKind, SharedMailboxAccess
from ..repositories import IrisAnalysisRepository, IrisMailboxConnectionRepository, IrisMailboxMemberRepository
from ..services.mailbox import ImapCredentials
from .analysis import IrisManager
from .mailbox import IrisMailboxManager
from .mailbox_accounts import IMAP_SCOPES, IrisMailboxAccountManager, apply_imap_settings, build_imap_account_email

logger = logging.getLogger(__name__)


def _require_access(connection_id: int, user_id: int, require_manager: bool = False) -> IrisMailboxConnection:
    """El buzón compartido, si la persona tiene acceso; si no, como si no existiera.

    Args:
        connection_id: Buzón.
        user_id: Persona.
        require_manager: Si hace falta acceso ``manager``. Por defecto ``False``.

    Returns:
        IrisMailboxConnection: El buzón.

    Raises:
        IrisMailboxConnectionNotFoundError: Si no existe, no es compartido o no
            tiene acceso (el mismo error en los tres casos).
    """
    connection = build_repository(IrisMailboxConnectionRepository).get_by_id(connection_id)
    if connection is None or not IrisMailboxManager.has_shared_access(connection, user_id, require_manager):
        raise IrisMailboxConnectionNotFoundError(connection_id)
    return connection


def _owned_organization(user_id: int) -> Dict[str, Any]:
    """La organización de la que el usuario es dueño.

    Args:
        user_id: Usuario.

    Returns:
        dict: La organización (``id``, ``name``…).

    Raises:
        IrisSharedMailboxOwnerRequiredError: Si no pertenece a ninguna o no es su dueño.
    """
    organization = OrganizationManager().get_mine(user_id)
    if organization is None or not organization.get("isOwner"):
        raise IrisSharedMailboxOwnerRequiredError()
    return organization


def _describe(connection: IrisMailboxConnection, access: Optional[str]) -> Dict[str, Any]:
    """Lo que se enseña de un buzón compartido. Nunca credenciales.

    Args:
        connection: El buzón.
        access: Acceso de quien lo mira (``viewer`` o ``manager``).

    Returns:
        dict: Identidad, estado, carpetas y el acceso propio.
    """
    return {
        "id": connection.id,
        "provider": connection.provider,
        "accountEmail": connection.account_email,
        "authMode": connection.auth_mode,
        "status": connection.status,
        "folder": connection.folder,
        "folderDisplayName": connection.folder_display_name,
        "additionalFolders": connection.additional_folders or [],
        "fullMessageMode": connection.full_message_mode,
        "lastSyncAt": isoformat_utc(connection.last_sync_at),
        "lastError": connection.last_error if access == SharedMailboxAccess.MANAGER.value else None,
        "createdAt": isoformat_utc(connection.created_at),
        "myAccess": access,
    }


def _describe_member(member: IrisMailboxMember) -> Dict[str, Any]:
    """Una persona con acceso a un buzón.

    Args:
        member: El acceso.

    Returns:
        dict: ``userId``, ``username``, ``access`` y ``grantedAt``.
    """
    user = UserManager().get_user_by_id(member.user_id)
    return {
        "userId": member.user_id,
        "username": getattr(user, "username", None),
        "access": member.access,
        "grantedAt": isoformat_utc(member.granted_at),
    }


class IrisSharedMailboxManager:
    """Buzones compartidos: alta, acceso de personas y consulta de sus análisis."""

    @staticmethod
    def create(user_id: int, provider: str, mailbox_address: str, *, folder: Optional[str] = None,
               full_message_mode: bool = False, imap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Conecta un buzón compartido de la organización del usuario.

        Con ``provider`` ``gmail`` o ``microsoft`` se accede con la cuenta de
        servicio de la instalación; con ``imap``, con las credenciales dadas.
        El acceso se prueba antes de guardar nada. Quien lo conecta queda
        como su primer responsable (``manager``).

        Args:
            user_id: Dueño de la organización.
            provider: ``gmail``, ``microsoft`` o ``imap``.
            mailbox_address: Dirección del buzón (en IMAP, informativa si el
                usuario IMAP ya es una dirección).
            folder: Carpeta que vigila; ``None`` para la bandeja.
            full_message_mode: Si se lee el mensaje completo. Por defecto ``False``.
            imap: Con ``provider="imap"``: ``host``, ``port``, ``username`` y
                ``password``.

        Returns:
            dict: El buzón, como en ``list_for_user``.

        Raises:
            SurfaceDisabledError: Si la conexión de buzones está cerrada.
            IrisSharedMailboxOwnerRequiredError: Si no es dueño de una organización.
            IrisSharedMailboxLimitError: Si la organización ya tiene el máximo.
            IrisSharedMailboxConflictError: ``already_connected`` si ya está conectado.
            IrisMailboxCredentialsRejectedError: Si no se puede entrar.
            IrisMailboxInvalidFolderError: Si la carpeta no existe.
        """
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.MAILBOX_CONNECTORS, user_id)
        organization = _owned_organization(user_id)
        repo = build_repository(IrisMailboxConnectionRepository)
        maximum = CR.iris_shared_mailboxes_config().max_per_organization
        if len(repo.get_shared_by_organization(organization["id"])) >= maximum:
            raise IrisSharedMailboxLimitError("mailboxes", maximum)

        credentials = None
        if provider == "imap":
            credentials = ImapCredentials(host=imap["host"], port=int(imap["port"]), username=imap["username"],
                                          password=imap["password"])
            mailbox_address = build_imap_account_email(credentials.username, credentials.host)
        mailbox_address = mailbox_address.strip().lower()
        # Una misma persona no puede tener dos conexiones de la misma cuenta
        # (restricción única), así que tampoco vale una personal suya.
        if (repo.get_shared_by_organization_and_address(organization["id"], provider, mailbox_address) is not None
                or repo.get_by_user_provider_email(user_id, provider, mailbox_address) is not None):
            raise IrisSharedMailboxConflictError("already_connected")

        if credentials is not None:
            folder_metadata = IrisMailboxAccountManager.probe_imap(credentials, folder)
            scopes = IMAP_SCOPES
        else:
            scopes, folder_metadata = IrisMailboxAccountManager.probe_service_account(provider, mailbox_address, folder)

        now = utcnow_naive()
        with UnitOfWork() as uow:
            connection_repo = IrisMailboxConnectionRepository(uow)
            connection = connection_repo.save(IrisMailboxConnection(
                user_id=user_id, provider=provider, account_email=mailbox_address, scopes=scopes,
                kind=MailboxKind.SHARED.value, organization_id=organization["id"],
                auth_mode=MailboxAuthMode.IMAP.value if credentials else MailboxAuthMode.SERVICE_ACCOUNT.value,
                folder=folder, folder_display_name=folder_metadata.display_name if folder_metadata else None,
                folder_type=folder_metadata.folder_type if folder_metadata else None,
                full_message_mode=full_message_mode, additional_folders=[], created_at=now,
            ))
            if credentials is not None:
                apply_imap_settings(connection, credentials, folder, folder_metadata, full_message_mode)
            IrisMailboxMemberRepository(uow).save(IrisMailboxMember(
                connection_id=connection.id, user_id=user_id, access=SharedMailboxAccess.MANAGER.value,
                granted_by_user_id=user_id, granted_at=now,
            ))
            return _describe(connection, SharedMailboxAccess.MANAGER.value)

    @staticmethod
    def list_for_user(user_id: int) -> List[Dict[str, Any]]:
        """Buzones compartidos de su organización a los que la persona tiene acceso.

        Args:
            user_id: Persona.

        Returns:
            List[dict]: Los buzones, con ``myAccess``; vacía si no pertenece a
                ninguna organización.
        """
        organization = OrganizationManager().get_mine(user_id)
        if organization is None:
            return []
        member_repo = build_repository(IrisMailboxMemberRepository)
        return [
            _describe(connection, member_repo.get_by_connection_and_user(connection.id, user_id).access)
            for connection in build_repository(IrisMailboxConnectionRepository).get_shared_for_member(
                user_id, organization["id"])
        ]

    @staticmethod
    def list_members(connection_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Personas con acceso a un buzón. Solo lo ven sus responsables.

        Args:
            connection_id: Buzón.
            user_id: Responsable que consulta.

        Returns:
            List[dict]: Los accesos.

        Raises:
            IrisMailboxConnectionNotFoundError: Si no existe o no es responsable.
        """
        _require_access(connection_id, user_id, require_manager=True)
        return [_describe_member(member) for member in
                build_repository(IrisMailboxMemberRepository).get_by_connection(connection_id)]

    @staticmethod
    def set_member(connection_id: int, user_id: int, member_user_id: int, access: str) -> Dict[str, Any]:
        """Da o cambia el acceso de una persona de la organización a un buzón.

        Args:
            connection_id: Buzón.
            user_id: Responsable que lo decide.
            member_user_id: Persona a la que se da acceso.
            access: ``viewer`` o ``manager``.

        Returns:
            dict: El acceso resultante.

        Raises:
            IrisMailboxConnectionNotFoundError: Si no existe o no es responsable.
            IrisSharedMailboxConflictError: ``member_not_in_organization`` si la
                persona no es de la organización; ``last_manager`` si se
                rebaja al último responsable.
            IrisSharedMailboxLimitError: Si el buzón ya tiene el máximo de personas.
        """
        connection = _require_access(connection_id, user_id, require_manager=True)
        member_organization = OrganizationManager().get_mine(member_user_id)
        if member_organization is None or member_organization.get("id") != connection.organization_id:
            raise IrisSharedMailboxConflictError("member_not_in_organization")
        with UnitOfWork() as uow:
            repo = IrisMailboxMemberRepository(uow)
            member = repo.get_by_connection_and_user(connection_id, member_user_id)
            if member is None:
                maximum = CR.iris_shared_mailboxes_config().max_members_per_mailbox
                if len(repo.get_by_connection(connection_id)) >= maximum:
                    raise IrisSharedMailboxLimitError("members", maximum)
                member = repo.save(IrisMailboxMember(connection_id=connection_id, user_id=member_user_id,
                                                     access=access, granted_by_user_id=user_id,
                                                     granted_at=utcnow_naive()))
            else:
                if (member.access == SharedMailboxAccess.MANAGER.value and access != SharedMailboxAccess.MANAGER.value
                        and repo.count_managers(connection_id) <= 1):
                    raise IrisSharedMailboxConflictError("last_manager")
                member.access = access
                member.granted_by_user_id = user_id
                member.granted_at = utcnow_naive()
                repo.update(member)
            return _describe_member(member)

    @staticmethod
    def remove_member(connection_id: int, user_id: int, member_user_id: int) -> None:
        """Quita el acceso de una persona a un buzón.

        Args:
            connection_id: Buzón.
            user_id: Responsable que lo decide.
            member_user_id: Persona.

        Raises:
            IrisMailboxConnectionNotFoundError: Si no existe o no es responsable.
            IrisSharedMailboxConflictError: ``last_manager`` si es el último responsable.
        """
        _require_access(connection_id, user_id, require_manager=True)
        with UnitOfWork() as uow:
            repo = IrisMailboxMemberRepository(uow)
            member = repo.get_by_connection_and_user(connection_id, member_user_id)
            if member is None:
                return
            if member.access == SharedMailboxAccess.MANAGER.value and repo.count_managers(connection_id) <= 1:
                raise IrisSharedMailboxConflictError("last_manager")
            repo.delete(member)

    @staticmethod
    def list_analyses(connection_id: int, user_id: int, page: int, per_page: int) -> Dict[str, Any]:
        """Análisis de los correos de un buzón compartido.

        Args:
            connection_id: Buzón.
            user_id: Persona con acceso.
            page: Página, desde 1.
            per_page: Tamaño de página.

        Returns:
            dict: ``analyses`` (resumen de cada uno), ``total``, ``page`` y ``perPage``.

        Raises:
            IrisMailboxConnectionNotFoundError: Si no existe o no tiene acceso.
        """
        _require_access(connection_id, user_id)
        items, total = build_repository(IrisAnalysisRepository).get_by_connection_paginated(
            connection_id, page, per_page)
        return {
            "analyses": [{
                "analysisId": analysis.id,
                "title": analysis.title,
                "status": analysis.status,
                "verdict": analysis.verdict,
                "totalScore": analysis.total_score,
                "startedAt": isoformat_utc(analysis.started_at),
                "finishedAt": isoformat_utc(analysis.finished_at),
            } for analysis in items],
            "total": total,
            "page": page,
            "perPage": per_page,
        }

    @staticmethod
    def get_analysis(connection_id: int, analysis_id: int, user_id: int) -> Dict[str, Any]:
        """Informe completo de un análisis de un buzón compartido.

        Args:
            connection_id: Buzón.
            analysis_id: Análisis.
            user_id: Persona con acceso.

        Returns:
            dict: El mismo informe que ``GET /iris/results/<id>``.

        Raises:
            IrisMailboxConnectionNotFoundError: Si no existe o no tiene acceso.
            IrisAnalysisNotFoundError: Si el análisis no es de ese buzón.
        """
        _require_access(connection_id, user_id)
        analysis = build_repository(IrisAnalysisRepository).get_by_id(analysis_id)
        if analysis is None or analysis.connection_id != connection_id:
            raise IrisAnalysisNotFoundError(analysis_id)
        return IrisManager().get_analysis_results(analysis_id)
