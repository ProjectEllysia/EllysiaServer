"""
Registro de los datos que otros módulos guardan de un usuario.

**Para qué existe.** Borrar una cuenta, avisar de lo que se borrará y exportar
sus datos obligan a conocer las tablas de otros módulos. Si ``users`` las
importase, cada módulo transversal nuevo con una tabla ``user_id`` obligaría a
editar un fichero de *otro* módulo, y olvidarlo dejaría la baja con datos
huérfanos sin que ningún test lo dijese.

Aquí la dependencia va al revés (CONVENCIONES.md § 3.4): cada módulo se da de
alta desde su propio ``__init__.py``, igual que hace con
``QueueRegistry.register(...)``, y ``users`` recorre el registro sin conocer a
nadie. Hoy lo usa ``accounts``; las features siguen declaradas a mano en
``account_deletion.py`` y ``data_export.py``.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

from src.modules.infrastructure import UnitOfWork
from src.modules.shared import ExportTable

#: Firma de una purga: recibe la unidad de trabajo de la baja y el usuario, y
#: devuelve cuántas filas cayeron por tabla.
PurgeHook = Callable[[UnitOfWork, int], dict[str, int]]


@dataclass(frozen=True)
class UserDataContribution:
    """Lo que un módulo declara de los datos que guarda de un usuario.

    Attributes:
        name: Nombre del módulo (``"accounts"``). Da nombre al JSON de la
            exportación y a la línea del log de la purga.
        purge: Borra, dentro de la transacción de la baja, las filas que el
            módulo guarda del usuario. Las referencias de otros usuarios hacia
            él que sean rastro histórico (quién invitó, quién asignó) se ponen a
            ``NULL`` en vez de borrar la fila.
        deletion_models: Categoría del aviso previo al borrado
            (``DELETION_CATEGORY_KEYS``) → modelos con columna ``user_id`` cuyas
            filas del usuario suman a esa categoría.
        export_tables: Tablas que entran en la exportación de datos, en el
            orden en que se escriben.
        priority: Orden de purga entre módulos registrados: de menor a mayor.
            Todos van después de las features y antes de las filas de ``users``.
    """

    name: str
    purge: PurgeHook
    deletion_models: Mapping[str, tuple] = field(default_factory=dict)
    export_tables: tuple[ExportTable, ...] = ()
    priority: int = 100


class UserDataRegistry:
    """Registro de módulos que guardan datos de un usuario.

    Lo rellena cada módulo desde su ``__init__.py`` al cargarse; ``users`` lo
    recorre al borrar una cuenta y al exportar sus datos. Tanto la API como el
    worker pasan por ``create_app``, así que ambos lo ven completo.
    """

    _contributions: dict[str, UserDataContribution] = {}
    _lock = threading.Lock()

    @classmethod
    def register(
        cls,
        name: str,
        *,
        purge: PurgeHook,
        deletion_models: Optional[Mapping[str, tuple]] = None,
        export_tables: tuple[ExportTable, ...] = (),
        priority: int = 100,
    ) -> None:
        """Da de alta un módulo en el registro.

        Idempotente: registrar dos veces el mismo ``name`` deja la última
        declaración, como ``QueueRegistry.register``.

        Args:
            name: Nombre del módulo (``"accounts"``).
            purge: Ver ``UserDataContribution.purge``.
            deletion_models: Ver ``UserDataContribution.deletion_models``. Por
                defecto, ninguna categoría del aviso.
            export_tables: Ver ``UserDataContribution.export_tables``. Por
                defecto, ninguna tabla.
            priority: Ver ``UserDataContribution.priority``. Por defecto ``100``.
        """
        contribution = UserDataContribution(
            name=name,
            purge=purge,
            deletion_models=dict(deletion_models or {}),
            export_tables=tuple(export_tables),
            priority=priority,
        )
        with cls._lock:
            cls._contributions[name] = contribution

    @classmethod
    def contributions(cls) -> list[UserDataContribution]:
        """Devuelve los módulos registrados, en orden de purga.

        Returns:
            list[UserDataContribution]: Ordenados por ``priority`` y, a igual
                prioridad, por ``name``, para que el orden no dependa de qué
                módulo se importó antes.
        """
        with cls._lock:
            return sorted(cls._contributions.values(), key=lambda item: (item.priority, item.name))
