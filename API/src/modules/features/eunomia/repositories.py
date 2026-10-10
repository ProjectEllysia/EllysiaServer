"""Acceso a datos del módulo Eunomia."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, update

from src.modules.infrastructure import BaseRepository

from .model import ADOPTION_ACTIVE, ADOPTION_ARCHIVED, EunomiaControlAssessment, EunomiaFrameworkAdoption


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
