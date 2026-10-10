"""
EunomiaEvidenceManager — evidencias que demuestran el cumplimiento de varios controles.

Una evidencia se sube una vez, en el espacio del dueño efectivo, y se enlaza con cualquier
número de controles de cualquier marco adoptado. El dueño y los miembros de su organización
suben, enlazan y borran sobre lo mismo. Cada enlace y cada desenlace queda en el historial del
control afectado.
"""

import logging
from datetime import date
from typing import Optional

import src.modules.system.config_reading as CR
from src.modules.accounts import LimitKey, OrganizationManager, QuotaExceededError, QuotaManager
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive

from ..exceptions import (
    ControlNotAssessableError,
    ControlNotFoundError,
    EvidenceFileMissingError,
    EvidenceNotFoundError,
    EvidenceStorageFullError,
)
from ..model import EunomiaAssessmentEvent, EunomiaEvidence, EunomiaEvidenceContent, EunomiaEvidenceLink
from ..repositories import (
    EunomiaAssessmentEventRepository,
    EunomiaEvidenceContentRepository,
    EunomiaEvidenceLinkRepository,
    EunomiaEvidenceRepository,
)
from ..services.evidence_files import check_upload, digest, sanitize_filename
from .assessments import adopted_version, assessable_node, display_name

logger = logging.getLogger(__name__)


def evidence_payload(row: EunomiaEvidence, links: list[EunomiaEvidenceLink]) -> dict:
    """Serializa una ficha de evidencia con sus enlaces (sin el contenido).

    Args:
        row: La evidencia.
        links: Sus enlaces.

    Returns:
        dict: ``id``, ``title``, ``description``, ``filename``, ``contentType``, ``sizeBytes``,
            ``sha256``, ``validUntil``, ``uploadedAt``, ``uploadedByName`` y ``links``
            (``[{"frameworkKey", "controlIdentifier"}]``).
    """
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "filename": row.filename,
        "contentType": row.content_type,
        "sizeBytes": row.size_bytes,
        "sha256": row.sha256,
        "validUntil": row.valid_until,
        "uploadedAt": row.uploaded_at,
        "uploadedByName": display_name(row.uploaded_by_user_id),
        "links": [{"frameworkKey": link.framework_key, "controlIdentifier": link.control_identifier}
                  for link in links],
    }


def _record_link_event(uow: UnitOfWork, owner_user_id: int, actor_user_id: int, framework_key: str,
                       identifier: str, before: Optional[str], after: Optional[str]) -> None:
    """Anota en el historial del control que se enlazó o desenlazó una evidencia."""
    EunomiaAssessmentEventRepository(uow).save(EunomiaAssessmentEvent(
        owner_user_id=owner_user_id, framework_key=framework_key, control_identifier=identifier,
        actor_user_id=actor_user_id, actor_name=display_name(actor_user_id) or "", occurred_at=utcnow_naive(),
        changes={"evidence": {"from": before, "to": after}},
    ))


