"""
Lo que cuelga de una adopción: el punto donde las fases siguientes se enganchan.

Quitar un marco tiene que decir **qué se pierde** y, pasado el plazo, borrarlo. Lo que se
pierde (evaluaciones, evidencias, historial) lo guardan tablas que llegan en fases
posteriores; para que la adopción no tenga que conocerlas, cada una declara aquí cómo se
cuenta y cómo se purga lo suyo para un ``(dueño, marco)``.

Un proveedor devuelve cantidades con nombre: ``assessments`` (evaluaciones que ya no están
«pendientes»), ``evidenceDeleted`` (evidencias que se borrarían con el marco) y
``evidenceKept`` (evidencias que se conservan porque también sirven a otro marco adoptado).
Un proveedor puede devolver solo las que le conciernen; las que no aparezcan cuentan 0.
"""

from dataclasses import dataclass
from typing import Callable

from src.modules.infrastructure import UnitOfWork

#: Cantidades que enseña la vista previa de quitar un marco, en el orden en que se muestran.
PREVIEW_KEYS = ("assessments", "evidenceDeleted", "evidenceKept")

CountHook = Callable[[UnitOfWork, int, str], dict[str, int]]
PurgeHook = Callable[[UnitOfWork, int, str], dict[str, int]]


@dataclass(frozen=True)
class AdoptionDataProvider:
    """Cómo cuenta y purga lo suyo una tabla que cuelga de una adopción.

    Attributes:
        name: Nombre del proveedor (``"assessments"``).
        count: ``(uow, owner_user_id, framework_key) -> {cantidad: n}``; solo lee.
        purge: ``(uow, owner_user_id, framework_key) -> {tabla: filas borradas}``; borra lo
            que es exclusivo de ese marco y conserva lo que sirve a otro marco adoptado.
    """

    name: str
    count: CountHook
    purge: PurgeHook


class AdoptionDataRegistry:
    """Registro de proveedores de datos de una adopción."""

    _providers: dict[str, AdoptionDataProvider] = {}

    @classmethod
    def register(cls, name: str, *, count: CountHook, purge: PurgeHook) -> None:
        """Da de alta un proveedor. Idempotente: registrar el mismo ``name`` deja el último.

        Args:
            name: Nombre del proveedor.
            count: Función de recuento (ver ``AdoptionDataProvider``).
            purge: Función de purga (ver ``AdoptionDataProvider``).
        """
        cls._providers[name] = AdoptionDataProvider(name=name, count=count, purge=purge)

    @classmethod
    def providers(cls) -> tuple[AdoptionDataProvider, ...]:
        """Devuelve los proveedores registrados, en orden de alta."""
        return tuple(cls._providers.values())

    @classmethod
    def count_all(cls, uow: UnitOfWork, owner_user_id: int, framework_key: str) -> dict[str, int]:
        """Suma lo que cuentan todos los proveedores para un ``(dueño, marco)``.

        Returns:
            dict[str, int]: Todas las claves de ``PREVIEW_KEYS``, con 0 si nadie las aporta.
        """
        totals = {key: 0 for key in PREVIEW_KEYS}
        for provider in cls._providers.values():
            for key, amount in provider.count(uow, owner_user_id, framework_key).items():
                totals[key] = totals.get(key, 0) + amount
        return totals

    @classmethod
    def purge_all(cls, uow: UnitOfWork, owner_user_id: int, framework_key: str) -> dict[str, int]:
        """Purga con todos los proveedores lo que cuelga de un ``(dueño, marco)``.

        Returns:
            dict[str, int]: Filas borradas por tabla.
        """
        deleted: dict[str, int] = {}
        for provider in cls._providers.values():
            for table, rows in provider.purge(uow, owner_user_id, framework_key).items():
                deleted[table] = deleted.get(table, 0) + rows
        return deleted
