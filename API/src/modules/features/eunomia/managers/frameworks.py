"""
EunomiaFrameworkManager — qué marcos tiene adoptados el dueño efectivo de los datos.

Adoptar es fijar una versión del catálogo. Lo hace el dueño efectivo (el propio usuario o el
dueño de su organización) y los miembros lo ven. Las cuotas se cuentan sobre el dueño.
"""

import logging
from datetime import timedelta
from typing import Optional

import src.modules.system.config_reading as CR
from src.modules.accounts import (
    DataOwnedByOrganizationError,
    LimitKey,
    OrganizationManager,
    QuotaManager,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive

from ..exceptions import (
    AdoptionNotFoundError,
    FrameworkAlreadyAdoptedError,
    FrameworkArchivedError,
    FrameworkNotArchivedError,
    FrameworkNotFoundError,
    FrameworkRestoreExpiredError,
    FrameworkUpToDateError,
    VersionMappingMissingError,
)
from ..model import (
    ADOPTION_ACTIVE,
    ADOPTION_ARCHIVED,
    STATUS_PENDING,
    EunomiaControlAssessment,
    EunomiaEvidenceLink,
    EunomiaFrameworkAdoption,
)
from ..repositories import (
    EunomiaControlAssessmentRepository,
    EunomiaEvidenceLinkRepository,
    EunomiaFrameworkAdoptionRepository,
)
from ..services.adoption_data import AdoptionDataRegistry
from .assessments import adoption_progress
from ..services.catalog import FrameworkVersion, load_index, load_version
from ..services.upgrade_plan import UpgradePlan, plan_upgrade
from ..services.version_mappings import load_mapping

logger = logging.getLogger(__name__)


def _framework_entry(framework_key: str) -> dict:
    """La entrada del índice del catálogo de un marco, o ``FrameworkNotFoundError``."""
    for framework in load_index()["frameworks"]:
        if framework["key"] == framework_key:
            return framework
    raise FrameworkNotFoundError(framework_key)


def _assert_owner(user_id: int) -> int:
    """Comprueba que el usuario es el dueño efectivo de sus datos y lo devuelve.

    Raises:
        DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
    """
    organizations = OrganizationManager()
    owner_user_id = organizations.resolve_data_owner(user_id)
    if owner_user_id != user_id:
        raise DataOwnedByOrganizationError(organizations.describe_data_ownership(user_id)["organizationName"] or "")
    return owner_user_id


def _get_active(owner_user_id: int, framework_key: str) -> EunomiaFrameworkAdoption:
    """Devuelve la adopción activa de un marco o lanza ``AdoptionNotFoundError``."""
    adoption = build_repository(EunomiaFrameworkAdoptionRepository).get_for_owner(owner_user_id, framework_key)
    if adoption is None or adoption.status != ADOPTION_ACTIVE:
        raise AdoptionNotFoundError(framework_key)
    return adoption


def _upgrade_context(owner_user_id: int, framework_key: str):
    """Reúne lo necesario para planificar el cambio de versión de un marco adoptado.

    Args:
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.

    Returns:
        tuple: ``(adopción, versión adoptada, versión vigente, plan, evaluaciones, enlaces)``.

    Raises:
        AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
        FrameworkUpToDateError: Si la adopción ya está en la versión vigente (409).
        VersionMappingMissingError: Si no hay correspondencias para ese par de versiones (409).
    """
    adoption = _get_active(owner_user_id, framework_key)
    current = _framework_entry(framework_key)["current"]
    if adoption.catalog_version == current:
        raise FrameworkUpToDateError(framework_key)
    mapping = load_mapping(framework_key, adoption.catalog_version, current)
    if mapping is None:
        raise VersionMappingMissingError(framework_key, adoption.catalog_version, current)
    assessments = build_repository(EunomiaControlAssessmentRepository).list_for_framework(
        owner_user_id, framework_key)
    links = build_repository(EunomiaEvidenceLinkRepository).list_for_framework(owner_user_id, framework_key)
    statuses = {row.control_identifier: row.status for row in assessments if row.status != STATUS_PENDING}
    plan = plan_upgrade(mapping, statuses, {link.control_identifier for link in links})
    return (adoption, load_version(framework_key, adoption.catalog_version),
            load_version(framework_key, current), plan, assessments, links)


def _title(version: FrameworkVersion, identifier: str) -> str:
    """El título de un control de una versión, o su identificador si no se encuentra."""
    node = version.node(f"{version.key}:{identifier}")
    return node.title if node else identifier


def _describe_plan(source: FrameworkVersion, target: FrameworkVersion, plan: UpgradePlan) -> dict:
    """Da al plan la forma que ve el usuario: con títulos y cifras."""
    return {
        "fromVersion": source.version,
        "toVersion": target.version,
        "moves": [{
            "identifier": move.target, "title": _title(target, move.target),
            "sources": list(move.sources), "status": move.status,
            "reason": move.reason, "needsReview": move.needs_review,
        } for move in plan.moves],
        "lost": [{"identifier": identifier, "title": _title(source, identifier), "status": status}
                 for identifier, status in plan.lost],
        "newControls": [{"identifier": identifier, "title": _title(target, identifier)}
                        for identifier in plan.new_controls],
        "linksMoved": len(plan.link_moves),
    }


def _listed(owner_user_id: int, framework_key: str) -> dict:
    """Devuelve una adopción con la forma de ``EunomiaFrameworkManager.list_adoptions``."""
    adoptions = EunomiaFrameworkManager().list_adoptions(owner_user_id)["adoptions"]
    return next(adoption for adoption in adoptions if adoption["frameworkKey"] == framework_key)


class EunomiaFrameworkManager:
    """Adopción, consulta, archivado y restauración de marcos."""

    def list_adoptions(self, user_id: int) -> dict:
        """Devuelve los marcos del dueño efectivo, con su versión y si hay una más nueva.

        Args:
            user_id: Usuario que pregunta, sea dueño o miembro (ve los del dueño).

        Returns:
            dict: ``{"adoptions": [...], "ownership": {...}}``. Cada adopción lleva
                ``frameworkKey``, ``name``, ``shortName``, ``catalogVersion``,
                ``currentVersion``, ``hasNewerVersion``, ``status``, ``adoptedAt``,
                ``adoptedByUserId``, ``archivedAt`` y ``purgeAt`` (cuándo se purgará un marco
                archivado). ``ownership`` es ``describe_data_ownership`` y dice si el usuario
                puede gestionarlos.
        """
        organizations = OrganizationManager()
        owner_user_id = organizations.resolve_data_owner(user_id)
        rows = build_repository(EunomiaFrameworkAdoptionRepository).list_for_owner(owner_user_id)
        index = {framework["key"]: framework for framework in load_index()["frameworks"]}
        retention = timedelta(days=CR.eunomia_config().archived_framework_retention_days)
        adoptions = []
        for row in rows:
            entry = index.get(row.framework_key)
            adoptions.append({
                "frameworkKey": row.framework_key,
                "name": entry["name"] if entry else row.framework_key,
                "shortName": entry["shortName"] if entry else row.framework_key,
                "catalogVersion": row.catalog_version,
                "currentVersion": entry["current"] if entry else row.catalog_version,
                "hasNewerVersion": bool(entry and entry["current"] != row.catalog_version),
                "status": row.status,
                "adoptedAt": row.adopted_at,
                "adoptedByUserId": row.adopted_by_user_id,
                "archivedAt": row.archived_at,
                "purgeAt": row.archived_at + retention if row.archived_at else None,
                "progress": (adoption_progress(owner_user_id, row.framework_key, row.catalog_version)
                             if row.status == ADOPTION_ACTIVE else None),
            })
        return {"adoptions": adoptions, "ownership": organizations.describe_data_ownership(user_id)}

    def active_framework_keys(self, user_id: int) -> list[str]:
        """Devuelve las claves de los marcos activos del dueño efectivo de los datos.

        Es lo que usan los módulos que traducen su trabajo a los marcos que el usuario ha
        elegido (los informes de Lybra): un miembro obtiene los del dueño de su organización.

        Args:
            user_id: Usuario que pregunta, sea dueño, miembro o sin organización.

        Returns:
            list[str]: Claves de marco (``"nis2"``) de las adopciones activas, en el orden en
                que se adoptaron. Vacía si no ha adoptado ninguno.
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        rows = build_repository(EunomiaFrameworkAdoptionRepository).list_for_owner(owner_user_id)
        return [row.framework_key for row in rows if row.status == ADOPTION_ACTIVE]

    def adopt(self, user_id: int, framework_key: str) -> dict:
        """Adopta un marco fijando la versión vigente del catálogo.

        Args:
            user_id: Usuario que adopta; tiene que ser el dueño efectivo de los datos.
            framework_key: Clave del marco (``"nis2"``).

        Returns:
            dict: La adopción creada, con la forma de un elemento de ``list_adoptions``.

        Raises:
            DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
            FrameworkNotFoundError: Si el catálogo no tiene ese marco (404).
            FrameworkAlreadyAdoptedError: Si ya lo tiene activo (409).
            FrameworkArchivedError: Si lo tiene archivado y puede restaurarlo (409).
            QuotaExceededError: Si supera ``eunomia.frameworks`` de su plan (402).
        """
        owner_user_id = _assert_owner(user_id)
        entry = _framework_entry(framework_key)

        existing = build_repository(EunomiaFrameworkAdoptionRepository).get_for_owner(owner_user_id, framework_key)
        if existing is not None:
            if existing.status == ADOPTION_ACTIVE:
                raise FrameworkAlreadyAdoptedError(framework_key)
            raise FrameworkArchivedError(framework_key)

        QuotaManager().consume(owner_user_id, LimitKey.EUNOMIA_FRAMEWORKS)
        with UnitOfWork() as uow:
            EunomiaFrameworkAdoptionRepository(uow).save(EunomiaFrameworkAdoption(
                owner_user_id=owner_user_id, framework_key=framework_key,
                catalog_version=entry["current"], status=ADOPTION_ACTIVE,
                adopted_at=utcnow_naive(), adopted_by_user_id=user_id,
            ))
        logger.info("Marco adoptado | owner=%s marco=%s version=%s", owner_user_id, framework_key, entry["current"])
        return _listed(owner_user_id, framework_key)

    def removal_preview(self, user_id: int, framework_key: str) -> dict:
        """Dice qué se perdería al quitar un marco, antes de quitarlo.

        Args:
            user_id: Usuario que va a quitarlo; tiene que ser el dueño efectivo.
            framework_key: Clave del marco.

        Returns:
            dict: ``assessments`` (evaluaciones con estado distinto de «pendiente»),
                ``evidenceDeleted`` (evidencias que se borrarían), ``evidenceKept`` (las que
                se conservan porque también sirven a otro marco adoptado), ``purgeAt`` (cuándo
                se purgaría) y ``retentionDays``.

        Raises:
            DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
            AdoptionNotFoundError: Si no tiene adoptado ese marco (404).
        """
        owner_user_id = _assert_owner(user_id)
        _get_active(owner_user_id, framework_key)
        retention_days = CR.eunomia_config().archived_framework_retention_days
        with UnitOfWork() as uow:
            totals = AdoptionDataRegistry.count_all(uow, owner_user_id, framework_key)
        return {
            **totals,
            "retentionDays": retention_days,
            "purgeAt": utcnow_naive() + timedelta(days=retention_days),
        }

    def upgrade_preview(self, user_id: int, framework_key: str) -> dict:
        """Dice qué pasaría con la evaluación al pasar un marco a la versión vigente.

        No cambia nada: lo que se traslada tal cual, lo que llega a revisión (controles que se
        dividieron o fusionaron), lo que se pierde (controles retirados) y lo nuevo.

        Args:
            user_id: Usuario que consulta; tiene que ser el dueño efectivo.
            framework_key: Clave del marco.

        Returns:
            dict: ``fromVersion``, ``toVersion``, ``moves``, ``lost``, ``newControls`` y
                ``linksMoved``.

        Raises:
            DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
            FrameworkUpToDateError: Si ya está en la versión vigente (409).
            VersionMappingMissingError: Si no hay correspondencias entre las versiones (409).
        """
        owner_user_id = _assert_owner(user_id)
        _, source, target, plan, _, _ = _upgrade_context(owner_user_id, framework_key)
        return _describe_plan(source, target, plan)

    def upgrade(self, user_id: int, framework_key: str) -> dict:
        """Pasa un marco a la versión vigente trasladando evaluaciones y enlaces de evidencias.

        Los controles que se dividieron o fusionaron llegan marcados en sus notas para que se
        revisen; los retirados se pierden (su historial se conserva); los nuevos quedan
        pendientes. Las evidencias no se tocan: solo cambia a qué controles apuntan.

        Args:
            user_id: Usuario que lo hace; tiene que ser el dueño efectivo.
            framework_key: Clave del marco.

        Returns:
            dict: El mismo resumen que ``upgrade_preview``.

        Raises:
            DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
            FrameworkUpToDateError: Si ya está en la versión vigente (409).
            VersionMappingMissingError: Si no hay correspondencias entre las versiones (409).
        """
        owner_user_id = _assert_owner(user_id)
        adoption, source, target, plan, assessments, links = _upgrade_context(owner_user_id, framework_key)
        now = utcnow_naive()
        by_source = {row.control_identifier: row for row in assessments}
        with UnitOfWork() as uow:
            assessment_repo = EunomiaControlAssessmentRepository(uow)
            link_repo = EunomiaEvidenceLinkRepository(uow)
            assessment_repo.delete_for_framework(owner_user_id, framework_key)
            # El borrado masivo no avisa a la sesión: se sueltan los objetos ya cargados para que
            # las filas nuevas, que pueden reutilizar clave, no choquen con ellos.
            for stale in (*assessments, *links):
                if stale in uow.session:
                    uow.session.expunge(stale)
            for move in plan.moves:
                origin = by_source[move.sources[0]]
                note = origin.notes or ""
                if move.needs_review:
                    origin_codes = ", ".join(move.sources)
                    note = f"Revisar tras el cambio de versión (procede de {origin_codes}). {note}".strip()
                assessment_repo.save(EunomiaControlAssessment(
                    owner_user_id=owner_user_id, framework_key=framework_key,
                    catalog_version=target.version, control_identifier=move.target,
                    status=move.status, justification=origin.justification, notes=note or None,
                    responsible_user_id=origin.responsible_user_id, due_date=origin.due_date,
                    updated_at=now, updated_by_user_id=user_id,
                ))
            link_repo.delete_for_framework(owner_user_id, framework_key)
            for evidence_id, destination in sorted({
                (link.evidence_id, to) for link in links
                for origin, to in plan.link_moves if origin == link.control_identifier
            }):
                link_repo.save(EunomiaEvidenceLink(
                    evidence_id=evidence_id, framework_key=framework_key,
                    control_identifier=destination, linked_at=now, linked_by_user_id=user_id,
                ))
            adoption_repo = EunomiaFrameworkAdoptionRepository(uow)
            stored = adoption_repo.get_for_owner(owner_user_id, framework_key)
            stored.catalog_version = target.version
            adoption_repo.save(stored)
        logger.info("Marco actualizado | owner=%s marco=%s %s -> %s", owner_user_id, framework_key,
                    source.version, target.version)
        return _describe_plan(source, target, plan)

    def archive(self, user_id: int, framework_key: str) -> dict:
        """Quita un marco: lo archiva, sin borrar nada, hasta que pase el plazo.

        Un marco archivado no aparece en el árbol ni cuenta para la cuota.

        Args:
            user_id: Usuario que lo quita; tiene que ser el dueño efectivo.
            framework_key: Clave del marco.

        Returns:
            dict: La adopción ya archivada, con ``purgeAt``.

        Raises:
            DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
            AdoptionNotFoundError: Si no la tiene adoptada y activa (404).
        """
        owner_user_id = _assert_owner(user_id)
        with UnitOfWork() as uow:
            repo = EunomiaFrameworkAdoptionRepository(uow)
            adoption = repo.get_for_owner(owner_user_id, framework_key)
            if adoption is None or adoption.status != ADOPTION_ACTIVE:
                raise AdoptionNotFoundError(framework_key)
            adoption.status = ADOPTION_ARCHIVED
            adoption.archived_at = utcnow_naive()
            adoption.archived_by_user_id = user_id
            repo.save(adoption)
        logger.info("Marco archivado | owner=%s marco=%s", owner_user_id, framework_key)
        return _listed(owner_user_id, framework_key)

    def restore(self, user_id: int, framework_key: str) -> dict:
        """Reactiva un marco archivado si sigue en plazo y hay cuota.

        Args:
            user_id: Usuario que lo restaura; tiene que ser el dueño efectivo.
            framework_key: Clave del marco.

        Returns:
            dict: La adopción reactivada, con su evaluación intacta.

        Raises:
            DataOwnedByOrganizationError: Si es miembro de la organización de otro (403).
            AdoptionNotFoundError: Si no tiene ese marco (404).
            FrameworkNotArchivedError: Si no está archivado (409).
            FrameworkRestoreExpiredError: Si ya pasó el plazo de recuperación (409).
            QuotaExceededError: Si no hay cuota para otro marco activo (402).
        """
        owner_user_id = _assert_owner(user_id)
        existing = build_repository(EunomiaFrameworkAdoptionRepository).get_for_owner(owner_user_id, framework_key)
        if existing is None:
            raise AdoptionNotFoundError(framework_key)
        if existing.status != ADOPTION_ARCHIVED:
            raise FrameworkNotArchivedError(framework_key)
        retention = timedelta(days=CR.eunomia_config().archived_framework_retention_days)
        if existing.archived_at is not None and existing.archived_at + retention < utcnow_naive():
            raise FrameworkRestoreExpiredError(framework_key)

        QuotaManager().consume(owner_user_id, LimitKey.EUNOMIA_FRAMEWORKS)
        with UnitOfWork() as uow:
            repo = EunomiaFrameworkAdoptionRepository(uow)
            adoption = repo.get_for_owner(owner_user_id, framework_key)
            adoption.status = ADOPTION_ACTIVE
            adoption.archived_at = None
            adoption.archived_by_user_id = None
            repo.save(adoption)
        logger.info("Marco restaurado | owner=%s marco=%s", owner_user_id, framework_key)
        return _listed(owner_user_id, framework_key)

    def purge_expired(self) -> int:
        """Borra definitivamente los marcos archivados hace más de la retención.

        Quita de cada uno sus evaluaciones, su historial y las evidencias que solo
        enlazaban con ese marco (lo registran los proveedores de ``AdoptionDataRegistry``),
        y la propia adopción. Lo llama el scheduler una vez al día.

        Returns:
            int: Cuántos marcos se purgaron.
        """
        retention = timedelta(days=CR.eunomia_config().archived_framework_retention_days)
        cutoff = utcnow_naive() - retention
        purged = 0
        with UnitOfWork() as uow:
            repo = EunomiaFrameworkAdoptionRepository(uow)
            for adoption in repo.list_archived_before(cutoff):
                deleted = AdoptionDataRegistry.purge_all(uow, adoption.owner_user_id, adoption.framework_key)
                repo.delete(adoption)
                purged += 1
                logger.info("Marco purgado | owner=%s marco=%s borrado=%s",
                            adoption.owner_user_id, adoption.framework_key, deleted)
        return purged
