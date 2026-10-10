"""Acceso a datos del módulo Eunomia."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, func, update

from src.modules.infrastructure import BaseRepository

from .model import (
    ADOPTION_ACTIVE,
    ADOPTION_ARCHIVED,
    EunomiaAssessmentEvent,
    EunomiaControlAssessment,
    EunomiaEvidence,
    EunomiaEvidenceContent,
    EunomiaEvidenceLink,
    EunomiaFrameworkAdoption,
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