def _megabytes(size: int) -> int:
    """Bytes a megabytes, redondeando hacia arriba para no decir 0 de algo que ocupa."""
    return -(-size // (1024 * 1024))


class EunomiaEvidenceManager:
    """Subida, consulta, enlace y borrado de evidencias."""

    def usage(self, user_id: int) -> dict:
        """Cuánto almacenamiento de evidencias lleva gastado el dueño efectivo.

        Es lo que enseña la cabecera de la vista de evidencias, para que nadie se entere del
        límite al fallar una subida.

        Args:
            user_id: Usuario que pregunta: el dueño efectivo o un miembro (consume del dueño).

        Returns:
            dict: ``usedBytes``, ``limitBytes`` (``None`` si es ilimitado) y ``remainingBytes``.
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        state = QuotaManager().state(owner_user_id, LimitKey.EUNOMIA_EVIDENCE_STORAGE)
        return {"usedBytes": state.used, "limitBytes": state.limit, "remainingBytes": state.remaining}

    def assert_room_for(self, user_id: int, declared_bytes: int) -> None:
        """Comprueba, antes de leer el fichero, que su tamaño declarado cabe en el plan.

        Args:
            user_id: Usuario que sube.
            declared_bytes: Tamaño que anuncia la petición.

        Raises:
            EvidenceStorageFullError: Si no cabe (402).
        """
        usage = self.usage(user_id)
        if usage["remainingBytes"] is not None and declared_bytes > usage["remainingBytes"]:
            raise EvidenceStorageFullError(_megabytes(usage["usedBytes"]), _megabytes(usage["limitBytes"]))

    def upload(self, user_id: int, filename: str, content: Optional[bytes], title: str,
               description: str = "", valid_until: Optional[date] = None) -> dict:
        """Guarda un fichero como evidencia del dueño efectivo.

        Args:
            user_id: Usuario que sube: el dueño efectivo o un miembro.
            filename: Nombre que declara el navegador; se sanea.
            content: Los bytes del fichero, o ``None`` si no vino ninguno.
            title: Título de la evidencia; si está vacío se usa el nombre del fichero.
            description: Notas libres.
            valid_until: Hasta cuándo vale, o ``None``.

        Returns:
            dict: La ficha creada, con la forma de ``evidence_payload``.

        Raises:
            EvidenceFileMissingError: Si no hay fichero (400).
            EvidenceTooLargeError: Si supera el máximo (413).
            EvidenceTypeNotAllowedError: Si el tipo no está admitido (400).
        """
        if not content:
            raise EvidenceFileMissingError()
        config = CR.eunomia_config()
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        safe_name = sanitize_filename(filename)
        content_type = check_upload(safe_name, content, config.max_evidence_bytes, config.allowed_evidence_types)

        # Con el tamaño real, dentro de la operación: el declarado lo comprobó el endpoint antes
        # de leer el fichero, y este es el que cuenta.
        try:
            QuotaManager().consume(owner_user_id, LimitKey.EUNOMIA_EVIDENCE_STORAGE, len(content))
        except QuotaExceededError as exc:
            used = int((exc.details or {}).get("used", 0))
            limit = int((exc.details or {}).get("value", 0))
            raise EvidenceStorageFullError(_megabytes(used), _megabytes(limit)) from exc
        with UnitOfWork() as uow:
            evidence = EunomiaEvidenceRepository(uow).save(EunomiaEvidence(
                owner_user_id=owner_user_id, title=(title or "").strip() or safe_name,
                description=(description or "").strip() or None, filename=safe_name,
                content_type=content_type, size_bytes=len(content), sha256=digest(content),
                valid_until=valid_until, uploaded_at=utcnow_naive(), uploaded_by_user_id=user_id,
            ))
            EunomiaEvidenceContentRepository(uow).save(EunomiaEvidenceContent(
                evidence_id=evidence.id, content=content))
            payload = evidence_payload(evidence, [])
        logger.info("Evidencia subida | owner=%s id=%s bytes=%s", owner_user_id, payload["id"], payload["sizeBytes"])
        return payload

    def list_evidence(self, user_id: int) -> list[dict]:
        """Devuelve las evidencias del dueño efectivo, con sus enlaces.

        Args:
            user_id: Usuario que pregunta: el dueño efectivo o un miembro.

        Returns:
            list[dict]: Las fichas, de la más reciente a la más antigua.
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        rows = build_repository(EunomiaEvidenceRepository).list_for_owner(owner_user_id)
        links = build_repository(EunomiaEvidenceLinkRepository).list_for_evidence_ids([row.id for row in rows])
        by_evidence: dict[int, list] = {}
        for link in links:
            by_evidence.setdefault(link.evidence_id, []).append(link)
        return [evidence_payload(row, by_evidence.get(row.id, [])) for row in rows]

    def get_content(self, user_id: int, evidence_id: int) -> tuple[str, str, bytes]:
        """Devuelve nombre, tipo y bytes de una evidencia para descargarla.

        Args:
            user_id: Usuario que descarga.
            evidence_id: Clave primaria de la evidencia.

        Returns:
            tuple[str, str, bytes]: ``(nombre, tipo, contenido)``.

        Raises:
            EvidenceNotFoundError: Si no existe o es de otro dueño (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        row = build_repository(EunomiaEvidenceRepository).get_for_owner(owner_user_id, evidence_id)
        content = build_repository(EunomiaEvidenceContentRepository).get_by_evidence(evidence_id) if row else None
        if row is None or content is None:
            raise EvidenceNotFoundError(evidence_id)
        return row.filename, row.content_type, content.content

    def update(self, user_id: int, evidence_id: int, data: dict) -> dict:
        """Cambia título, descripción o validez de una evidencia.

        Args:
            user_id: Usuario que edita.
            evidence_id: Clave primaria de la evidencia.
            data: Claves opcionales ``title``, ``description`` y ``validUntil``.

        Returns:
            dict: La ficha actualizada.

        Raises:
            EvidenceNotFoundError: Si no existe o es de otro dueño (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        with UnitOfWork() as uow:
            repo = EunomiaEvidenceRepository(uow)
            row = repo.get_for_owner(owner_user_id, evidence_id)
            if row is None:
                raise EvidenceNotFoundError(evidence_id)
            if "title" in data and (data["title"] or "").strip():
                row.title = data["title"].strip()
            if "description" in data:
                row.description = (data["description"] or "").strip() or None
            if "validUntil" in data:
                row.valid_until = data["validUntil"]
            repo.save(row)
            links = EunomiaEvidenceLinkRepository(uow).list_for_evidence(evidence_id)
            return evidence_payload(row, links)

    def delete(self, user_id: int, evidence_id: int) -> None:
        """Borra una evidencia con su contenido y sus enlaces.

        Cada control que la tenía enlazada anota el cambio en su historial.

        Args:
            user_id: Usuario que borra.
            evidence_id: Clave primaria de la evidencia.

        Raises:
            EvidenceNotFoundError: Si no existe o es de otro dueño (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        with UnitOfWork() as uow:
            repo = EunomiaEvidenceRepository(uow)
            row = repo.get_for_owner(owner_user_id, evidence_id)
            if row is None:
                raise EvidenceNotFoundError(evidence_id)
            for link in EunomiaEvidenceLinkRepository(uow).list_for_evidence(evidence_id):
                _record_link_event(uow, owner_user_id, user_id, link.framework_key,
                                   link.control_identifier, row.title, None)
            repo.delete_with_dependents(evidence_id)
        logger.info("Evidencia borrada | owner=%s id=%s", owner_user_id, evidence_id)

    def link(self, user_id: int, evidence_id: int, framework_key: str, identifier: str) -> dict:
        """Enlaza una evidencia con un control evaluable de un marco adoptado.

        Idempotente: enlazar dos veces lo mismo deja un solo enlace.

        Args:
            user_id: Usuario que enlaza.
            evidence_id: Clave primaria de la evidencia.
            framework_key: Clave del marco adoptado.
            identifier: Identificador del control en la versión adoptada.

        Returns:
            dict: La ficha con sus enlaces.

        Raises:
            EvidenceNotFoundError: Si la evidencia no existe o es de otro dueño (404).
            AdoptionNotFoundError: Si el marco no está adoptado y activo (404).
            ControlNotFoundError: Si el control no existe en la versión adoptada (404).
            ControlNotAssessableError: Si el nodo es un grupo (400).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        version = adopted_version(owner_user_id, framework_key)
        assessable_node(version, framework_key, identifier)
        with UnitOfWork() as uow:
            row = EunomiaEvidenceRepository(uow).get_for_owner(owner_user_id, evidence_id)
            if row is None:
                raise EvidenceNotFoundError(evidence_id)
            links = EunomiaEvidenceLinkRepository(uow)
            if links.get_link(evidence_id, framework_key, identifier) is None:
                links.save(EunomiaEvidenceLink(
                    evidence_id=evidence_id, framework_key=framework_key, control_identifier=identifier,
                    linked_at=utcnow_naive(), linked_by_user_id=user_id))
                _record_link_event(uow, owner_user_id, user_id, framework_key, identifier, None, row.title)
            return evidence_payload(row, links.list_for_evidence(evidence_id))

    def unlink(self, user_id: int, evidence_id: int, framework_key: str, identifier: str) -> dict:
        """Quita el enlace entre una evidencia y un control. No borra la evidencia.

        Args:
            user_id: Usuario que desenlaza.
            evidence_id: Clave primaria de la evidencia.
            framework_key: Clave del marco.
            identifier: Identificador del control.

        Returns:
            dict: La ficha con los enlaces que le quedan.

        Raises:
            EvidenceNotFoundError: Si la evidencia no existe o es de otro dueño (404).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        with UnitOfWork() as uow:
            row = EunomiaEvidenceRepository(uow).get_for_owner(owner_user_id, evidence_id)
            if row is None:
                raise EvidenceNotFoundError(evidence_id)
            links = EunomiaEvidenceLinkRepository(uow)
            existing = links.get_link(evidence_id, framework_key, identifier)
            if existing is not None:
                links.delete(existing)
                _record_link_event(uow, owner_user_id, user_id, framework_key, identifier, row.title, None)
            return evidence_payload(row, links.list_for_evidence(evidence_id))
