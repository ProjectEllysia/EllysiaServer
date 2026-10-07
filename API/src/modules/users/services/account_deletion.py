"""
Borrado de una cuenta y de todo lo que cuelga de ella.

**Por qué existe este fichero.** Veintiséis claves ajenas apuntan a ``User`` y
solo dos tienen ``ON DELETE CASCADE``. De las demás, unas cuantas cuelgan de una
``relationship`` con ``cascade="all, delete-orphan"`` y se van solas al borrar
por el ORM; otras diez no cuelgan de nada, así que un ``DELETE FROM "User"``
falla en Postgres con una violación de clave ajena.

Y no se notaría en los tests: la suite corre sobre SQLite, que **no** aplica
claves ajenas salvo que se active un PRAGMA que el proyecto no activa. Un
barrido incompleto pasaría verde aquí y daría un 500 en producción. Por eso el
barrido es explícito y hay un test que recorre el grafo real de claves ajenas
en vez de fiarse del borrado.

**Por qué una lista y no un registro.** Se puede leer de arriba abajo y saber
exactamente qué se destruye. Un registro donde cada módulo se apunta solo queda
más desacoplado y obliga a ir a cinco ficheros para responder "¿qué borra este
botón?" — que es justo la pregunta que hay que poder responder rápido.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable

from src.modules.infrastructure import UnitOfWork
from src.modules.shared import Document

logger = logging.getLogger(__name__)


# =========================================================================
# LO QUE VIVE FUERA DE LA BASE DE DATOS
# =========================================================================
#
# El barrido de más abajo solo toca filas. Un usuario deja además ficheros en
# disco (los PDF y JSON de sus documentos) y tareas en la cola de Redis, que
# guardan sus argumentos. Hay que anotar qué son **antes** de borrar las filas,
# porque después ya no hay forma de saber a quién pertenecían, y actuar sobre
# ellos solo **después** de que la transacción se confirme: si el borrado de la
# cuenta falla, los ficheros y las tareas de una cuenta que sigue existiendo
# no se pueden haber perdido.


@dataclass
class ExternalFootprint:
    """Lo que un usuario tiene fuera de la base de datos.

    Attributes:
        file_paths: Rutas en disco de los documentos generados para el usuario
            (``Document.filename``), sin duplicados y sin vacíos.
        task_external_ids: ``external_id`` de las tareas de la cola que
            podrían llevar datos del usuario, tanto si siguen pendientes como
            si ya acabaron. Un id que no corresponda a ninguna tarea es
            inofensivo: quien lo use simplemente no la encuentra.
    """

    file_paths: list[str] = field(default_factory=list)
    task_external_ids: list[str] = field(default_factory=list)


def _document_external_prefixes() -> dict[str, str]:
    """Prefijo de ``external_id`` de las tareas de documento, por tipo de documento.

    Returns:
        dict[str, str]: ``Document.document_type`` → prefijo (``"themis"`` →
        ``"themis-doc:"``). Los imports van diferidos por la misma razón que
        en las purgas: users → features cerraría un ciclo al nivel de módulo.
    """
    from src.modules.features.aegis.managers.pills import AegisManager
    from src.modules.features.hygeia.managers import HygeiaDocumentManager
    from src.modules.features.iris.managers.reports import IrisReportManager
    from src.modules.features.themis.managers.reports import ThemisReportManager

    return {
        "themis": ThemisReportManager.EXTERNAL_ID_PREFIX,
        "aegis": AegisManager.EXTERNAL_ID_PREFIX,
        "iris": IrisReportManager.EXTERNAL_ID_PREFIX,
        "hygeia": HygeiaDocumentManager.EXTERNAL_ID_PREFIX,
    }


def _footprint_documents(uow: UnitOfWork, user_id: int, footprint: ExternalFootprint) -> None:
    """Rutas y tareas de los documentos generados (todos los módulos).

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se va a borrar.
        footprint: Acumulador al que se añaden las rutas y los ``external_id``.
    """
    prefixes = _document_external_prefixes()
    rows = uow.session.query(Document.id, Document.document_type, Document.filename).filter(
        Document.user_id == user_id
    )
    for document_id, document_type, filename in rows:
        if filename:
            footprint.file_paths.append(filename)
        prefix = prefixes.get(document_type)
        if prefix:
            footprint.task_external_ids.append(f"{prefix}{document_id}")


def _footprint_themis(uow: UnitOfWork, user_id: int, footprint: ExternalFootprint) -> None:
    """Tareas de escaneos, escaneos pasivos y traceroutes.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se va a borrar.
        footprint: Acumulador al que se añaden los ``external_id``.
    """
    from src.modules.features.themis.managers.lybra.osint import OsintManager
    from src.modules.features.themis.managers.scan import ScanManager
    from src.modules.features.themis.managers.traceroute import TracerouteManager
    from src.modules.features.themis.model import Scan, Traceroute

    session = uow.session
    for (scan_id,) in session.query(Scan.id).filter(Scan.user_id == user_id):
        footprint.task_external_ids.append(f"{ScanManager.EXTERNAL_ID_PREFIX}{scan_id}")
        footprint.task_external_ids.append(f"{OsintManager.EXTERNAL_ID_PREFIX}{scan_id}")
    for (target,) in session.query(Traceroute.target).filter(Traceroute.user_id == user_id):
        footprint.task_external_ids.append(TracerouteManager.external_id_for_target(user_id, target))


def _footprint_aegis(uow: UnitOfWork, user_id: int, footprint: ExternalFootprint) -> None:
    """Tareas de envío de campañas.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se va a borrar.
        footprint: Acumulador al que se añaden los ``external_id``.
    """
    from src.modules.features.aegis.managers.campaigns import CampaignManager
    from src.modules.features.aegis.model import Campaign

    for (campaign_id,) in uow.session.query(Campaign.id).filter(Campaign.user_id == user_id):
        footprint.task_external_ids.append(f"{CampaignManager.EXTERNAL_ID_PREFIX}{campaign_id}")


def _footprint_iris(uow: UnitOfWork, user_id: int, footprint: ExternalFootprint) -> None:
    """Tareas de análisis, resúmenes, avisos y sincronización de buzones.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se va a borrar.
        footprint: Acumulador al que se añaden los ``external_id``.
    """
    from src.modules.features.iris.managers.analysis import IrisManager
    from src.modules.features.iris.managers.mailbox import IrisMailboxManager
    from src.modules.features.iris.managers.mailbox_events import IrisMailboxEventManager
    from src.modules.features.iris.managers.notifications import (
        IrisDigestNotifyManager,
        IrisPhishingNotifyManager,
        IrisReauthNotifyManager,
        IrisStuckSyncNotifyManager,
    )
    from src.modules.features.iris.model import IrisAnalysis, IrisMailboxConnection

    session = uow.session
    for (analysis_id,) in session.query(IrisAnalysis.id).filter(IrisAnalysis.user_id == user_id):
        for prefix in (
            IrisManager.EXTERNAL_ID_PREFIX,
            IrisManager.AI_SUMMARY_EXTERNAL_ID_PREFIX,
            IrisPhishingNotifyManager.EXTERNAL_ID_PREFIX,
        ):
            footprint.task_external_ids.append(f"{prefix}{analysis_id}")

    for (connection_id,) in session.query(IrisMailboxConnection.id).filter(
        IrisMailboxConnection.user_id == user_id
    ):
        for prefix in (
            IrisMailboxManager.EXTERNAL_ID_PREFIX,
            IrisMailboxEventManager.EXTERNAL_ID_PREFIX,
            IrisReauthNotifyManager.EXTERNAL_ID_PREFIX,
            IrisStuckSyncNotifyManager.EXTERNAL_ID_PREFIX,
        ):
            footprint.task_external_ids.append(f"{prefix}{connection_id}")

    footprint.task_external_ids.append(f"{IrisDigestNotifyManager.EXTERNAL_ID_PREFIX}{user_id}")


#: Orden de recogida. Solo lee: no modifica nada de la base de datos.
FOOTPRINTS: list[tuple[str, Callable[[UnitOfWork, int, ExternalFootprint], None]]] = [
    ("documents", _footprint_documents),
    ("themis",    _footprint_themis),
    ("aegis",     _footprint_aegis),
    ("iris",      _footprint_iris),
]


def collect_external_footprint(uow: UnitOfWork, user_id: int) -> ExternalFootprint:
    """Anota los ficheros y las tareas que el usuario tiene fuera de la base de datos.

    Solo lee. Hay que llamarla **antes** de ``purge_user_data``: una vez
    borradas las filas ya no queda registro de qué ficheros y tareas eran suyos.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se va a borrar.

    Returns:
        ExternalFootprint: Rutas y ``external_id`` recogidos, sin duplicados y
        en orden estable.
    """
    footprint = ExternalFootprint()
    for _module_name, collect in FOOTPRINTS:
        collect(uow, user_id, footprint)
    footprint.file_paths = list(dict.fromkeys(footprint.file_paths))
    footprint.task_external_ids = list(dict.fromkeys(footprint.task_external_ids))
    return footprint


# =========================================================================
# PURGAS POR MÓDULO
# =========================================================================
#
# Cada una borra lo que su módulo guarda de un usuario. Los imports van
# diferidos dentro de cada función: estas dependencias apuntan "hacia abajo"
# (users -> features) y al nivel de módulo cerrarían un ciclo.


def _purge_themis(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Escaneos programados, carpetas, objetivos autorizados y traceroutes.

    Los ``Scan`` no van aquí: cuelgan de ``User.scans`` con
    ``cascade="all, delete-orphan"`` y se los lleva el ORM.
    """
    from src.modules.features.themis.model import (
        AuthorizedTarget,
        ProgramedScan,
        ScanFolder,
        Traceroute,
    )

    return _delete_by_user(uow, user_id, [ProgramedScan, ScanFolder, AuthorizedTarget, Traceroute])


