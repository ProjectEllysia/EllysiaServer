"""
Cálculo del cumplimiento de un marco a partir de las evaluaciones de sus controles.

Puro: no toca base de datos ni red. Recibe la versión del catálogo y el estado de cada
control y devuelve cuánto falta, por rama y en global.

La regla que más importa: los controles «no aplica» **no cuentan ni a favor ni en contra**.
El porcentaje es ``implementados / (evaluables − no aplica)``; si contarlos como pendientes
el porcentaje engañaría hacia abajo y si los contara como hechos, hacia arriba.
"""

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional

from ..model import (
    ASSESSMENT_STATUSES,
    STATUS_IMPLEMENTED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_APPLICABLE,
    STATUS_PENDING,
)
from .catalog import CatalogNode, FrameworkVersion


@dataclass(frozen=True)
class ControlState:
    """Lo que el cálculo necesita saber de la evaluación de un control.

    Attributes:
        status: Uno de ``ASSESSMENT_STATUSES``.
        due_date: Fecha límite, o ``None``.
        responsible_user_id: Responsable, o ``None``.
    """

    status: str = STATUS_PENDING
    due_date: Optional[date] = None
    responsible_user_id: Optional[int] = None


def progress_of(counts: Mapping[str, int]) -> dict:
    """Convierte un recuento por estado en el progreso de una rama.

    Args:
        counts: Cuántos controles hay en cada estado de ``ASSESSMENT_STATUSES``.

    Returns:
        dict: ``counts`` (los cuatro estados), ``total`` (todos los evaluables),
            ``countable`` (los que cuentan: sin los «no aplica») y ``percent`` (0 a 100, con un
            decimal). Con ``countable`` igual a 0 el porcentaje es 0.0, nunca una división por
            cero.
    """
    normalized = {status: int(counts.get(status, 0)) for status in ASSESSMENT_STATUSES}
    total = sum(normalized.values())
    countable = total - normalized[STATUS_NOT_APPLICABLE]
    percent = round(100 * normalized[STATUS_IMPLEMENTED] / countable, 1) if countable else 0.0
    return {"counts": normalized, "total": total, "countable": countable, "percent": percent}


def _branch_counts(version: FrameworkVersion, node: CatalogNode, states: Mapping[str, ControlState],
                   cache: dict[str, dict[str, int]]) -> dict[str, int]:
    """Recuento por estado de los controles evaluables bajo un nodo (él incluido)."""
    counts = {status: 0 for status in ASSESSMENT_STATUSES}
    if node.is_assessable:
        counts[states.get(node.identifier, ControlState()).status] += 1
    for child in version.children(node.code):
        for status, amount in _branch_counts(version, child, states, cache).items():
            counts[status] += amount
    cache[node.code] = counts
    return counts


def branch_progress(version: FrameworkVersion, states: Mapping[str, ControlState]) -> dict[str, dict]:
    """Calcula el progreso de **todos** los nodos de una versión en una sola pasada.

    Args:
        version: La versión del catálogo adoptada.
        states: Estado de cada control evaluado, por identificador. Un control que no aparece
            está «pendiente».

    Returns:
        dict[str, dict]: Por código de nodo, lo que devuelve ``progress_of``. Incluye a los
            grupos, que agregan el estado de sus hijos.
    """
    cache: dict[str, dict[str, int]] = {}
    for root in version.children(None):
        _branch_counts(version, root, states, cache)
    return {code: progress_of(counts) for code, counts in cache.items()}


def summarize(version: FrameworkVersion, states: Mapping[str, ControlState], today: date,
              horizon_days: int = 30, limit: int = 10) -> dict:
    """Resume el cumplimiento de un marco: global, por rama, vencimientos y sin responsable.

    Args:
        version: La versión del catálogo adoptada.
        states: Estado de cada control evaluado, por identificador.
        today: El día de referencia para los vencimientos.
        horizon_days: A cuántos días vista se considera «próximo» un vencimiento. Por defecto 30.
        limit: Máximo de controles en cada lista. Por defecto 10.

    Returns:
        dict: ``global`` (``progress_of``), ``branches`` (una entrada por raíz con ``code``,
            ``identifier``, ``title`` y su progreso), ``upcoming`` (controles abiertos con fecha
            límite vencida o dentro del horizonte, por fecha), ``unassigned`` (controles
            abiertos sin responsable) y ``unassignedCount``. Un control «abierto» es el que
            no está ni implementado ni «no aplica».
    """
    progress = branch_progress(version, states)
    roots = version.children(None)

    global_counts = {status: 0 for status in ASSESSMENT_STATUSES}
    for root in roots:
        for status, amount in progress[root.code]["counts"].items():
            global_counts[status] += amount

    open_statuses = (STATUS_PENDING, STATUS_IN_PROGRESS)
    upcoming, unassigned = [], []
    for node in version.assessable_nodes():
        state = states.get(node.identifier, ControlState())
        if state.status not in open_statuses:
            continue
        entry = {"code": node.code, "identifier": node.identifier, "title": node.title,
                 "status": state.status, "dueDate": state.due_date,
                 "responsibleUserId": state.responsible_user_id}
        if state.due_date is not None and (state.due_date - today).days <= horizon_days:
            upcoming.append({**entry, "isOverdue": state.due_date < today})
        if state.responsible_user_id is None:
            unassigned.append(entry)

    upcoming.sort(key=lambda item: item["dueDate"])
    return {
        "global": progress_of(global_counts),
        "branches": [
            {"code": root.code, "identifier": root.identifier, "title": root.title, **progress[root.code]}
            for root in roots
        ],
        "upcoming": upcoming[:limit],
        "unassigned": unassigned[:limit],
        "unassignedCount": len(unassigned),
    }
