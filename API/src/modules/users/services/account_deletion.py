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

**Una lista y un registro.** Las features siguen declaradas aquí, en una lista
que se lee de arriba abajo. Los módulos transversales que conocen sus propias
tablas (hoy ``accounts``) se dan de alta en ``UserDataRegistry`` desde su
``__init__.py``: así ``users`` no escribe SQL sobre tablas ajenas y añadir una
tabla con ``user_id`` a ese módulo no obliga a editar este fichero. El orden de
barrido es el de ``purge_order()``: features, módulos registrados (por
prioridad) y, al final, lo que guarda ``users``.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import func

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import Document
from src.modules.system.taskqueue import ITaskQueue, TaskQueue
from src.modules.users.exceptions import UserBindingError
from src.modules.users.repositories import UserRepository
from src.modules.users.services.user_data import UserDataRegistry

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


def revoke_mailbox_grants(user_id: int) -> int:
    """Retira ante Google y Microsoft el permiso de los buzones conectados del usuario.

    Hay que hacerlo **antes** de borrar las conexiones, porque el token que se
    revoca vive en esa fila. Si un proveedor falla el borrado de la cuenta sigue
    adelante: se anota en el log y el permiso caducará solo o lo retirará el
    usuario desde su cuenta de correo.

    Args:
        user_id: Usuario cuya cuenta se va a borrar.

    Returns:
        int: Cuántos permisos no se pudieron retirar (``0`` si todos fueron bien
            o el usuario no tenía buzones).
    """
    from src.modules.features.iris.managers.mailbox import IrisMailboxManager

    failures = IrisMailboxManager().revoke_all_for_user(user_id)
    if failures:
        logger.warning(
            f"Al borrar la cuenta {user_id}, {failures} permiso(s) de buzón no se pudieron retirar "
            f"ante el proveedor"
        )
    return failures


def _footprint_users(uow: UnitOfWork, user_id: int, footprint: ExternalFootprint) -> None:
    """ZIP de exportaciones de datos todavía sin descargar y sus tareas.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se va a borrar.
        footprint: Acumulador al que se añaden las rutas y los ``external_id``.
    """
    from src.modules.users.managers import DataExportManager
    from src.modules.users.model import DataExport

    for export_id, filename in uow.session.query(DataExport.id, DataExport.filename).filter(
        DataExport.user_id == user_id
    ):
        if filename:
            footprint.file_paths.append(filename)
        footprint.task_external_ids.append(f"{DataExportManager.EXTERNAL_ID_PREFIX}{export_id}")