def _purge_aegis(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Perfil de organización, listas de distribución y campañas.

    Los destinatarios y las respuestas cuelgan de la lista y de la campaña por
    clave ajena; se borran con ellas.
    """
    from src.modules.features.aegis.model import (
        AegisOrgProfile,
        Campaign,
        CampaignAnswer,
        CampaignRecipient,
        DistributionList,
        Recipient,
    )

    counts: dict[str, int] = {}
    session = uow.session

    campaign_ids = [row[0] for row in session.query(Campaign.id).filter(Campaign.user_id == user_id)]
    list_ids = [
        row[0] for row in session.query(DistributionList.id)
        .filter(DistributionList.user_id == user_id)
    ]

    if campaign_ids:
        # Las respuestas cuelgan del destinatario de la campaña, no de la
        # campaña: hay que bajar dos niveles antes de borrar hacia arriba.
        recipient_ids = [
            row[0] for row in session.query(CampaignRecipient.id)
            .filter(CampaignRecipient.campaign_id.in_(campaign_ids))
        ]
        if recipient_ids:
            counts["CampaignAnswer"] = session.query(CampaignAnswer).filter(
                CampaignAnswer.campaign_recipient_id.in_(recipient_ids)
            ).delete(synchronize_session=False)
        counts["CampaignRecipient"] = session.query(CampaignRecipient).filter(
            CampaignRecipient.campaign_id.in_(campaign_ids)
        ).delete(synchronize_session=False)
    if list_ids:
        counts["Recipient"] = session.query(Recipient).filter(
            Recipient.list_id.in_(list_ids)
        ).delete(synchronize_session=False)

    counts.update(_delete_by_user(uow, user_id, [Campaign, DistributionList, AegisOrgProfile]))
    return counts


def _purge_iris(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Buzones conectados. Los análisis cuelgan de ``User.analyses``."""
    from src.modules.features.iris.model import IrisMailboxConnection

    return _delete_by_user(uow, user_id, [IrisMailboxConnection])


def _purge_hygeia(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Activos monitorizados, con sus muestras y anomalías."""
    from src.modules.features.hygeia.model import Anomaly, AssetSnapshot, MonitoredAsset

    session = uow.session
    asset_ids = [
        row[0] for row in session.query(MonitoredAsset.id)
        .filter(MonitoredAsset.user_id == user_id)
    ]

    counts: dict[str, int] = {}
    if asset_ids:
        counts["Anomaly"] = session.query(Anomaly).filter(
            Anomaly.asset_id.in_(asset_ids)
        ).delete(synchronize_session=False)
        counts["AssetSnapshot"] = session.query(AssetSnapshot).filter(
            AssetSnapshot.asset_id.in_(asset_ids)
        ).delete(synchronize_session=False)

    counts.update(_delete_by_user(uow, user_id, [MonitoredAsset]))
    return counts


def _purge_accounts(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Suscripción, pertenencia y rastro en invitaciones.

    La **organización de la que es dueño se disuelve entera**: sus miembros se
    quedan sin ella. Es lo que hay que avisarle antes de pulsar el botón, y por
    eso ``preview_deletion`` lo cuenta.

    Las referencias de "quién invitó" o "quién asignó el plan" se ponen a NULL
    en vez de borrar la fila: son rastro histórico de otra persona, no datos de
    quien se va.
    """
    from src.modules.accounts.model import (
        Organization,
        OrganizationInvitation,
        OrganizationMember,
        Subscription,
    )

    session = uow.session
    counts: dict[str, int] = {}

    owned = session.query(Organization).filter(Organization.owner_user_id == user_id).one_or_none()
    if owned is not None:
        counts["OrganizationInvitation"] = session.query(OrganizationInvitation).filter(
            OrganizationInvitation.organization_id == owned.id
        ).delete(synchronize_session=False)
        counts["OrganizationMember"] = session.query(OrganizationMember).filter(
            OrganizationMember.organization_id == owned.id
        ).delete(synchronize_session=False)
        session.delete(owned)
        counts["Organization"] = 1

    # Invitaciones que emitió o que crearon su cuenta, en organizaciones ajenas.
    session.query(OrganizationInvitation).filter(
        OrganizationInvitation.created_user_id == user_id
    ).update({"created_user_id": None}, synchronize_session=False)
    session.query(OrganizationInvitation).filter(
        OrganizationInvitation.invited_by_user_id == user_id
    ).delete(synchronize_session=False)

    session.query(OrganizationMember).filter(
        OrganizationMember.invited_by_user_id == user_id
    ).update({"invited_by_user_id": None}, synchronize_session=False)
    session.query(Subscription).filter(
        Subscription.assigned_by_user_id == user_id
    ).update({"assigned_by_user_id": None}, synchronize_session=False)

    counts.update(_delete_by_user(uow, user_id, [OrganizationMember, Subscription]))
    return counts


def _purge_users(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Desafíos MFA a medias.

    El resto de lo que guarda ``users`` (tokens, atributos, credencial TOTP y
    códigos de recuperación) cuelga de una ``relationship`` con cascada.
    """
    from src.modules.users.model import MFAChallenge

    return _delete_by_user(uow, user_id, [MFAChallenge])


#: Orden de barrido. Se ejecuta antes de borrar la fila de ``User``.
PURGES: list[tuple[str, Callable[[UnitOfWork, int], dict[str, int]]]] = [
    ("themis",   _purge_themis),
    ("aegis",    _purge_aegis),
    ("iris",     _purge_iris),
    ("hygeia",   _purge_hygeia),
    ("accounts", _purge_accounts),
    ("users",    _purge_users),
]


def _delete_by_user(uow: UnitOfWork, user_id: int, models: list) -> dict[str, int]:
    """Borra de cada modelo las filas cuyo ``user_id`` sea el dado."""
    counts = {}
    for model in models:
        counts[model.__tablename__] = (
            uow.session.query(model)
            .filter(model.user_id == user_id)
            .delete(synchronize_session=False)
        )
    return counts


def purge_user_data(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Ejecuta todas las purgas y devuelve cuántas filas cayó cada tabla."""
    counts: dict[str, int] = {}
    for module_name, purge in PURGES:
        module_counts = purge(uow, user_id)
        counts.update({key: value for key, value in module_counts.items() if value})
        logger.debug(f"Purga de {module_name} para el usuario {user_id}: {module_counts}")
    uow.session.flush()
    return counts
