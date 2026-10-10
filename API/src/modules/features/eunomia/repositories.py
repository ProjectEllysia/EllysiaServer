"""Acceso a datos del módulo Eunomia."""

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import and_, func, update

from src.modules.infrastructure import BaseRepository, DocumentRepository

from .model import (
    ADOPTION_ACTIVE,
    ADOPTION_ARCHIVED,
    EunomiaAssessmentEvent,
    EunomiaControlAssessment,
    EunomiaDocument,
    EunomiaEvidence,
    EunomiaEvidenceContent,
    EunomiaEvidenceLink,
    EunomiaFrameworkAdoption,
    EunomiaRecord,
    EunomiaRecordEvent,
    EunomiaTemplateDraft,
)


class EunomiaFrameworkAdoptionRepository(BaseRepository[EunomiaFrameworkAdoption]):
    """Acceso a datos de las adopciones de marcos."""

    _MODEL = EunomiaFrameworkAdoption

    def get_for_owner(self, owner_user_id: int, framework_key: str) -> Optional[EunomiaFrameworkAdoption]:
        """La adopción de un marco de un dueño, activa o archivada, o ``None``.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
        """
        return (
            self._session.query(EunomiaFrameworkAdoption)
            .filter(EunomiaFrameworkAdoption.owner_user_id == owner_user_id,
                    EunomiaFrameworkAdoption.framework_key == framework_key)
            .one_or_none()
        )

    def list_for_owner(self, owner_user_id: int) -> List[EunomiaFrameworkAdoption]:
        """Todas las adopciones de un dueño, activas y archivadas, por fecha de adopción.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        return (
            self._session.query(EunomiaFrameworkAdoption)
            .filter(EunomiaFrameworkAdoption.owner_user_id == owner_user_id)
            .order_by(EunomiaFrameworkAdoption.adopted_at.asc(), EunomiaFrameworkAdoption.id.asc())
            .all()
        )

    def list_archived_before(self, moment: datetime) -> List[EunomiaFrameworkAdoption]:
        """Las adopciones archivadas desde antes de un instante: las que ya se pueden purgar.

        Args:
            moment: Instante de corte (UTC naive).
        """
        return (
            self._session.query(EunomiaFrameworkAdoption)
            .filter(EunomiaFrameworkAdoption.status == ADOPTION_ARCHIVED,
                    EunomiaFrameworkAdoption.archived_at < moment)
            .all()
        )

    def count_active_for_owners(self, owner_user_ids: list[int]) -> int:
        """Cuántas adopciones activas tienen unos dueños: lo que cuenta para la cuota.

        Args:
            owner_user_ids: Ids de los dueños (la bolsa de una organización suma a sus miembros).
        """
        return (
            self._session.query(EunomiaFrameworkAdoption)
            .filter(EunomiaFrameworkAdoption.owner_user_id.in_(owner_user_ids),
                    EunomiaFrameworkAdoption.status == ADOPTION_ACTIVE)
            .count()
        )

    def delete_for_owner(self, owner_user_id: int) -> int:
        """Borra todas las adopciones de un dueño; devuelve cuántas.

        Args:
            owner_user_id: Dueño cuyas adopciones se borran.
        """
        return self._session.query(EunomiaFrameworkAdoption).filter(
            EunomiaFrameworkAdoption.owner_user_id == owner_user_id
        ).delete(synchronize_session=False)


class EunomiaControlAssessmentRepository(BaseRepository[EunomiaControlAssessment]):
    """Acceso a datos de las evaluaciones de controles."""

    _MODEL = EunomiaControlAssessment

    def get_for_control(self, owner_user_id: int, framework_key: str,
                        control_identifier: str) -> Optional[EunomiaControlAssessment]:
        """La evaluación de un control de un dueño, o ``None`` si está pendiente.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
            control_identifier: Identificador del control en la versión adoptada.
        """
        return (
            self._session.query(EunomiaControlAssessment)
            .filter(EunomiaControlAssessment.owner_user_id == owner_user_id,
                    EunomiaControlAssessment.framework_key == framework_key,
                    EunomiaControlAssessment.control_identifier == control_identifier)
            .one_or_none()
        )

    def list_for_framework(self, owner_user_id: int, framework_key: str) -> List[EunomiaControlAssessment]:
        """Todas las evaluaciones de un marco de un dueño.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
        """
        return (
            self._session.query(EunomiaControlAssessment)
            .filter(EunomiaControlAssessment.owner_user_id == owner_user_id,
                    EunomiaControlAssessment.framework_key == framework_key)
            .all()
        )

    def update_if_unchanged(self, assessment_id: int, expected_updated_at: datetime, **fields) -> bool:
        """Actualiza una evaluación solo si nadie la ha tocado desde ``expected_updated_at``.

        La condición va dentro del ``UPDATE`` (CONVENCIONES § 4.4): leer, decidir y escribir
        dejaría pasar a dos miembros que editan el mismo control a la vez.

        Args:
            assessment_id: Clave primaria de la evaluación.
            expected_updated_at: El ``updated_at`` que vio quien escribe.
            **fields: Columnas a cambiar.

        Returns:
            bool: ``True`` si ganó la escritura; ``False`` si la fila había cambiado.
        """
        result = self._session.execute(
            update(EunomiaControlAssessment)
            .where(and_(EunomiaControlAssessment.id == assessment_id,
                        EunomiaControlAssessment.updated_at == expected_updated_at))
            .values(**fields)
        )
        return result.rowcount == 1

    def clear_user_references(self, user_id: int) -> None:
        """Deja a ``NULL`` las referencias a un usuario que se da de baja.

        Responsable y último editor son rastro de otra persona, no datos de quien se va.

        Args:
            user_id: Usuario que se borra.
        """
        self._session.query(EunomiaControlAssessment).filter(
            EunomiaControlAssessment.responsible_user_id == user_id
        ).update({"responsible_user_id": None}, synchronize_session=False)
        self._session.query(EunomiaControlAssessment).filter(
            EunomiaControlAssessment.updated_by_user_id == user_id
        ).update({"updated_by_user_id": None}, synchronize_session=False)

    def delete_for_owner(self, owner_user_id: int) -> int:
        """Borra todas las evaluaciones de un dueño; devuelve cuántas.

        Args:
            owner_user_id: Dueño cuyas evaluaciones se borran.
        """
        return self._session.query(EunomiaControlAssessment).filter(
            EunomiaControlAssessment.owner_user_id == owner_user_id
        ).delete(synchronize_session=False)

    def delete_for_framework(self, owner_user_id: int, framework_key: str) -> int:
        """Borra las evaluaciones de un marco de un dueño; devuelve cuántas.

        Args:
            owner_user_id: Dueño efectivo.
            framework_key: Clave del marco.
        """
        return self._session.query(EunomiaControlAssessment).filter(
            EunomiaControlAssessment.owner_user_id == owner_user_id,
            EunomiaControlAssessment.framework_key == framework_key,
        ).delete(synchronize_session=False)

    def count_not_pending(self, owner_user_id: int, framework_key: str) -> int:
        """Cuántas evaluaciones de un marco tienen un estado distinto de «pendiente».

        Args:
            owner_user_id: Dueño efectivo.
            framework_key: Clave del marco.
        """
        return self._session.query(EunomiaControlAssessment).filter(
            EunomiaControlAssessment.owner_user_id == owner_user_id,
            EunomiaControlAssessment.framework_key == framework_key,
            EunomiaControlAssessment.status != "pending",
        ).count()


class EunomiaAssessmentEventRepository(BaseRepository[EunomiaAssessmentEvent]):
    """Acceso a datos del historial de evaluaciones: de solo añadir."""

    _MODEL = EunomiaAssessmentEvent

    def list_for_control(self, owner_user_id: int, framework_key: str,
                         control_identifier: str) -> List[EunomiaAssessmentEvent]:
        """El historial de un control, del cambio más reciente al más antiguo.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
            control_identifier: Identificador del control.
        """
        return (
            self._session.query(EunomiaAssessmentEvent)
            .filter(EunomiaAssessmentEvent.owner_user_id == owner_user_id,
                    EunomiaAssessmentEvent.framework_key == framework_key,
                    EunomiaAssessmentEvent.control_identifier == control_identifier)
            .order_by(EunomiaAssessmentEvent.occurred_at.desc(), EunomiaAssessmentEvent.id.desc())
            .all()
        )

    def clear_actor(self, user_id: int) -> None:
        """Deja a ``NULL`` el actor de los eventos de un usuario que se da de baja.

        El evento conserva ``actor_name``: pierde el vínculo a la cuenta, no el rastro.

        Args:
            user_id: Usuario que se borra.
        """
        self._session.query(EunomiaAssessmentEvent).filter(
            EunomiaAssessmentEvent.actor_user_id == user_id
        ).update({"actor_user_id": None}, synchronize_session=False)

    def delete_for_owner(self, owner_user_id: int) -> int:
        """Borra el historial de un dueño; devuelve cuántos eventos.

        Args:
            owner_user_id: Dueño cuyo historial se borra.
        """
        return self._session.query(EunomiaAssessmentEvent).filter(
            EunomiaAssessmentEvent.owner_user_id == owner_user_id
        ).delete(synchronize_session=False)

    def delete_for_framework(self, owner_user_id: int, framework_key: str) -> int:
        """Borra el historial de un marco de un dueño; devuelve cuántos eventos.

        Args:
            owner_user_id: Dueño efectivo.
            framework_key: Clave del marco.
        """
        return self._session.query(EunomiaAssessmentEvent).filter(
            EunomiaAssessmentEvent.owner_user_id == owner_user_id,
            EunomiaAssessmentEvent.framework_key == framework_key,
        ).delete(synchronize_session=False)


class EunomiaEvidenceRepository(BaseRepository[EunomiaEvidence]):
    """Acceso a datos de las fichas de evidencia (sin su contenido)."""

    _MODEL = EunomiaEvidence

    def get_for_owner(self, owner_user_id: int, evidence_id: int) -> Optional[EunomiaEvidence]:
        """Una evidencia de un dueño, o ``None`` si no existe o es de otro.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            evidence_id: Clave primaria de la evidencia.
        """
        return (
            self._session.query(EunomiaEvidence)
            .filter(EunomiaEvidence.id == evidence_id, EunomiaEvidence.owner_user_id == owner_user_id)
            .one_or_none()
        )

    def list_for_owner(self, owner_user_id: int) -> List[EunomiaEvidence]:
        """Las evidencias de un dueño, de la más reciente a la más antigua.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        return (
            self._session.query(EunomiaEvidence)
            .filter(EunomiaEvidence.owner_user_id == owner_user_id)
            .order_by(EunomiaEvidence.uploaded_at.desc(), EunomiaEvidence.id.desc())
            .all()
        )

    def sum_size_for_owners(self, owner_user_ids: list[int]) -> int:
        """Suma el tamaño original de las evidencias de unos dueños, en bytes.

        Args:
            owner_user_ids: Ids de los dueños (la bolsa de una organización suma a sus miembros).
        """
        total = self._session.query(func.coalesce(func.sum(EunomiaEvidence.size_bytes), 0)).filter(
            EunomiaEvidence.owner_user_id.in_(owner_user_ids)
        ).scalar()
        return int(total or 0)

    def clear_user_references(self, user_id: int) -> None:
        """Deja a ``NULL`` quién subió las evidencias de un usuario que se da de baja.

        Args:
            user_id: Usuario que se borra.
        """
        self._session.query(EunomiaEvidence).filter(
            EunomiaEvidence.uploaded_by_user_id == user_id
        ).update({"uploaded_by_user_id": None}, synchronize_session=False)
        self._session.query(EunomiaEvidenceLink).filter(
            EunomiaEvidenceLink.linked_by_user_id == user_id
        ).update({"linked_by_user_id": None}, synchronize_session=False)

    def delete_with_dependents(self, evidence_id: int) -> None:
        """Borra una evidencia con su contenido y sus enlaces.

        Se hace a mano y no con ``ON DELETE CASCADE``: SQLite no lo aplica sin un pragma.

        Args:
            evidence_id: Clave primaria de la evidencia.
        """
        self._session.query(EunomiaEvidenceLink).filter(
            EunomiaEvidenceLink.evidence_id == evidence_id).delete(synchronize_session=False)
        self._session.query(EunomiaEvidenceContent).filter(
            EunomiaEvidenceContent.evidence_id == evidence_id).delete(synchronize_session=False)
        self._session.query(EunomiaEvidence).filter(
            EunomiaEvidence.id == evidence_id).delete(synchronize_session=False)

    def list_expiring(self, on_or_before: date) -> List[EunomiaEvidence]:
        """Las evidencias cuya validez vence en o antes de una fecha y de las que aún no se avisó.

        Args:
            on_or_before: Fecha límite (incluida): hoy más la antelación del aviso.

        Returns:
            List[EunomiaEvidence]: Las que tienen ``valid_until`` y no se han avisado para esa
                misma fecha, de la que vence antes a la que vence después.
        """
        return (
            self._session.query(EunomiaEvidence)
            .filter(EunomiaEvidence.valid_until.isnot(None),
                    EunomiaEvidence.valid_until <= on_or_before,
                    (EunomiaEvidence.expiry_notified_for.is_(None))
                    | (EunomiaEvidence.expiry_notified_for != EunomiaEvidence.valid_until))
            .order_by(EunomiaEvidence.valid_until.asc(), EunomiaEvidence.id.asc())
            .all()
        )

    def iter_files_for_owner(self, owner_user_id: int):
        """Va dando cada evidencia de un dueño con sus bytes ya descifrados, de una en una.

        Args:
            owner_user_id: Dueño efectivo de los datos.

        Yields:
            tuple[EunomiaEvidence, bytes]: La ficha y su contenido.
        """
        rows = (
            self._session.query(EunomiaEvidence, EunomiaEvidenceContent)
            .join(EunomiaEvidenceContent, EunomiaEvidenceContent.evidence_id == EunomiaEvidence.id)
            .filter(EunomiaEvidence.owner_user_id == owner_user_id)
            .order_by(EunomiaEvidence.id)
            .yield_per(20)
        )
        for evidence, content in rows:
            yield evidence, content.content

    def ids_for_owner(self, owner_user_id: int) -> list[int]:
        """Las claves de todas las evidencias de un dueño.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        return [row[0] for row in self._session.query(EunomiaEvidence.id).filter(
            EunomiaEvidence.owner_user_id == owner_user_id)]


class EunomiaEvidenceContentRepository(BaseRepository[EunomiaEvidenceContent]):
    """Acceso a datos del contenido cifrado de las evidencias."""

    _MODEL = EunomiaEvidenceContent

    def get_by_evidence(self, evidence_id: int) -> Optional[EunomiaEvidenceContent]:
        """El contenido de una evidencia, o ``None``.

        Args:
            evidence_id: Clave primaria de la evidencia.
        """
        return self.get_by_field("evidence_id", evidence_id)


class EunomiaEvidenceLinkRepository(BaseRepository[EunomiaEvidenceLink]):
    """Acceso a datos de los enlaces entre evidencias y controles."""

    _MODEL = EunomiaEvidenceLink

    def list_for_evidence(self, evidence_id: int) -> List[EunomiaEvidenceLink]:
        """Los enlaces de una evidencia.

        Args:
            evidence_id: Clave primaria de la evidencia.
        """
        return (
            self._session.query(EunomiaEvidenceLink)
            .filter(EunomiaEvidenceLink.evidence_id == evidence_id)
            .order_by(EunomiaEvidenceLink.framework_key, EunomiaEvidenceLink.control_identifier)
            .all()
        )

    def list_for_evidence_ids(self, evidence_ids: list[int]) -> List[EunomiaEvidenceLink]:
        """Los enlaces de varias evidencias, en una sola consulta.

        Args:
            evidence_ids: Claves primarias de las evidencias.
        """
        if not evidence_ids:
            return []
        return (
            self._session.query(EunomiaEvidenceLink)
            .filter(EunomiaEvidenceLink.evidence_id.in_(evidence_ids))
            .all()
        )

    def get_link(self, evidence_id: int, framework_key: str, control_identifier: str) -> Optional[EunomiaEvidenceLink]:
        """Un enlace concreto, o ``None``.

        Args:
            evidence_id: Clave primaria de la evidencia.
            framework_key: Clave del marco.
            control_identifier: Identificador del control.
        """
        return (
            self._session.query(EunomiaEvidenceLink)
            .filter(EunomiaEvidenceLink.evidence_id == evidence_id,
                    EunomiaEvidenceLink.framework_key == framework_key,
                    EunomiaEvidenceLink.control_identifier == control_identifier)
            .one_or_none()
        )

    def list_for_framework(self, owner_user_id: int, framework_key: str) -> List[EunomiaEvidenceLink]:
        """Los enlaces de un marco cuyas evidencias son de un dueño.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
        """
        return (
            self._session.query(EunomiaEvidenceLink)
            .join(EunomiaEvidence, EunomiaEvidence.id == EunomiaEvidenceLink.evidence_id)
            .filter(EunomiaEvidence.owner_user_id == owner_user_id,
                    EunomiaEvidenceLink.framework_key == framework_key)
            .all()
        )

    def evidence_ids_linked_elsewhere(self, evidence_ids: set[int], framework_key: str) -> set[int]:
        """De unas evidencias, cuáles tienen algún enlace con un marco distinto del dado.

        Args:
            evidence_ids: Claves primarias de las evidencias a comprobar.
            framework_key: El marco que se excluye.
        """
        if not evidence_ids:
            return set()
        rows = self._session.query(EunomiaEvidenceLink.evidence_id).filter(
            EunomiaEvidenceLink.evidence_id.in_(evidence_ids),
            EunomiaEvidenceLink.framework_key != framework_key,
        )
        return {row[0] for row in rows}

    def delete_for_framework(self, owner_user_id: int, framework_key: str) -> int:
        """Borra los enlaces de un marco de un dueño; devuelve cuántos.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
        """
        ids = [row[0] for row in self._session.query(EunomiaEvidenceLink.id)
               .join(EunomiaEvidence, EunomiaEvidence.id == EunomiaEvidenceLink.evidence_id)
               .filter(EunomiaEvidence.owner_user_id == owner_user_id,
                       EunomiaEvidenceLink.framework_key == framework_key)]
        if not ids:
            return 0
        return self._session.query(EunomiaEvidenceLink).filter(
            EunomiaEvidenceLink.id.in_(ids)).delete(synchronize_session=False)


class EunomiaTemplateDraftRepository(BaseRepository[EunomiaTemplateDraft]):
    """Acceso a datos de los borradores de plantillas."""

    _MODEL = EunomiaTemplateDraft

    def get_for_owner(self, owner_user_id: int, template_key: str) -> Optional[EunomiaTemplateDraft]:
        """El borrador de una plantilla de un dueño, o ``None``.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            template_key: Identificador de la plantilla.
        """
        return (
            self._session.query(EunomiaTemplateDraft)
            .filter(EunomiaTemplateDraft.owner_user_id == owner_user_id,
                    EunomiaTemplateDraft.template_key == template_key)
            .one_or_none()
        )

    def list_for_owner(self, owner_user_id: int) -> List[EunomiaTemplateDraft]:
        """Todos los borradores de un dueño.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        return (
            self._session.query(EunomiaTemplateDraft)
            .filter(EunomiaTemplateDraft.owner_user_id == owner_user_id)
            .all()
        )

    def clear_user_references(self, user_id: int) -> None:
        """Anula quién escribió por última vez cuando esa cuenta se borra.

        Args:
            user_id: Usuario cuya cuenta se borra.
        """
        self._session.query(EunomiaTemplateDraft).filter(
            EunomiaTemplateDraft.updated_by_user_id == user_id
        ).update({EunomiaTemplateDraft.updated_by_user_id: None}, synchronize_session=False)

    def delete_for_owner(self, owner_user_id: int) -> int:
        """Borra todos los borradores de un dueño; devuelve cuántos.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        return self._session.query(EunomiaTemplateDraft).filter(
            EunomiaTemplateDraft.owner_user_id == owner_user_id
        ).delete(synchronize_session=False)


class EunomiaDocumentRepository(DocumentRepository[EunomiaDocument]):
    """Acceso a datos de ``EunomiaDocument``.

    Las consultas por dueño y la paginación las hereda de ``DocumentRepository``. No define
    ``_PARENT_FK``: un documento no cuelga de ninguna entidad padre.
    """

    _MODEL = EunomiaDocument

    def get_unfinished_documents(self) -> List[EunomiaDocument]:
        """Los documentos de cualquier dueño que siguen en ``pending`` o ``running``."""
        return (
            self._session.query(EunomiaDocument)
            .filter(EunomiaDocument.status.in_(("pending", "running")))
            .all()
        )


class EunomiaRecordRepository(BaseRepository[EunomiaRecord]):
    """Acceso a datos de las fichas de los registros."""

    _MODEL = EunomiaRecord

    def get_for_owner(self, owner_user_id: int, register_key: str, record_id: int) -> Optional[EunomiaRecord]:
        """Una ficha de un dueño y de un registro, o ``None`` si no existe o es de otro.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            register_key: Tipo de registro.
            record_id: Clave primaria de la ficha.
        """
        return (
            self._session.query(EunomiaRecord)
            .filter(EunomiaRecord.id == record_id, EunomiaRecord.owner_user_id == owner_user_id,
                    EunomiaRecord.register_key == register_key)
            .one_or_none()
        )

    def list_for_register(self, owner_user_id: int, register_key: str,
                          include_archived: bool = False) -> List[EunomiaRecord]:
        """Las fichas de un registro, de la más reciente a la más antigua.

        Args:
            owner_user_id: Dueño efectivo de los datos.
            register_key: Tipo de registro.
            include_archived: Si salen también las archivadas. Por defecto ``False``.
        """
        query = self._session.query(EunomiaRecord).filter(
            EunomiaRecord.owner_user_id == owner_user_id, EunomiaRecord.register_key == register_key)
        if not include_archived:
            query = query.filter(EunomiaRecord.is_archived.is_(False))
        return query.order_by(EunomiaRecord.created_at.desc(), EunomiaRecord.id.desc()).all()

    def list_open_for_registers(self, register_keys: list[str]) -> List[EunomiaRecord]:
        """Las fichas no archivadas de unos tipos de registro, de cualquier dueño.

        Lo usa el trabajo programado de avisos de plazos.

        Args:
            register_keys: Tipos de registro que interesan.
        """
        if not register_keys:
            return []
        return (
            self._session.query(EunomiaRecord)
            .filter(EunomiaRecord.register_key.in_(register_keys), EunomiaRecord.is_archived.is_(False))
            .all()
        )

    def count_by_register(self, owner_user_id: int) -> dict[str, int]:
        """Cuántas fichas no archivadas tiene un dueño en cada registro.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        rows = (
            self._session.query(EunomiaRecord.register_key, func.count(EunomiaRecord.id))
            .filter(EunomiaRecord.owner_user_id == owner_user_id, EunomiaRecord.is_archived.is_(False))
            .group_by(EunomiaRecord.register_key)
            .all()
        )
        return {key: count for key, count in rows}

    def update_if_unchanged(self, record_id: int, expected_updated_at: datetime, **fields) -> bool:
        """Actualiza una ficha solo si nadie la ha tocado desde ``expected_updated_at``.

        La condición va dentro del ``UPDATE`` (CONVENCIONES § 4.4).

        Args:
            record_id: Clave primaria de la ficha.
            expected_updated_at: El ``updated_at`` que vio quien escribe.
            **fields: Columnas a cambiar.

        Returns:
            bool: ``True`` si ganó la escritura; ``False`` si la ficha había cambiado.
        """
        result = self._session.execute(
            update(EunomiaRecord)
            .where(and_(EunomiaRecord.id == record_id, EunomiaRecord.updated_at == expected_updated_at))
            .values(**fields)
        )
        return result.rowcount == 1

    def clear_user_references(self, user_id: int) -> None:
        """Anula quién creó o editó fichas cuando esa cuenta se borra.

        Args:
            user_id: Usuario cuya cuenta se borra.
        """
        for column in (EunomiaRecord.created_by_user_id, EunomiaRecord.updated_by_user_id):
            self._session.query(EunomiaRecord).filter(column == user_id).update(
                {column: None}, synchronize_session=False)

    def delete_for_owner(self, owner_user_id: int) -> int:
        """Borra todas las fichas de un dueño (y, por cascada, su historial); devuelve cuántas.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        ids = [row[0] for row in self._session.query(EunomiaRecord.id).filter(
            EunomiaRecord.owner_user_id == owner_user_id)]
        if ids:
            self._session.query(EunomiaRecordEvent).filter(EunomiaRecordEvent.record_id.in_(ids)).delete(
                synchronize_session=False)
        return self._session.query(EunomiaRecord).filter(
            EunomiaRecord.owner_user_id == owner_user_id).delete(synchronize_session=False)


class EunomiaRecordEventRepository(BaseRepository[EunomiaRecordEvent]):
    """Acceso a datos del historial de las fichas: de solo añadir."""

    _MODEL = EunomiaRecordEvent

    def list_for_record(self, record_id: int) -> List[EunomiaRecordEvent]:
        """El historial de una ficha, del cambio más reciente al más antiguo.

        Args:
            record_id: Clave primaria de la ficha.
        """
        return (
            self._session.query(EunomiaRecordEvent)
            .filter(EunomiaRecordEvent.record_id == record_id)
            .order_by(EunomiaRecordEvent.occurred_at.desc(), EunomiaRecordEvent.id.desc())
            .all()
        )

    def clear_actor(self, user_id: int) -> None:
        """Deja a ``NULL`` el actor de los eventos de un usuario que se da de baja.

        Args:
            user_id: Usuario que se borra.
        """
        self._session.query(EunomiaRecordEvent).filter(
            EunomiaRecordEvent.actor_user_id == user_id
        ).update({"actor_user_id": None}, synchronize_session=False)

    def delete_for_owner(self, owner_user_id: int) -> int:
        """Borra los eventos de un dueño; devuelve cuántos.

        Args:
            owner_user_id: Dueño efectivo de los datos.
        """
        return self._session.query(EunomiaRecordEvent).filter(
            EunomiaRecordEvent.owner_user_id == owner_user_id).delete(synchronize_session=False)
