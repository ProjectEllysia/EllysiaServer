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
    FrameworkAlreadyAdoptedError,
    FrameworkArchivedError,
    FrameworkNotFoundError,
)
from ..model import ADOPTION_ACTIVE, ADOPTION_ARCHIVED, EunomiaFrameworkAdoption
from ..repositories import EunomiaFrameworkAdoptionRepository
from ..services.catalog import load_index

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
            })
        return {"adoptions": adoptions, "ownership": organizations.describe_data_ownership(user_id)}

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
        return next(
            adoption for adoption in self.list_adoptions(owner_user_id)["adoptions"]
            if adoption["frameworkKey"] == framework_key
        )
