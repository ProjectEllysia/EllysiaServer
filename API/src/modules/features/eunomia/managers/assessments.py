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
    STATUS_NOT_APPLICABLE,
    EunomiaAssessmentEvent,
    EunomiaControlAssessment,
)
from ..repositories import (
    EunomiaAssessmentEventRepository,
    EunomiaControlAssessmentRepository,
    EunomiaEvidenceLinkRepository,
    EunomiaEvidenceRepository,
    EunomiaFrameworkAdoptionRepository,
)
from ..services.assessments import ControlState, branch_progress, summarize
from ..services.catalog import CatalogNode, FrameworkVersion, load_version

logger = logging.getLogger(__name__)


def display_name(user_id: Optional[int]) -> Optional[str]:
    """Nombre visible de un usuario: nombre completo o, si no tiene, su usuario."""
    if user_id is None:
        return None
    user = UserManager().get_user_by_id(user_id)
    if user is None:
        return None
    return f"{user.first_name} {user.last_name}".strip() or user.username


def _name(user_id: Optional[int], names: Optional[dict[int, Optional[str]]]) -> Optional[str]:
    """El nombre de un usuario, de la caché si la hay."""
    if names is not None and user_id in names:
        return names[user_id]
    return display_name(user_id)


def assessment_payload(row: Optional[EunomiaControlAssessment], framework_key: str, identifier: str,
                       names: Optional[dict[int, Optional[str]]] = None) -> dict:
    """Serializa una evaluación; sin fila, la de un control «pendiente».

    Args:
        row: La fila, o ``None`` si el control no se ha evaluado nunca.
        framework_key: Clave del marco.
        identifier: Identificador del control.
        names: Nombres ya resueltos por id de usuario, para no consultarlos de uno en uno al
            serializar muchas evaluaciones. Por defecto se consultan.

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
        "responsibleName": _name(row.responsible_user_id, names) if row else None,
        "dueDate": row.due_date if row else None,
        "updatedAt": row.updated_at if row else None,
        "updatedByUserId": row.updated_by_user_id if row else None,
        "updatedByName": _name(row.updated_by_user_id, names) if row else None,
    }


def adopted_version(owner_user_id: int, framework_key: str) -> FrameworkVersion:
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


def assessable_node(version: FrameworkVersion, framework_key: str, identifier: str) -> CatalogNode:
    """El nodo evaluable de una versión, o el error que corresponda."""
    node = version.node(f"{framework_key}:{identifier}")
    if node is None:
        raise ControlNotFoundError(identifier)
    if not node.is_assessable:
        raise ControlNotAssessableError(identifier)
    return node


def _people(user_id: int, owner_user_id: int) -> list[dict]:
    """Las personas a las que se puede asignar un control, tal como las ve quien pregunta.

    El dueño ve a su gente; un miembro solo se ve a sí mismo y al dueño, igual que en el resto
    de la plataforma, donde los miembros no se ven entre ellos.
    """
    organizations = OrganizationManager()
    people = [{"userId": owner_user_id, "name": display_name(owner_user_id) or ""}]
    if user_id != owner_user_id:
        people.append({"userId": user_id, "name": display_name(user_id) or ""})
        return people
    summary = organizations.get_owned_summary(owner_user_id)
    if summary is not None:
        for member in organizations.list_members(summary["id"], owner_user_id):
            if member["userId"] != owner_user_id:
                people.append({"userId": member["userId"], "name": member["fullName"] or member["username"]})
    return people


def _states(records: list) -> dict[str, ControlState]:
    """Pasa las filas de evaluación al estado que necesita el cálculo."""
    return {
        row.control_identifier: ControlState(row.status, row.due_date, row.responsible_user_id)
        for row in records
    }


def _tree_node(version: FrameworkVersion, node: CatalogNode, rows: dict, names: dict, progress: dict,
               evidence: dict) -> dict:
    """Serializa un nodo con sus hijos y, si es evaluable, su evaluación."""
    return {
        "code": node.code,
        "identifier": node.identifier,
        "kind": node.kind,
        "isAssessable": node.is_assessable,
        "title": node.title,
        "officialText": node.official_text,
        "description": node.description,
        "actions": list(node.actions),
        "evidence": list(node.evidence),
        "source": node.source,
        "assessment": (
            assessment_payload(rows.get(node.identifier), node.framework, node.identifier, names)
            if node.is_assessable else None
        ),
        "progress": progress[node.code],
        "linkedEvidence": evidence.get(node.identifier, []),
        "children": [_tree_node(version, child, rows, names, progress, evidence)
                     for child in version.children(node.code)],
    }


#: Campos de una evaluación que se registran en el historial, con su nombre en la API.
_TRACKED_FIELDS = (
    ("status", "status"), ("justification", "justification"), ("notes", "notes"),
    ("responsible_user_id", "responsibleUserId"), ("due_date", "dueDate"),
)


def _diff(row: Optional[EunomiaControlAssessment], fields: dict) -> dict:
    """Los campos que cambian entre la fila actual y los valores nuevos.

    Args:
        row: La fila actual, o ``None`` si el control estaba «pendiente» sin fila.
        fields: Valores nuevos por nombre de columna.

    Returns:
        dict: ``{campo: {"from": anterior, "to": nuevo}}`` con las fechas en ISO; vacío si no
            cambia nada.
    """
    def plain(value):
        return value.isoformat() if isinstance(value, (date, datetime)) else value

    changes = {}
    for column, name in _TRACKED_FIELDS:
        before = getattr(row, column) if row is not None else ("pending" if column == "status" else None)
        after = fields[column]
        if before != after:
            changes[name] = {"from": plain(before), "to": plain(after)}
    return changes


def _conflict_payload(row: Optional[EunomiaControlAssessment], framework_key: str, identifier: str) -> dict:
    """Lo que hay ahora en la fila, con las fechas ya en texto, para devolverlo en un conflicto."""
    payload = assessment_payload(row, framework_key, identifier)
    for key in ("dueDate", "updatedAt"):
        if isinstance(payload[key], (date, datetime)):
            payload[key] = payload[key].isoformat()
    return payload


def adoption_progress(owner_user_id: int, framework_key: str, catalog_version: str) -> Optional[dict]:
    """El progreso global de un marco adoptado, para las tarjetas de la pantalla de marcos.

    Args:
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.
        catalog_version: Versión que fijó la adopción.

    Returns:
        Optional[dict]: Lo que devuelve ``progress_of`` para el conjunto del marco, o ``None`` si
            la versión ya no está en el catálogo.
    """
    version = load_version(framework_key, catalog_version)
    if version is None:
        return None
    records = build_repository(EunomiaControlAssessmentRepository).list_for_framework(owner_user_id, framework_key)
    return summarize(version, _states(records), date.today())["global"]


class EunomiaAssessmentManager:
    """Evaluación de controles de los marcos adoptados."""

    def get_history(self, user_id: int, framework_key: str, identifier: str) -> list[dict]:
        """Devuelve el historial de cambios de un control, del más reciente al más antiguo.

        Args:
            user_id: Usuario que pregunta: el dueño efectivo o un miembro.
            framework_key: Clave del marco adoptado.
            identifier: Identificador del control.

        Returns:
            list[dict]: ``actorUserId`` (``None`` si la cuenta se borró), ``actorName``,
                ``occurredAt`` y ``changes`` (``{campo: {"from", "to"}}``).

        Raises:
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
            ControlNotFoundError: Si el control no existe en la versión adoptada (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        version = adopted_version(owner_user_id, framework_key)
        if version.node(f"{framework_key}:{identifier}") is None:
            raise ControlNotFoundError(identifier)
        events = build_repository(EunomiaAssessmentEventRepository).list_for_control(
            owner_user_id, framework_key, identifier)
        return [
            {"actorUserId": event.actor_user_id, "actorName": event.actor_name,
             "occurredAt": event.occurred_at, "changes": event.changes}
            for event in events
        ]

    def get_tree(self, user_id: int, framework_key: str) -> dict:
        """Devuelve el árbol de la versión adoptada combinado con las evaluaciones del dueño.

        Lo ve el dueño efectivo y los miembros de su organización.

        Args:
            user_id: Usuario que pregunta.
            framework_key: Clave del marco adoptado.

        Returns:
            dict: Metadatos de la versión (``key``, ``version``, ``name``, ``shortName``,
                ``status``, ``notes``, ``sources``) y ``tree``: las raíces con sus hijos
                anidados; cada nodo evaluable lleva ``assessment`` (``pending`` si no tiene fila).

        Raises:
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        version = adopted_version(owner_user_id, framework_key)
        records = build_repository(EunomiaControlAssessmentRepository).list_for_framework(
            owner_user_id, framework_key)
        rows = {row.control_identifier: row for row in records}
        ids = {value for row in records for value in (row.responsible_user_id, row.updated_by_user_id) if value}
        names = {user: display_name(user) for user in ids}
        links = build_repository(EunomiaEvidenceLinkRepository).list_for_framework(owner_user_id, framework_key)
        evidence_rows = {
            row.id: row for row in build_repository(EunomiaEvidenceRepository).list_for_owner(owner_user_id)
        }
        evidence: dict[str, list] = {}
        for link in links:
            row = evidence_rows.get(link.evidence_id)
            if row is not None:
                evidence.setdefault(link.control_identifier, []).append({
                    "id": row.id, "title": row.title, "filename": row.filename,
                    "sizeBytes": row.size_bytes, "validUntil": row.valid_until,
                })
        progress = branch_progress(version, _states(records))
        return {
            "people": _people(user_id, owner_user_id),
            "key": version.key, "version": version.version, "status": version.status,
            "name": version.name, "shortName": version.short_name, "notes": version.notes,
            "sources": [
                {"name": s.name, "url": s.url, "license": s.license, "consultedAt": s.consulted_at}
                for s in version.sources
            ],
            "tree": [_tree_node(version, root, rows, names, progress, evidence)
                     for root in version.children(None)],
        }

    def get_summary(self, user_id: int, framework_key: str) -> dict:
        """Resume cuánto falta de un marco: global, por rama, vencimientos y sin responsable.

        Args:
            user_id: Usuario que pregunta: el dueño efectivo o un miembro.
            framework_key: Clave del marco adoptado.

        Returns:
            dict: Lo que devuelve ``summarize``, con el nombre del responsable en cada control
                de ``upcoming`` y ``unassigned``.

        Raises:
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        version = adopted_version(owner_user_id, framework_key)
        records = build_repository(EunomiaControlAssessmentRepository).list_for_framework(
            owner_user_id, framework_key)
        summary = summarize(version, _states(records), date.today())
        names = {
            item["responsibleUserId"]: display_name(item["responsibleUserId"])
            for key in ("upcoming", "unassigned") for item in summary[key] if item["responsibleUserId"]
        }
        for key in ("upcoming", "unassigned"):
            for item in summary[key]:
                item["responsibleName"] = names.get(item["responsibleUserId"])
        return summary

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
        version = adopted_version(owner_user_id, framework_key)
        assessable_node(version, framework_key, identifier)

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
            changes = _diff(row, fields)
            if not changes:
                return assessment_payload(row, framework_key, identifier)
            EunomiaAssessmentEventRepository(uow).save(EunomiaAssessmentEvent(
                owner_user_id=owner_user_id, framework_key=framework_key, control_identifier=identifier,
                actor_user_id=user_id, actor_name=display_name(user_id) or "", occurred_at=fields["updated_at"],
                changes=changes,
            ))
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
