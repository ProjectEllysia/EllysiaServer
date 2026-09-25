"""ComplianceManager — qué marcos de cumplimiento ve cada usuario en los informes de Lybra.

Un usuario elige los suyos; si pertenece a una organización y su dueño ha
fijado marcos, esos **sustituyen** a los del usuario. Esta es la única
implementación de esa regla: la usan la pantalla de preferencias y el informe
PDF, y dos implementaciones podrían enseñar en la interfaz unos marcos y
imprimir otros.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.modules.accounts import OrganizationManager
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository

from ..exceptions import ComplianceOrganizationNotOwnedError
from ..lybra import list_compliance_frameworks
from ..model import ComplianceFrameworkSelection
from ..repositories import ComplianceFrameworkSelectionRepository

logger = logging.getLogger(__name__)


def _selection_frameworks(selection: Optional[ComplianceFrameworkSelection]) -> Optional[list[str]]:
    """Las claves de marco de una elección que siguen existiendo en el catálogo.

    Un marco que se retiró del catálogo después de elegirse se ignora en vez de
    romper el informe.

    Args:
        selection: La fila, o ``None`` si no se eligió.

    Returns:
        Optional[list[str]]: ``None`` si no hay elección; si la hay, sus claves
            vigentes (puede ser una lista vacía: «ninguno»).
    """
    if selection is None:
        return None
    known = {framework.key for framework in list_compliance_frameworks()}
    return [key for key in selection.frameworks if key in known]


def _store_selection(repository: ComplianceFrameworkSelectionRepository,
                     selection: Optional[ComplianceFrameworkSelection],
                     frameworks: Optional[list[str]], **owner: int) -> None:
    """Crea, actualiza o borra una elección.

    Args:
        repository: Repositorio dentro de la transacción en curso.
        selection: La fila actual, o ``None`` si no existe.
        frameworks: Las claves nuevas, o ``None`` para borrar la fila.
        **owner: ``user_id=`` u ``organization_id=``, para crear la fila.
    """
    if frameworks is None:
        if selection is not None:
            repository.delete(selection)
        return
    unique = list(dict.fromkeys(frameworks))
    if selection is None:
        repository.save(ComplianceFrameworkSelection(frameworks=unique, **owner))
    else:
        selection.frameworks = unique


class ComplianceManager:
    """Preferencias de marcos de cumplimiento, del usuario y de su organización."""

    def get_preferences(self, user_id: int) -> dict:
        """Todo lo que la pantalla de preferencias necesita para pintarse.

        Args:
            user_id: Usuario que consulta.

        Returns:
            dict: ``frameworks`` (el catálogo: ``[{key, name, shortName}]``), ``mine`` (su
                elección, o ``None`` si no eligió), ``organization`` (la de su
                organización, o ``None`` si no tiene o no la fijó),
                ``effective`` (la que se aplica en sus informes),
                ``isLockedByOrganization`` (``True`` si manda la de la
                organización) y ``canManageOrganization`` (``True`` si es dueño
                de una organización).
        """
        organization = OrganizationManager().get_mine(user_id)
        mine = _selection_frameworks(
            build_repository(ComplianceFrameworkSelectionRepository).get_by_user(user_id))
        organization_frameworks = None
        if organization is not None:
            organization_frameworks = _selection_frameworks(
                build_repository(ComplianceFrameworkSelectionRepository)
                .get_by_organization(organization["id"]))
        return {
            "frameworks": [{"key": framework.key, "name": framework.name, "shortName": framework.short_name}
                           for framework in list_compliance_frameworks()],
            "mine": mine,
            "organization": organization_frameworks,
            "effective": organization_frameworks if organization_frameworks is not None else (mine or []),
            "isLockedByOrganization": organization_frameworks is not None,
            "canManageOrganization": bool(organization and organization["isOwner"]),
        }

    def resolve_effective_frameworks(self, user_id: int) -> list[str]:
        """Los marcos que se aplican en los informes de un usuario.

        Args:
            user_id: Dueño del escaneo del que sale el informe.

        Returns:
            list[str]: Los de su organización si esta los fijó; si no, los
                suyos; si tampoco eligió, una lista vacía (el informe sólo
                enseña MITRE ATT&CK).
        """
        return self.get_preferences(user_id)["effective"]

    def set_user_frameworks(self, user_id: int, frameworks: Optional[list[str]]) -> dict:
        """Guarda los marcos que elige un usuario.

        Se guardan aunque su organización imponga otros: si la organización deja
        de fijarlos, vuelven a aplicarse los suyos.

        Args:
            user_id: Usuario que elige.
            frameworks: Claves del catálogo (las valida el schema del endpoint),
                o ``None`` para dejar de elegir.

        Returns:
            dict: Las preferencias ya actualizadas, como ``get_preferences``.
        """
        with UnitOfWork() as uow:
            repository = ComplianceFrameworkSelectionRepository(uow)
            _store_selection(repository, repository.get_by_user(user_id), frameworks, user_id=user_id)
        logger.info("Marcos de cumplimiento del usuario %s: %s", user_id, frameworks)
        return self.get_preferences(user_id)

    def set_organization_frameworks(self, user_id: int, frameworks: Optional[list[str]]) -> dict:
        """Fija los marcos que se imponen a todos los miembros de la organización.

        Args:
            user_id: Quien lo pide; tiene que ser el dueño de su organización.
            frameworks: Claves del catálogo (las valida el schema del endpoint),
                o ``None`` para dejar de imponerlos y que cada miembro use los suyos.

        Returns:
            dict: Las preferencias del dueño ya actualizadas, como ``get_preferences``.

        Raises:
            ComplianceOrganizationNotOwnedError: Si no tiene organización o no es su dueño.
        """
        organization = OrganizationManager().get_mine(user_id)
        if organization is None or not organization["isOwner"]:
            raise ComplianceOrganizationNotOwnedError()
        with UnitOfWork() as uow:
            repository = ComplianceFrameworkSelectionRepository(uow)
            _store_selection(repository, repository.get_by_organization(organization["id"]), frameworks,
                        organization_id=organization["id"])
        logger.info("Marcos de cumplimiento de la organización %s: %s", organization["id"], frameworks)
        return self.get_preferences(user_id)
