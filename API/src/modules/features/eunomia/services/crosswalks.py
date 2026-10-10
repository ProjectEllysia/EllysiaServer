"""
Correspondencias entre marcos: lo que se cumple en uno cuenta, como sugerencia, en otro.

Una empresa que ya cumple el ENS tiene hecha buena parte de NIS2; una certificada en ISO 27001,
también. Decírselo control a control ahorra semanas. Pero entre marcos distintos los controles
rara vez son idénticos: solo se solapan. Por eso estas correspondencias **sugieren y nunca
trasladan**: no copian una evaluación, enseñan qué tiene hecho el usuario en el otro marco.

Fichero ``catalog/crosswalks/<marcoA>@<versión>__<marcoB>@<versión>.json``::

    {"a": {"framework": "nis2", "version": "2022-2555"},
     "b": {"framework": "ens", "version": "rd-311-2022"},
     "links": [{"from": "RE.11.1", "to": "op.acc.2", "coverage": "full"}]}

``from`` es un control de ``a`` y ``to`` uno de ``b``; la relación se consulta desde cualquiera de
los dos lados. ``coverage`` es ``full`` (cumplir uno cubre en lo esencial al otro) o ``partial``
(lo cubre en parte).

Puro: no toca base de datos ni red.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .catalog import CATALOG_ROOT, CatalogFormatError, load_version

COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
_COVERAGES = (COVERAGE_FULL, COVERAGE_PARTIAL)


@dataclass(frozen=True)
class Suggestion:
    """Un control de otro marco que cubre, total o parcialmente, el que se mira.

    Attributes:
        framework: Clave del otro marco.
        version: Versión de ese marco en la que está el control.
        identifier: Identificador del control en el otro marco.
        coverage: ``"full"`` o ``"partial"``.
    """

    framework: str
    version: str
    identifier: str
    coverage: str


@dataclass(frozen=True)
class Crosswalk:
    """Las correspondencias ya validadas entre dos marcos en dos versiones.

    Attributes:
        a_framework: Clave del primer marco.
        a_version: Versión del primer marco.
        b_framework: Clave del segundo marco.
        b_version: Versión del segundo marco.
        links: Tuplas ``(identificador en a, identificador en b, cobertura)``.
    """

    a_framework: str
    a_version: str
    b_framework: str
    b_version: str
    links: tuple[tuple[str, str, str], ...]

    def suggestions_for(self, framework: str, identifier: str) -> list[Suggestion]:
        """Los controles del otro marco que se solapan con uno de este.

        Args:
            framework: Clave del marco al que pertenece el control (uno de los dos).
            identifier: Identificador del control.

        Returns:
            list[Suggestion]: Las del otro lado; vacía si el marco no es de este fichero o el
                control no tiene correspondencias.
        """
        if framework == self.a_framework:
            return [Suggestion(self.b_framework, self.b_version, to, coverage)
                    for origin, to, coverage in self.links if origin == identifier]
        if framework == self.b_framework:
            return [Suggestion(self.a_framework, self.a_version, origin, coverage)
                    for origin, to, coverage in self.links if to == identifier]
        return []


def parse_crosswalk(document: dict, root: Path = CATALOG_ROOT) -> Crosswalk:
    """Valida un fichero de correspondencias entre marcos contra las versiones que relaciona.

    Args:
        document: El JSON ya cargado.
        root: Carpeta del catálogo, para cargar las dos versiones.

    Returns:
        Crosswalk: Las correspondencias validadas.

    Raises:
        CatalogFormatError: Si una versión no existe, si un control no existe o no es evaluable,
            o si una cobertura es desconocida.
    """
    a, b = document.get("a", {}), document.get("b", {})
    version_a = load_version(a.get("framework", ""), a.get("version", ""), root)
    version_b = load_version(b.get("framework", ""), b.get("version", ""), root)
    where = f"{a.get('framework')}@{a.get('version')}__{b.get('framework')}@{b.get('version')}"
    if version_a is None or version_b is None:
        raise CatalogFormatError(f"{where}: alguna de las dos versiones no existe en el catálogo")
    links: list[tuple[str, str, str]] = []
    for position, raw in enumerate(document.get("links", [])):
        origin, to, coverage = raw.get("from"), raw.get("to"), raw.get("coverage")
        if coverage not in _COVERAGES:
            raise CatalogFormatError(f"{where}: la entrada {position} tiene una cobertura desconocida")
        for version, identifier in ((version_a, origin), (version_b, to)):
            node = version.node(f"{version.key}:{identifier}")
            if node is None:
                raise CatalogFormatError(f"{where}: «{identifier}» no existe en {version.key}@{version.version}")
            if not node.is_assessable:
                raise CatalogFormatError(f"{where}: «{identifier}» no es evaluable")
        links.append((origin, to, coverage))
    return Crosswalk(version_a.key, version_a.version, version_b.key, version_b.version, tuple(links))


@lru_cache(maxsize=None)
def _load_all(root: str) -> tuple[Crosswalk, ...]:
    folder = Path(root) / "crosswalks"
    if not folder.is_dir():
        return ()
    return tuple(
        parse_crosswalk(json.loads(path.read_text(encoding="utf-8")), Path(root))
        for path in sorted(folder.glob("*.json"))
    )


def load_crosswalks(root: Path = CATALOG_ROOT) -> tuple[Crosswalk, ...]:
    """Carga y valida todas las correspondencias entre marcos del catálogo.

    Args:
        root: Carpeta del catálogo.

    Returns:
        tuple[Crosswalk, ...]: Una por fichero de ``crosswalks/``, en orden de nombre.
    """
    return _load_all(str(root))


def suggestions(framework: str, version: str, identifier: str, adopted: dict[str, str],
                root: Path = CATALOG_ROOT) -> list[Suggestion]:
    """Los controles de los **otros marcos adoptados** que se solapan con un control.

    Solo cuenta lo que el usuario puede usar: un marco no adoptado no se sugiere, y se mira la
    versión adoptada de cada uno, no la vigente.

    Args:
        framework: Clave del marco del control.
        version: Versión adoptada de ese marco.
        identifier: Identificador del control.
        adopted: ``{marco: versión adoptada}`` de los marcos activos del dueño efectivo.
        root: Carpeta del catálogo.

    Returns:
        list[Suggestion]: Sin repetidos, en el orden de los ficheros.
    """
    found: list[Suggestion] = []
    for crosswalk in load_crosswalks(root):
        own_version = crosswalk.a_version if crosswalk.a_framework == framework else crosswalk.b_version
        if framework not in (crosswalk.a_framework, crosswalk.b_framework) or own_version != version:
            continue
        for suggestion in crosswalk.suggestions_for(framework, identifier):
            if adopted.get(suggestion.framework) == suggestion.version and suggestion not in found:
                found.append(suggestion)
    return found
