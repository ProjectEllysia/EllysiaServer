"""
Correspondencias entre dos versiones de un mismo marco: qué control nuevo corresponde a cada
control viejo.

Entre dos versiones los controles no se limitan a cambiar de nombre (ISO 27001 pasó de 114 a 93
controles entre 2013 y 2022: fusionó varios, dividió alguno y añadió 11). Para no perder el
trabajo de un usuario al cambiar de versión hay que saber, control a control, cómo se
relacionan. Van en un fichero aparte de las versiones, porque una versión publicada no se
modifica.

Fichero ``catalog/<marco>/mappings/<origen>__<destino>.json``::

    {"framework": "iso27001", "from": "2013", "to": "2022",
     "mappings": [{"from": "A.9.1.1", "to": "A.5.15", "relation": "equivalent", "note": "..."}]}

Cada entrada une **un** control de origen con **uno** de destino:

* ``equivalent``: el mismo control con otro código o redacción.
* ``split``: un origen aparece en varias entradas, una por destino.
* ``merged``: varios orígenes apuntan al mismo destino.
* ``retired``: el origen desaparece sin sustituto (``to`` es ``null``).
* ``new``: el destino aparece sin antecedente (``from`` es ``null``).

La relación tiene que ser **completa**: todo control evaluable de origen aparece al menos una
vez y todo control evaluable de destino también.

Puro: no toca base de datos ni red.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .catalog import CATALOG_ROOT, CatalogFormatError, FrameworkVersion, load_version

RELATION_EQUIVALENT = "equivalent"
RELATION_SPLIT = "split"
RELATION_MERGED = "merged"
RELATION_RETIRED = "retired"
RELATION_NEW = "new"
_RELATIONS = (RELATION_EQUIVALENT, RELATION_SPLIT, RELATION_MERGED, RELATION_RETIRED, RELATION_NEW)


@dataclass(frozen=True)
class Correspondence:
    """Una línea de correspondencia entre dos versiones.

    Attributes:
        source: Identificador del control de origen, o ``None`` si es nuevo.
        target: Identificador del control de destino, o ``None`` si se retiró.
        relation: Una de ``equivalent``, ``split``, ``merged``, ``retired`` o ``new``.
        note: Matiz para quien revisa el cambio; vacío si no hay.
    """

    source: Optional[str]
    target: Optional[str]
    relation: str
    note: str


@dataclass(frozen=True)
class VersionMapping:
    """Las correspondencias ya validadas entre dos versiones de un marco.

    Attributes:
        framework: Clave del marco.
        from_version: Versión de origen.
        to_version: Versión de destino.
        entries: Las líneas, en el orden del fichero.
    """

    framework: str
    from_version: str
    to_version: str
    entries: tuple[Correspondence, ...]

    def targets_of(self, source: str) -> tuple[Correspondence, ...]:
        """Las líneas cuyo origen es un control (varias si se dividió)."""
        return tuple(entry for entry in self.entries if entry.source == source)

    def sources_of(self, target: str) -> tuple[Correspondence, ...]:
        """Las líneas cuyo destino es un control (varias si se fusionaron)."""
        return tuple(entry for entry in self.entries if entry.target == target)

    def is_complete_for_translation(self) -> bool:
        """Siempre ``True`` en un mapeo validado; existe para dejar dicho el contrato."""
        return True


def parse_mapping(document: dict, source: FrameworkVersion, target: FrameworkVersion) -> VersionMapping:
    """Valida un fichero de correspondencias contra las dos versiones que relaciona.

    Args:
        document: El JSON ya cargado.
        source: La versión de origen.
        target: La versión de destino.

    Returns:
        VersionMapping: Las correspondencias, ya validadas.

    Raises:
        CatalogFormatError: Si una referencia no existe, si falta algún control evaluable de
            origen o de destino, o si una relación es incoherente con sus extremos.
    """
    where = f"{source.key}/{source.version}__{target.version}"
    if document.get("framework") != source.key or document.get("from") != source.version \
            or document.get("to") != target.version:
        raise CatalogFormatError(f"{where}: la cabecera no corresponde a las versiones que relaciona")

    entries: list[Correspondence] = []
    for position, raw in enumerate(document.get("mappings", [])):
        relation = raw.get("relation")
        if relation not in _RELATIONS:
            raise CatalogFormatError(f"{where}: la entrada {position} tiene una relación desconocida")
        origin, destination = raw.get("from"), raw.get("to")
        if relation == RELATION_NEW and (origin is not None or destination is None):
            raise CatalogFormatError(f"{where}: «new» lleva destino y no origen (entrada {position})")
        if relation == RELATION_RETIRED and (destination is not None or origin is None):
            raise CatalogFormatError(f"{where}: «retired» lleva origen y no destino (entrada {position})")
        if relation in (RELATION_EQUIVALENT, RELATION_SPLIT, RELATION_MERGED) and (origin is None or destination is None):
            raise CatalogFormatError(f"{where}: «{relation}» lleva origen y destino (entrada {position})")
        if origin is not None and source.node(f"{source.key}:{origin}") is None:
            raise CatalogFormatError(f"{where}: el origen «{origin}» no existe en {source.version}")
        if destination is not None and target.node(f"{target.key}:{destination}") is None:
            raise CatalogFormatError(f"{where}: el destino «{destination}» no existe en {target.version}")
        entries.append(Correspondence(origin, destination, relation, raw.get("note", "")))

    covered_sources = {entry.source for entry in entries if entry.source is not None}
    covered_targets = {entry.target for entry in entries if entry.target is not None}
    missing_sources = [n.identifier for n in source.assessable_nodes() if n.identifier not in covered_sources]
    missing_targets = [n.identifier for n in target.assessable_nodes() if n.identifier not in covered_targets]
    if missing_sources:
        raise CatalogFormatError(f"{where}: controles de origen sin correspondencia: {missing_sources[:10]}")
    if missing_targets:
        raise CatalogFormatError(f"{where}: controles de destino sin correspondencia: {missing_targets[:10]}")
    return VersionMapping(source.key, source.version, target.version, tuple(entries))


@lru_cache(maxsize=None)
def _load(root: str, key: str, from_version: str, to_version: str) -> Optional[VersionMapping]:
    path = Path(root) / key / "mappings" / f"{from_version}__{to_version}.json"
    if not path.exists():
        return None
    source = load_version(key, from_version, Path(root))
    target = load_version(key, to_version, Path(root))
    if source is None or target is None:
        return None
    return parse_mapping(json.loads(path.read_text(encoding="utf-8")), source, target)


def load_mapping(key: str, from_version: str, to_version: str, root: Path = CATALOG_ROOT) -> Optional[VersionMapping]:
    """Carga y valida las correspondencias entre dos versiones de un marco.

    Args:
        key: Clave del marco.
        from_version: Versión de origen.
        to_version: Versión de destino.
        root: Carpeta del catálogo. Por defecto, la que viaja con el código.

    Returns:
        Optional[VersionMapping]: Las correspondencias, o ``None`` si no hay fichero para ese
            par (o alguna de las versiones no existe).

    Raises:
        CatalogFormatError: Si el fichero existe y no es válido.
    """
    return _load(str(root), key, from_version, to_version)


def translate_control(key: str, identifier: str, from_version: str, to_version: str,
                      root: Path = CATALOG_ROOT) -> list[Correspondence]:
    """Dice a qué controles de otra versión corresponde un control.

    Es lo que usa quien guarda un código de una versión (Lybra apunta a una) y necesita el de la
    que el usuario tiene adoptada.

    Args:
        key: Clave del marco.
        identifier: Identificador del control en ``from_version``.
        from_version: Versión en la que está el identificador.
        to_version: Versión a la que se quiere traducir.
        root: Carpeta del catálogo.

    Returns:
        list[Correspondence]: Las líneas del control; una sola ``equivalent`` si las dos
            versiones son la misma; vacía si no hay correspondencias para ese par.
    """
    if from_version == to_version:
        return [Correspondence(identifier, identifier, RELATION_EQUIVALENT, "")]
    mapping = load_mapping(key, from_version, to_version, root)
    return list(mapping.targets_of(identifier)) if mapping else []
