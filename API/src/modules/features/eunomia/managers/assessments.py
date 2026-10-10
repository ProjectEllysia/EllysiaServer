"""
EunomiaAssessmentManager — evaluar los controles de un marco adoptado.

Los miembros de una organización evalúan sobre las filas del dueño efectivo. Cada control se
valida contra la versión del catálogo que la adopción fijó, nunca contra la vigente.
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from src.modules.accounts import OrganizationManager
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive
from src.modules.users import UserManager

from ..exceptions import (
    AdoptionNotFoundError,
    AssessmentConflictError,
    ControlNotAssessableError,
    ControlNotFoundError,
    JustificationRequiredError,
    ResponsibleNotInOrganizationError,
)
from ..model import (
    ADOPTION_ACTIVE,
    ASSESSMENT_STATUSES,
    STATUS_NOT_APPLICABLE,
    EunomiaControlAssessment,
)
from ..repositories import EunomiaControlAssessmentRepository, EunomiaFrameworkAdoptionRepository
from ..services.catalog import CatalogNode, FrameworkVersion, load_version

logger = logging.getLogger(__name__)


def _display_name(user_id: Optional[int]) -> Optional[str]:
    """Nombre visible de un usuario: nombre completo o, si no tiene, su usuario."""
    if user_id is None:
        return None
    user = UserManager().get_user_by_id(user_id)
    if user is None:
        return None
    return f"{user.first_name} {user.last_name}".strip() or user.username


def assessment_payload(row: Optional[EunomiaControlAssessment], framework_key: str, identifier: str) -> dict:
    """Serializa una evaluación; sin fila, la de un control «pendiente».

    Args:
        row: La fila, o ``None`` si el control no se ha evaluado nunca.
        framework_key: Clave del marco.
        identifier: Identificador del control.

    Returns:
        dict: ``code``, ``controlIdentifier``, ``status``, ``justification``, ``notes``,
            ``responsibleUserId``, ``responsibleName``, ``dueDate``, ``updatedAt`` (el testigo
            de concurrencia: ``None`` si no hay fila), ``updatedByUserId`` y ``updatedByName``.
    """
    return {
        "code": f"{framework_key}:{identifier}",
        "controlIdentifier": identifier,
        "status": row.status if row else "pending",
        "justification": (row.justification or "") if row else "",
        "notes": (row.notes or "") if row else "",
        "responsibleUserId": row.responsible_user_id if row else None,
        "responsibleName": _display_name(row.responsible_user_id) if row else None,
        "dueDate": row.due_date if row else None,
        "updatedAt": row.updated_at if row else None,
        "updatedByUserId": row.updated_by_user_id if row else None,
        "updatedByName": _display_name(row.updated_by_user_id) if row else None,
    }


def _adopted_version(owner_user_id: int, framework_key: str) -> FrameworkVersion:
    """La versión del catálogo que el dueño tiene adoptada y activa para un marco.

    Raises:
        AdoptionNotFoundError: Si no tiene el marco adoptado y activo (404).
    """
    adoption = build_repository(EunomiaFrameworkAdoptionRepository).get_for_owner(owner_user_id, framework_key)
    if adoption is None or adoption.status != ADOPTION_ACTIVE:
        raise AdoptionNotFoundError(framework_key)
    version = load_version(framework_key, adoption.catalog_version)
    if version is None:
        raise AdoptionNotFoundError(framework_key)
    return version


def _assessable_node(version: FrameworkVersion, framework_key: str, identifier: str) -> CatalogNode:
    """El nodo evaluable de una versión, o el error que corresponda."""
    node = version.node(f"{framework_key}:{identifier}")
    if node is None:
        raise ControlNotFoundError(identifier)
    if not node.is_assessable:
        raise ControlNotAssessableError(identifier)
    return node


def _conflict_payload(row: Optional[EunomiaControlAssessment], framework_key: str, identifier: str) -> dict:
    """Lo que hay ahora en la fila, con las fechas ya en texto, para devolverlo en un conflicto."""
    payload = assessment_payload(row, framework_key, identifier)
    for key in ("dueDate", "updatedAt"):
        if isinstance(payload[key], (date, datetime)):
            payload[key] = payload[key].isoformat()
    return payload


class EunomiaAssessmentManager:
    """Evaluación de controles de los marcos adoptados."""

    def set_assessment(self, user_id: int, framework_key: str, identifier: str, data: dict) -> dict:
        """Guarda la evaluación de un control.

        Args:
            user_id: Usuario que evalúa: el dueño efectivo o un miembro de su organización.
            framework_key: Clave del marco adoptado.
            identifier: Identificador del control en la versión adoptada.
            data: ``status``, ``justification``, ``notes``, ``responsibleUserId``, ``dueDate`` y
                ``updatedAt`` (el valor que vio el cliente, o ``None`` si no había fila).

        Returns:
            dict: La evaluación guardada, con la forma de ``assessment_payload``.

        Raises:
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
            ControlNotFoundError: Si el control no existe en la versión adoptada (404).
            ControlNotAssessableError: Si el nodo es un grupo (400).
            JustificationRequiredError: Si es «no aplica» sin justificar (400).
            ResponsibleNotInOrganizationError: Si el responsable es ajeno (400).
            AssessmentConflictError: Si alguien cambió el control desde que el cliente lo leyó (409).
        """
        organizations = OrganizationManager()
        owner_user_id = organizations.resolve_data_owner(user_id)
        version = _adopted_version(owner_user_id, framework_key)
        _assessable_node(version, framework_key, identifier)

        status = data["status"]
        justification = (data.get("justification") or "").strip()
        if status == STATUS_NOT_APPLICABLE and not justification:
            raise JustificationRequiredError()
        responsible = data.get("responsibleUserId")
        if responsible is not None and responsible != owner_user_id \
                and not organizations.is_owner_of_member(owner_user_id, responsible):
            raise ResponsibleNotInOrganizationError()

        expected: Optional[datetime] = data.get("updatedAt")
        if expected is not None and expected.tzinfo is not None:
            # La columna es naive-UTC; el cliente devuelve el testigo con su zona.
            expected = expected.astimezone(timezone.utc).replace(tzinfo=None)
        fields = {
            "status": status,
            "justification": justification or None,
            "notes": (data.get("notes") or "").strip() or None,
            "responsible_user_id": responsible,
            "due_date": data.get("dueDate"),
            "updated_at": utcnow_naive(),
            "updated_by_user_id": user_id,
        }
        with UnitOfWork() as uow:
            repo = EunomiaControlAssessmentRepository(uow)
            row = repo.get_for_control(owner_user_id, framework_key, identifier)
            if (row.updated_at if row else None) != expected:
                raise AssessmentConflictError(_conflict_payload(row, framework_key, identifier))
            if row is None:
                row = EunomiaControlAssessment(
                    owner_user_id=owner_user_id, framework_key=framework_key,
                    catalog_version=version.version, control_identifier=identifier, **fields,
                )
                repo.save(row)
            else:
                if not repo.update_if_unchanged(row.id, expected, **fields):
                    raise AssessmentConflictError(None)
                uow.session.refresh(row)
        logger.info("Control evaluado | owner=%s %s:%s estado=%s", owner_user_id, framework_key, identifier, status)
        return assessment_payload(row, framework_key, identifier)