#: Orden de recogida. Solo lee: no modifica nada de la base de datos.
FOOTPRINTS: list[tuple[str, Callable[[UnitOfWork, int, ExternalFootprint], None]]] = [
    ("documents", _footprint_documents),
    ("themis",    _footprint_themis),
    ("aegis",     _footprint_aegis),
    ("iris",      _footprint_iris),
    ("users",     _footprint_users),
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


def _purge_users(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Desafíos MFA a medias y exportaciones de datos.

    El resto de lo que guarda ``users`` (tokens, atributos, credencial TOTP y
    códigos de recuperación) cuelga de una ``relationship`` con cascada.
    """
    from src.modules.users.model import DataExport, MFAChallenge

    return _delete_by_user(uow, user_id, [MFAChallenge, DataExport])


#: Purgas de las features, en orden. Corren primero; después las de los módulos
#: registrados en ``UserDataRegistry`` y, al final, ``_purge_users``.
PURGES: list[tuple[str, Callable[[UnitOfWork, int], dict[str, int]]]] = [
    ("themis",   _purge_themis),
    ("aegis",    _purge_aegis),
    ("iris",     _purge_iris),
    ("hygeia",   _purge_hygeia),
]


def _ordered_purges() -> list[tuple[str, Callable[[UnitOfWork, int], dict[str, int]]]]:
    """Todas las purgas en el orden en que se ejecutan.

    Returns:
        list[tuple[str, Callable]]: ``(nombre del módulo, purga)``: primero
            ``PURGES``, después los módulos de ``UserDataRegistry`` por
            prioridad y, al final, la de ``users``. La fila de ``User`` se
            borra después de todas.
    """
    registered = [(item.name, item.purge) for item in UserDataRegistry.contributions()]
    return [*PURGES, *registered, ("users", _purge_users)]


def purge_order() -> list[str]:
    """Nombres de los módulos en el orden en que se purgan.

    Returns:
        list[str]: Por ejemplo ``["themis", "aegis", "iris", "hygeia", "accounts",
            "users"]``. Hay un test que lo fija: algunas tablas tienen claves
            ajenas entre sí y cambiar el orden rompe el borrado en Postgres.
    """
    return [name for name, _purge in _ordered_purges()]


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
    """Ejecuta todas las purgas, en el orden de ``purge_order``, y devuelve cuántas filas cayó cada tabla."""
    counts: dict[str, int] = {}
    for module_name, purge in _ordered_purges():
        module_counts = purge(uow, user_id)
        counts.update({key: value for key, value in module_counts.items() if value})
        logger.debug(f"Purga de {module_name} para el usuario {user_id}: {module_counts}")
    uow.session.flush()
    return counts


def cleanup_external_footprint(
    footprint: ExternalFootprint, task_queue: Optional[ITaskQueue] = None
) -> dict[str, int]:
    """Borra los ficheros del usuario y cancela sus tareas de la cola.

    Solo se debe llamar **después** de que el borrado de la cuenta esté
    confirmado en la base de datos: si se hiciera antes y el borrado fallase, la
    cuenta seguiría existiendo sin sus ficheros. Nunca lanza: cada fichero o
    tarea que falla se cuenta y se anota en el log, y el resto sigue.

    Una tarea pendiente se cancela y se elimina de Redis con sus argumentos. Una
    en ejecución recibe la señal de cancelación y sus datos desaparecen cuando
    termina. Una ya terminada no se puede cancelar: su resultado caduca solo por
    el TTL del historial de la cola.

    Args:
        footprint: Lo recogido por ``collect_external_footprint`` antes del borrado.
        task_queue: Cola sobre la que cancelar. Por defecto la del proceso.

    Returns:
        dict[str, int]: ``filesRemoved``, ``tasksCancelled`` y ``failures``
            (ficheros que no se pudieron borrar y consultas a la cola que fallaron).
    """
    result = {"filesRemoved": 0, "tasksCancelled": 0, "failures": 0}

    for file_path in footprint.file_paths:
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                result["filesRemoved"] += 1
        except OSError as error:
            result["failures"] += 1
            logger.warning(f"No se pudo borrar el fichero {file_path} de una cuenta eliminada: {error}")

    try:
        queue = task_queue or TaskQueue.get_instance()
    except Exception as error:
        queue = None
        result["failures"] += len(footprint.task_external_ids)
        logger.warning(f"No se pudo acceder a la cola para cancelar las tareas de una cuenta eliminada: {error}")

    for external_id in footprint.task_external_ids if queue is not None else []:
        try:
            task = queue.get_task_by_external_id(external_id)
            if task is not None and queue.cancel(task.id):
                result["tasksCancelled"] += 1
        except Exception as error:
            result["failures"] += 1
            logger.warning(f"No se pudo cancelar la tarea {external_id} de una cuenta eliminada: {error}")

    return result


def delete_account(user_id: int) -> dict[str, int]:
    """Borra una cuenta entera: permisos de correo, filas, ficheros y tareas.

    Es la única vía de borrado de una cuenta (baja voluntaria y baja por un
    administrador), para que las dos hagan exactamente lo mismo. Orden:

    1. Retira el permiso de cada buzón ante su proveedor.
    2. En una transacción anota los ficheros y tareas, barre las filas y borra el
       usuario, y **confirma** explícitamente: dentro de una petición el commit
       normal ocurre al terminar, y los ficheros no pueden borrarse antes.
    3. Con el borrado ya durable, borra los ficheros y cancela las tareas.

    Args:
        user_id: Usuario a borrar.

    Returns:
        dict[str, int]: Filas borradas por tabla, como ``purge_user_data``.

    Raises:
        UserBindingError: Si el usuario no existe.
    """
    revoke_mailbox_grants(user_id)

    with UnitOfWork() as uow:
        repo = UserRepository(uow)
        user = repo.get_by_id(user_id)
        if user is None:
            raise UserBindingError(username=str(user_id))
        footprint = collect_external_footprint(uow, user_id)
        purged = purge_user_data(uow, user_id)
        repo.delete(user)
        uow.commit()

    outcome = cleanup_external_footprint(footprint)
    logger.info(f"Limpieza externa de la cuenta {user_id}: {outcome}")
    return purged


# =========================================================================
# LO QUE SE LE ENSEÑA AL USUARIO ANTES DE BORRAR
# =========================================================================
#
# El aviso de la interfaz lista, por categorías y con cantidades, lo que se va
# a borrar. No es una lista aparte que mantener a mano: se cuenta sobre los
# mismos modelos que barre ``PURGES``, y un test recorre el grafo real de claves
# ajenas hacia ``User`` para que ninguna tabla nueva se quede sin salir en el
# aviso (o sin declararse expresamente como "no se lista").


def _models_of_deletion_category(key: str) -> list:
    """Modelos cuyas filas cuentan para una categoría del aviso de borrado.

    Los de las features están aquí; los de los módulos registrados en
    ``UserDataRegistry`` (``subscription``, de ``accounts``) los aportan ellos.

    Args:
        key: Clave de la categoría (``DELETION_CATEGORY_KEYS``).

    Returns:
        list: Modelos SQLAlchemy con columna ``user_id``; cada fila suya del
            usuario suma una unidad a la categoría. Vacía si ninguno la declara.
    """
    from src.modules.features.acheron.model import Vault
    from src.modules.features.aegis.model import Campaign, DistributionList
    from src.modules.features.hygeia.model import MonitoredAsset
    from src.modules.features.iris.model import IrisAnalysis, IrisMailboxConnection
    from src.modules.features.themis.model import AuthorizedTarget, OsintScan, ProgramedScan, Scan

    own_models = {
        "scans": [Scan, OsintScan],
        "documents": [Document],
        "scheduledScans": [ProgramedScan],
        "authorizedTargets": [AuthorizedTarget],
        "mailboxes": [IrisMailboxConnection],
        "mailAnalyses": [IrisAnalysis],
        "monitoredAssets": [MonitoredAsset],
        "distributionLists": [DistributionList],
        "campaigns": [Campaign],
        "vaults": [Vault],
    }
    models = list(own_models.get(key, []))
    for contribution in UserDataRegistry.contributions():
        models.extend(contribution.deletion_models.get(key, ()))
    return models


#: Categorías del aviso, en el orden en que se enseñan. La interfaz traduce cada
#: clave en ``profilePage.delete.items.<clave>``.
DELETION_CATEGORY_KEYS: tuple[str, ...] = (
    "scans", "documents", "scheduledScans", "authorizedTargets", "mailboxes",
    "mailAnalyses", "monitoredAssets", "distributionLists", "campaigns", "vaults",
    "subscription", "complianceFrameworks", "complianceEvidence",
)

#: Tablas con clave ajena hacia ``User`` que se borran pero **no** salen como
#: categoría propia, con el motivo. El test del grafo de claves ajenas exige que
#: toda tabla esté en una categoría o aquí: así nadie añade una y se olvida del aviso.
UNLISTED_TABLES: dict[str, str] = {
    "DataExport": "exportaciones de tus datos, con su archivo si aún no lo has descargado",
    "CompanyProfile": "los datos de tu empresa: razón social, NIF, dirección y contacto de seguridad",
    **dict.fromkeys(
        ["EunomiaControlAssessment", "EunomiaAssessmentEvent"],
        "las evaluaciones de tus marcos de cumplimiento y su historial, que se cuentan con el marco",
    ),
    **dict.fromkeys(
        ["EunomiaRecord", "EunomiaRecordEvent"],
        "las fichas de tus registros de cumplimiento (tratamientos, incidentes…) y su historial",
    ),
    "EunomiaTemplateDraft": "los borradores de los documentos de cumplimiento que has ido rellenando",
    **dict.fromkeys(
        ["EunomiaEvidenceLink"],
        "los enlaces entre tus evidencias de cumplimiento y los controles, que caen con cada evidencia",
    ),
    **dict.fromkeys(
        ["AccessToken", "RefreshToken", "MFAChallenge", "MFARecoveryCode", "MFATotpCredential",
         "UserAttribute"],
        "sesión, segundo factor y permisos de la propia cuenta",
    ),
    **dict.fromkeys(
        ["Organization", "OrganizationMember", "OrganizationInvitation"],
        "organización e invitaciones: su disolución se enseña aparte porque afecta a terceros",
    ),
    **dict.fromkeys(
        ["ScanFolder", "Traceroute", "Finding"],
        "carpetas, cachés y marcas que cuelgan de los escaneos",
    ),
    **dict.fromkeys(
        ["AegisOrgProfile", "AssetGroup", "HygeiaTag"],
        "ajustes y etiquetas de Aegis e Hygeia",
    ),
    **dict.fromkeys(
        ["IrisActionAudit", "IrisAnalystFeedback", "IrisBatch", "IrisCampaign", "IrisCase",
         "IrisCaseEvent", "IrisCommunicationEdge", "IrisIntegrationToken", "IrisMailboxMember",
         "IrisNotificationPreference", "IrisSavedView", "IrisTenantConsent", "IrisTenantProfile",
         "IrisTrustedSender", "IrisUrlExpansion", "IrisWebhookSubscription"],
        "ajustes, casos y resultados derivados de los análisis de Iris",
    ),
}


def count_deletion_categories(uow: UnitOfWork, user_id: int) -> list[dict]:
    """Cuenta cuánto de cada categoría se borraría con la cuenta.

    Solo lee. Las categorías sin ninguna fila no se devuelven: un aviso que
    enumera lo que el usuario no tiene solo añade ruido.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        user_id: Usuario cuya cuenta se mostraría borrar.

    Returns:
        list[dict]: ``{"key": str, "count": int}`` por cada categoría con al
            menos una fila, en el orden de ``DELETION_CATEGORY_KEYS``.
    """
    categories = []
    for key in DELETION_CATEGORY_KEYS:
        total = 0
        for model in _models_of_deletion_category(key):
            owner_column = model.user_id if hasattr(model, "user_id") else model.owner_user_id
            total += uow.session.query(func.count()).select_from(model).filter(
                owner_column == user_id
            ).scalar() or 0
        if total:
            categories.append({"key": key, "count": total})
    return categories


def describe_retained_data() -> dict[str, int]:
    """Lo que se conserva tras el borrado de una cuenta, para decírselo al usuario.

    Returns:
        dict[str, int]: ``activityLogDays``, los días que se conserva el
            registro de actividad (con el usuario y la dirección IP de cada
            petición) antes de que se borre solo.
    """
    return {"activityLogDays": CR.logs_config().retention_days}
