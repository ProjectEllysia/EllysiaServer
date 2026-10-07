"""
Descripción de lo que un módulo entrega en la exportación de los datos de un usuario.

Cada módulo de feature declara, junto a sus modelos, qué tablas guardan datos de
un usuario y cuáles de sus columnas **no** deben salir (credenciales, secretos,
rutas internas del servidor). El módulo ``users`` recoge esas declaraciones y
escribe el archivo; no necesita saber nada de las tablas de los demás.

Vive en ``shared`` para que un módulo de feature pueda declarar sus tablas sin
importar ``users`` (que depende de ellos, no al revés).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select


@dataclass(frozen=True)
class ExportTable:
    """Una tabla cuyas filas, de un usuario, entran en su exportación de datos.

    Attributes:
        name: Clave bajo la que sus filas aparecen en el JSON del módulo
            (``"scans"``). Única dentro del módulo.
        model: Modelo SQLAlchemy. Si es la base de una herencia, cada fila sale
            con las columnas de su subclase.
        scope: Función que recibe el id del usuario y devuelve la condición que
            deja solo sus filas. Para una tabla con ``user_id`` es
            ``owned_by(Modelo.user_id)``; para una tabla hija, una subconsulta
            sobre su padre.
        exclude: Atributos del modelo que no salen en el archivo. Aquí van las
            credenciales, los secretos y las rutas de ficheros del servidor.
            Por defecto, ninguno.
    """

    name: str
    model: type
    scope: Callable[[int], Any]
    exclude: frozenset[str] = field(default_factory=frozenset)


def owned_by(column: Any) -> Callable[[int], Any]:
    """Alcance de una tabla que guarda el id de su dueño en una columna.

    Args:
        column: La columna del modelo que apunta al usuario
            (``Scan.user_id``).

    Returns:
        Callable[[int], Any]: Función que, dado el id del usuario, devuelve la
            condición ``column == user_id``.
    """
    return lambda user_id: column == user_id


def owned_through(column: Any, parent_id: Any, parent_owner: Any) -> Callable[[int], Any]:
    """Alcance de una tabla hija: sus filas son del usuario si lo es su fila padre.

    Args:
        column: La columna del hijo que apunta al padre (``Finding.scan_id``).
        parent_id: La clave primaria del padre (``Scan.id``).
        parent_owner: La columna del padre que apunta al usuario (``Scan.user_id``).

    Returns:
        Callable[[int], Any]: Función que, dado el id del usuario, devuelve la
            condición «el padre de esta fila es de ese usuario».
    """
    return lambda user_id: column.in_(select(parent_id).where(parent_owner == user_id))
