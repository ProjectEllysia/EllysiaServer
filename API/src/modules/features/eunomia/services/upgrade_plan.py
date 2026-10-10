"""
Qué se traslada, qué hay que revisar y qué se pierde al pasar un marco a otra versión.

Con las correspondencias entre versiones (``version_mappings``) casi todo el trabajo hecho se
puede trasladar, pero no a ciegas: si un control se divide en tres, el «implementado» no vale
sin más para los tres, y si varios se fusionan en uno, la evaluación del destino no puede ser
mejor que la de sus orígenes. El plan traslada lo seguro y pide revisión de lo que no lo es.

Puro: no toca base de datos ni red.
"""

from dataclasses import dataclass, field
from typing import Mapping

from .version_mappings import RELATION_EQUIVALENT, RELATION_NEW, RELATION_RETIRED, VersionMapping

#: Reglas para combinar las evaluaciones de varios orígenes en un destino fusionado.
_STATUS_IMPLEMENTED = "implemented"
_STATUS_NOT_APPLICABLE = "not_applicable"
_STATUS_IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class Move:
    """Una evaluación que pasa al control de destino.

    Attributes:
        target: Identificador del control en la versión nueva.
        sources: Identificadores de origen de los que sale (varios si se fusionaron).
        status: Estado que toma en el destino.
        reason: ``"equivalent"``, ``"split"`` o ``"merged"``.
        needs_review: Si hay que pedir revisión (todo menos un equivalente uno a uno).
    """

    target: str
    sources: tuple[str, ...]
    status: str
    reason: str
    needs_review: bool


@dataclass(frozen=True)
class UpgradePlan:
    """El resultado de planificar un cambio de versión.

    Attributes:
        moves: Lo que se traslada, con su estado en el destino.
        lost: Orígenes evaluados cuyo control se retira sin sustituto, con su estado.
        new_controls: Controles de la versión nueva sin antecedente: quedan pendientes.
        link_moves: Pares ``(origen, destino)`` a los que hay que mover los enlaces de
            evidencias; lo que apuntaba a un retirado se pierde.
    """

    moves: tuple[Move, ...] = ()
    lost: tuple[tuple[str, str], ...] = ()
    new_controls: tuple[str, ...] = ()
    link_moves: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _merged_status(statuses: list[str]) -> str:
    """El estado de un destino fusionado: nunca mejor que el de sus orígenes."""
    if all(status == _STATUS_IMPLEMENTED for status in statuses):
        return _STATUS_IMPLEMENTED
    if all(status == _STATUS_NOT_APPLICABLE for status in statuses):
        return _STATUS_NOT_APPLICABLE
    return _STATUS_IN_PROGRESS


def plan_upgrade(mapping: VersionMapping, statuses: Mapping[str, str], linked: set[str]) -> UpgradePlan:
    """Planifica el traslado de las evaluaciones y los enlaces de una versión a otra.

    Args:
        mapping: Correspondencias validadas entre las dos versiones.
        statuses: Estado de cada control evaluado de la versión de origen, por identificador.
        linked: Identificadores de origen que tienen evidencias enlazadas.

    Returns:
        UpgradePlan: Lo que se traslada, lo que se pierde, lo nuevo y los enlaces a mover.
    """
    targets_of: dict[str, list] = {}
    sources_of: dict[str, list] = {}
    for entry in mapping.entries:
        if entry.source is not None and entry.target is not None:
            targets_of.setdefault(entry.source, []).append(entry)
            sources_of.setdefault(entry.target, []).append(entry)

    moves: list[Move] = []
    for target, entries in sources_of.items():
        assessed = [entry.source for entry in entries if entry.source in statuses]
        if not assessed:
            continue
        one_to_one = (
            len(entries) == 1 and entries[0].relation == RELATION_EQUIVALENT
            and len(targets_of[entries[0].source]) == 1
        )
        if one_to_one:
            moves.append(Move(target, (assessed[0],), statuses[assessed[0]], RELATION_EQUIVALENT, False))
        else:
            reason = "merged" if len(entries) > 1 else "split"
            # Un origen sin evaluar cuenta como pendiente: el destino no puede ser mejor que él.
            status = _merged_status([statuses.get(entry.source, "pending") for entry in entries])
            moves.append(Move(target, tuple(assessed), status, reason, True))

    lost = tuple(
        (entry.source, statuses[entry.source]) for entry in mapping.entries
        if entry.relation == RELATION_RETIRED and entry.source in statuses
    )
    new_controls = tuple(entry.target for entry in mapping.entries if entry.relation == RELATION_NEW)
    link_moves = tuple(
        (entry.source, entry.target) for entry in mapping.entries
        if entry.source in linked and entry.target is not None
    )
    return UpgradePlan(tuple(moves), lost, new_controls, link_moves)
