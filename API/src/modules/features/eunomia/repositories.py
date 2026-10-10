"""Acceso a datos del módulo Eunomia."""

from datetime import datetime
from typing import List, Optional

from src.modules.infrastructure import BaseRepository

from .model import ADOPTION_ACTIVE, ADOPTION_ARCHIVED, EunomiaFrameworkAdoption


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
