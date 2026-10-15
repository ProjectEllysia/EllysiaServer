"""
Qué controles de un marco se exigen según la categoría del sistema.

El ENS no pide lo mismo a todos los sistemas: el anexo II del Real Decreto 311/2022 dice, medida
a medida, qué se exige en categoría básica, media y alta. El catálogo guarda esa fila en
``metadata.categories`` de cada medida, con uno de estos valores por categoría:

* ``"n.a."``: la medida no se exige.
* ``"aplica"``: se exige la medida sola.
* ``"+ R1 + R2"``: se exige la medida y esos refuerzos.
* ``"+ [R1 o R2 o R3 o R4] + R8"``: además, basta **uno** de los refuerzos entre corchetes.

Un refuerzo es el hijo de una medida cuyo identificador acaba en ``.r<n>``
(``op.acc.6.r5`` es el R5 de ``op.acc.6``), y se exige si su medida lo cita en la columna de la
categoría. Un refuerzo que su medida no cita en ninguna columna es opcional en las tres.

Las medidas que dependen de una dimensión de seguridad (confidencialidad, integridad…) se leen
con la categoría del sistema, que es el nivel más alto de sus dimensiones: guardar el nivel de
cada dimensión sería más fiel, pero el usuario no lo tiene a mano y la categoría sí.

Puro: no toca base de datos ni red.
"""

import re
from typing import Mapping, Optional

from .catalog import FrameworkVersion

#: Las categorías del sistema, en el orden del anexo II: las claves de ``metadata.categories``.
CATEGORIES = ("basic", "medium", "high")

#: Se exige en la categoría del sistema y cuenta en el cumplimiento.
REQUIRED = "required"
#: Es una de varias opciones de las que basta una; no cuenta (la cuenta su medida).
ALTERNATIVE = "alternative"
#: No se exige en la categoría del sistema; no cuenta.
NOT_REQUIRED = "not_required"
#: Refuerzo que el anexo II no exige en ninguna categoría; no cuenta.
OPTIONAL = "optional"

_NOT_APPLICABLE = "n.a."
_ALTERNATIVES = re.compile(r"\[([^\]]*)\]")
_REINFORCEMENT = re.compile(r"R(\d+)")


def categories_of(version: FrameworkVersion) -> tuple[str, ...]:
    """Las categorías de sistema que admite una versión.

    Args:
        version: Versión del catálogo.

    Returns:
        tuple[str, ...]: ``CATEGORIES`` si algún nodo trae ``metadata.categories`` (hoy, el ENS);
            vacía si el marco no distingue categorías.
    """
    return CATEGORIES if any("categories" in node.metadata for node in version.nodes) else ()


def _cited(row: str) -> tuple[set[int], set[int]]:
    """Los refuerzos que cita una celda del anexo II: los exigidos y los alternativos."""
    alternatives = {int(number) for group in _ALTERNATIVES.findall(row) for number in _REINFORCEMENT.findall(group)}
    required = {int(number) for number in _REINFORCEMENT.findall(_ALTERNATIVES.sub("", row))}
    return required, alternatives


def applicability(version: FrameworkVersion, category: Optional[str]) -> dict[str, str]:
    """Clasifica los controles evaluables de una versión según la categoría del sistema.

    Args:
        version: Versión del catálogo adoptada.
        category: Categoría del sistema, una de ``CATEGORIES``, o ``None`` si no se ha elegido.

    Returns:
        dict[str, str]: Por identificador, ``REQUIRED``, ``ALTERNATIVE``, ``NOT_REQUIRED`` u
            ``OPTIONAL``. Vacío si ``category`` es ``None`` o el marco no distingue categorías:
            entonces todo se exige, que es lo que asume quien lo lea con ``is_required``.
    """
    if category is None or not categories_of(version):
        return {}
    scope: dict[str, str] = {}
    for node in version.assessable_nodes():
        rows: Mapping[str, str] = node.metadata.get("categories") or {}
        if rows:
            scope[node.identifier] = NOT_REQUIRED if rows.get(category, "").strip() == _NOT_APPLICABLE else REQUIRED
            continue
        parent = version.node(node.parent) if node.parent else None
        match = re.fullmatch(re.escape(parent.identifier) + r"\.r(\d+)", node.identifier) if parent else None
        parent_rows: Mapping[str, str] = parent.metadata.get("categories") or {} if parent else {}
        if match is None or not parent_rows:
            scope[node.identifier] = REQUIRED
            continue
        number = int(match.group(1))
        if not any(number in set.union(*_cited(row)) for row in parent_rows.values()):
            scope[node.identifier] = OPTIONAL
            continue
        row = parent_rows.get(category, "")
        required, alternatives = _cited(row)
        if row.strip() == _NOT_APPLICABLE:
            scope[node.identifier] = NOT_REQUIRED
        elif number in required:
            scope[node.identifier] = REQUIRED
        elif number in alternatives:
            scope[node.identifier] = ALTERNATIVE
        else:
            scope[node.identifier] = NOT_REQUIRED
    return scope


def is_required(scope: Mapping[str, str], identifier: str) -> bool:
    """Si un control cuenta en el cumplimiento: lo que no aparece en ``scope`` se exige."""
    return scope.get(identifier, REQUIRED) == REQUIRED
