"""Fin de soporte del fabricante, por producto y rama de versión.

La correlación de vulnerabilidades (``kb.py`` + ``applicability.py``) cruza un
producto y una versión contra las CVE ya publicadas. Eso deja un hueco: el fin
de soporte **no es una vulnerabilidad**, es una fecha, y por eso ninguna base
de datos de CVEs la recoge. Un producto sin ninguna CVE catalogada hoy pasa el
informe limpio aunque el fabricante haya dejado de darle parches — y cualquier
fallo que se descubra a partir de ahora se queda sin corregir para siempre.

Módulo puro, igual que ``applicability.py``: sin ORM y sin red. El catálogo es
un fichero curado (``feeds/eol_catalog.json``), una instantánea versionada en
vez de una tabla con su propia sincronización — las fechas de fin de soporte
casi no cambian, y una tabla con migración y sincronización propia sería
mecanismo de sobra para un puñado de fechas por producto. Se refresca a mano
con ``scripts/refresh_eol_catalog.py`` contra la API pública de
``endoflife.date``, igual de espíritu que el resto de los feeds de este
paquete (alias de producto, patrones de ``sysDescr``…): un fichero que se edita
fuera del código, no una llamada de red en cada escaneo.

**Encaje de la versión en una rama.** El catálogo lista las ramas de cada
producto por su ``cycle`` (``"1.29"``, ``"18"``, ``"9.6"``…): el mismo
prefijo que ``endoflife.date`` usa para agrupar versiones. Una versión
concreta (``"1.29.8"``) se encaja probando sus prefijos de más específico a
menos (``"1.29.8"``, ``"1.29"``, ``"1"``) contra la lista de ramas del
producto y quedándose con el primero que exista — no hace falta comparar
rangos numéricos, el propio catálogo ya separa una rama de otra por ese
prefijo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

_BUNDLED_CATALOG = Path(__file__).parent / "feeds" / "eol_catalog.json"


@dataclass(frozen=True)
class EolStatus:
    """El estado de fin de soporte de la rama de versión de un producto.

    Attributes:
        cycle: La rama a la que se encajó la versión consultada (``"1.29"``).
        eol_date: La fecha en la que el fabricante deja (o dejó) de mantener
            esa rama.
        is_past: ``True`` si ``eol_date`` ya pasó respecto al instante contra
            el que se consultó. Una rama con fecha de fin de soporte futura
            **no** es un hallazgo: sigue mantenida hoy.
    """
    cycle: str
    eol_date: date
    is_past: bool


@lru_cache(maxsize=1)
def load_eol_catalog(path: Optional[str] = None) -> Dict[str, List[dict]]:
    """Carga el catálogo de fin de soporte.

    Args:
        path: Ruta a otro catálogo. Por defecto, ``None``: el que acompaña al
            módulo.

    Returns:
        dict: ``{"vendor:product": [{"cycle": str, "eol": str | None}, ...]}``,
        con la misma clave ``vendor:product`` que ``feeds/cve_applicability.json``
        y ``feeds/product_aliases.json`` ya usan.
    """
    catalog_path = Path(path) if path else _BUNDLED_CATALOG
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    return data.get("products", {})


def _parse_eol_date(value) -> Optional[date]:
    """Interpreta el campo ``eol`` de una rama del catálogo.

    Args:
        value: ``False`` (sin fecha conocida de fin de soporte: la rama es de
            desarrollo continuo, "rolling"), o una fecha ``"YYYY-MM-DD"``.

    Returns:
        date | None: La fecha, o ``None`` si el valor no es una fecha (incluye
        ``False`` y cualquier texto no parseable, que se trata como "no hay
        fecha" en vez de hacer fallar el escaneo por una entrada rara del feed).
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def cycle_for_version(version: str, cycles) -> Optional[str]:
    """Encaja una versión concreta en la rama más específica que el catálogo tenga.

    Args:
        version: La versión detectada (``"1.29.8"``, ``"18.6"``).
        cycles: Los nombres de rama disponibles para el producto.

    Returns:
        str | None: La rama, o ``None`` si ningún prefijo de ``version``
        coincide con ninguna rama conocida.
    """
    known = set(cycles)
    components = version.strip().split(".")
    for length in range(len(components), 0, -1):
        candidate = ".".join(components[:length])
        if candidate in known:
            return candidate
    return None


def check_end_of_life(vendor: str, product: str, version: str,
                      as_of: Optional[date] = None,
                      catalog: Optional[Dict[str, List[dict]]] = None) -> Optional[EolStatus]:
    """Dice si la rama de un producto y versión está fuera de soporte.

    Args:
        vendor: El vendor del CPE (``"nginx"``, ``"postgresql"``).
        product: El producto del CPE (``"nginx"``, ``"postgresql"``).
        version: La versión detectada.
        as_of: El instante contra el que se juzga el fin de soporte.
            Inyectable para que un test no dependa del reloj; por defecto,
            ``None``, que resuelve a la fecha de hoy.
        catalog: El catálogo a consultar. Por defecto, ``None``: el que
            acompaña al módulo (:func:`load_eol_catalog`).

    Returns:
        EolStatus | None: El estado, o ``None`` si el producto no está en el
        catálogo, la versión no encaja en ninguna rama conocida, o la rama no
        tiene fecha de fin de soporte (desarrollo continuo).
    """
    branches = (catalog if catalog is not None else load_eol_catalog()).get(f"{vendor}:{product}")
    if not branches:
        return None
    by_cycle = {branch["cycle"]: branch for branch in branches}
    cycle = cycle_for_version(version, by_cycle)
    if cycle is None:
        return None
    eol_date = _parse_eol_date(by_cycle[cycle].get("eol"))
    if eol_date is None:
        return None
    moment = as_of or date.today()
    return EolStatus(cycle=cycle, eol_date=eol_date, is_past=moment >= eol_date)


def validate_eol_catalog(catalog: Optional[Dict[str, List[dict]]] = None) -> List[str]:
    """Comprueba que el catálogo tiene la forma esperada.

    Args:
        catalog: El catálogo a validar. Por defecto, ``None``: el que
            acompaña al módulo.

    Returns:
        list[str]: Un problema por entrada mal formada; vacía si todo encaja.
    """
    problems: List[str] = []
    data = catalog if catalog is not None else load_eol_catalog()
    for key, branches in data.items():
        if ":" not in key:
            problems.append(f"Clave {key!r}: debe ser \"vendor:product\"")
        seen_cycles: set = set()
        for branch in branches:
            cycle = branch.get("cycle")
            if not cycle or not isinstance(cycle, str):
                problems.append(f"{key}: una rama sin 'cycle' válido")
                continue
            if cycle in seen_cycles:
                problems.append(f"{key}: la rama {cycle!r} aparece más de una vez")
            seen_cycles.add(cycle)
            eol = branch.get("eol")
            if eol is not False and not (isinstance(eol, str) and _parse_eol_date(eol)):
                problems.append(f"{key} ({cycle}): 'eol' debe ser false o \"YYYY-MM-DD\"")
    return problems
