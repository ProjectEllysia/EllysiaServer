"""
El catálogo de marcos de cumplimiento: ficheros versionados que viajan con el código.

Un marco (``nis2``) tiene una o más **versiones** (``2022-2555``), cada una en su fichero
``catalog/<marco>/<versión>.json``. Una versión es un árbol de nodos de profundidad libre: un
nodo es un **grupo** (agrupa a otros) o un **requisito** (algo que se evalúa y se evidencia).

El catálogo no vive en base de datos: las evaluaciones y evidencias de los usuarios guardan
``(marco, versión, código de nodo)`` sin clave ajena, y por eso una versión **publicada no se
modifica nunca**. ``catalog/LOCK.json`` guarda el SHA-256 de cada versión publicada y un test lo
recalcula; un cambio en una versión publicada se hace publicando otra. Una versión en estado
``draft`` aún no se ha congelado: se puede completar y, al publicarla, su hash entra en el lock.

Este módulo es **puro**: no toca base de datos, red ni Flask, y no importa nada de ``features``.

Fuentes y licencias
-------------------
Reproducir el texto de una norma protegida dentro de un producto comercial es un riesgo legal, y
es fácil hacerlo sin darse cuenta al rellenar un catálogo. Por eso cada versión declara de dónde
sale (``sources``: nombre, dirección, base de reutilización y fecha de consulta) y qué se puede
reproducir de ella (``licenseMode``):

* ``full_text``: el texto de la fuente se puede reproducir citándola. Legislación publicada en
  EUR-Lex o en el BOE (NIS2, el Reglamento 2024/2690, el RGPD, el ENS).
* ``own_wording``: solo redacción propia, tomando la fuente como referencia. Guías con una
  autorización de reproducción condicionada, como las de ENISA, que permite reproducir citando
  la fuente «salvo que se indique otra cosa» y no fija una licencia concreta.
* ``codes_only``: solo códigos y títulos cortos propios. Normas de pago con derechos de autor,
  como ISO/IEC 27001: se usan los identificadores de los controles, nunca su texto.

Un título de una versión ``codes_only`` no pasa de ``CODES_ONLY_MAX_TITLE`` caracteres y su
descripción no pasa de ``CODES_ONLY_MAX_DESCRIPTION``: no impide copiar, pero un párrafo de la
norma no cabe y salta en el test. Que lo escrito sea de verdad redacción propia lo comprueba la
revisión del cambio.

Formato de una versión (claves en camelCase)::

    {
      "key": "nis2", "version": "2022-2555", "status": "draft" | "published",
      "name": "...", "shortName": "...", "publishedAt": "2022-12-27",
      "licenseMode": "full_text" | "own_wording" | "codes_only",
      "sources": [{"name": "...", "url": "...", "license": "...", "consultedAt": "2026-10-10"}],
      "notes": "...",                          # opcional
      "nodes": [{
        "identifier": "21.2.b", "parent": "21.2" | null, "order": 2,
        "kind": "group" | "requirement",
        "assessable": true,                    # opcional; hojas true, grupos false
        "title": "...", "description": "...",
        "actions": ["..."], "evidence": ["..."],
        "source": "Directiva (UE) 2022/2555, art. 21.2.b",
        "register": null                       # reservado: el requisito se evidencia con un registro
      }]
    }
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

#: Carpeta con los datos del catálogo (``index.json``, ``LOCK.json`` y una carpeta por marco).
CATALOG_ROOT = Path(__file__).resolve().parents[1] / "catalog"

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)

KIND_GROUP = "group"
KIND_REQUIREMENT = "requirement"
_KINDS = (KIND_GROUP, KIND_REQUIREMENT)

LICENSE_FULL_TEXT = "full_text"
LICENSE_OWN_WORDING = "own_wording"
LICENSE_CODES_ONLY = "codes_only"
_LICENSE_MODES = (LICENSE_FULL_TEXT, LICENSE_OWN_WORDING, LICENSE_CODES_ONLY)

#: Longitud máxima de un título y de una descripción en una versión ``codes_only``.
CODES_ONLY_MAX_TITLE = 100
CODES_ONLY_MAX_DESCRIPTION = 300


class CatalogFormatError(ValueError):
    """Una versión del catálogo no cumple el formato; el mensaje dice cuál y dónde."""


@dataclass(frozen=True)
class CatalogSource:
    """De dónde sale una versión del catálogo.

    Attributes:
        name: Nombre de la fuente (``"Directiva (UE) 2022/2555"``).
        url: Dirección donde se consultó.
        license: Base de reutilización (``"Legislación de la UE: reutilizable citando la fuente"``).
        consulted_at: Fecha de consulta, ISO ``AAAA-MM-DD``.
    """

    name: str
    url: str
    license: str
    consulted_at: str


@dataclass(frozen=True)
class CatalogNode:
    """Un nodo del árbol de una versión.

    Attributes:
        code: Código global ``<marco>:<identificador>``, la clave estable que guardan las
            evaluaciones y los mapeos de Lybra (``"nis2:21.2.e"``).
        framework: Clave del marco.
        identifier: Identificador dentro del marco (``"21.2.e"``).
        parent: Código global del padre, o ``None`` si es una raíz.
        order: Posición entre sus hermanos; las listas salen ordenadas por ella.
        kind: ``"group"`` o ``"requirement"``.
        is_assessable: Si se puede evaluar y evidenciar. Por defecto, las hojas sí y los grupos
            no; el catálogo puede marcar evaluable un grupo.
        title: Título del nodo.
        description: Qué pide, en lenguaje llano; vacío si no está redactado.
        actions: Qué hay que hacer para cumplirlo.
        evidence: Qué documentos o registros lo demuestran, como lista de elementos cortos.
        source: Artículo o punto del que sale el nodo, para citarlo.
        register: Reservado: tipo de registro con el que se evidencia el requisito, o ``None``.
    """

    code: str
    framework: str
    identifier: str
    parent: Optional[str]
    order: int
    kind: str
    is_assessable: bool
    title: str
    description: str
    actions: tuple[str, ...]
    evidence: tuple[str, ...]
    source: str
    register: Optional[str]


@dataclass(frozen=True)
class FrameworkVersion:
    """Una versión de un marco, ya validada y lista para consultar.

    Attributes:
        key: Clave del marco (``"nis2"``).
        version: Identificador de la versión (``"2022-2555"``).
        status: ``"draft"`` o ``"published"``.
        name: Nombre legible del marco.
        short_name: Nombre corto para rótulos estrechos.
        published_at: Fecha de publicación del texto de origen, ISO.
        license_mode: Qué se puede reproducir de la fuente: ``"full_text"``,
            ``"own_wording"`` o ``"codes_only"`` (ver «Fuentes y licencias»).
        sources: Fuentes de las que sale.
        notes: Notas de aplicabilidad o de uso; vacío si no hay.
        nodes: Todos los nodos, en el orden del fichero.
    """

    key: str
    version: str
    status: str
    name: str
    short_name: str
    published_at: str
    license_mode: str
    sources: tuple[CatalogSource, ...]
    notes: str
    nodes: tuple[CatalogNode, ...]
    _by_code: dict[str, CatalogNode] = field(default_factory=dict, repr=False, compare=False)
    _children: dict[Optional[str], tuple[CatalogNode, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def node(self, code: str) -> Optional[CatalogNode]:
        """Devuelve un nodo por su código global, o ``None`` si la versión no lo tiene."""
        return self._by_code.get(code)

    def children(self, code: Optional[str]) -> tuple[CatalogNode, ...]:
        """Devuelve los hijos directos de un nodo, ordenados; las raíces si ``code`` es ``None``."""
        return self._children.get(code, ())

    def ancestors(self, code: str) -> tuple[CatalogNode, ...]:
        """Devuelve los ascendientes de un nodo, del padre inmediato a la raíz.

        Args:
            code: Código global del nodo.

        Returns:
            tuple[CatalogNode, ...]: Vacía si el nodo es raíz o no existe.
        """
        chain: list[CatalogNode] = []
        current = self._by_code.get(code)
        while current is not None and current.parent is not None:
            current = self._by_code[current.parent]
            chain.append(current)
        return tuple(chain)

    def assessable_nodes(self) -> tuple[CatalogNode, ...]:
        """Devuelve los nodos evaluables, en el orden del árbol (profundidad primero)."""
        return tuple(node for node in self.walk() if node.is_assessable)

    def walk(self) -> Iterator[CatalogNode]:
        """Recorre el árbol en profundidad, cada nivel en el orden del catálogo."""
        stack = list(reversed(self.children(None)))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(self.children(node.code)))


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogFormatError(message)


def _text_list(value: object, where: str) -> tuple[str, ...]:
    _require(isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value),
             f"{where}: debe ser una lista de textos no vacíos")
    return tuple(value)  # type: ignore[arg-type]


def parse_version(document: dict) -> FrameworkVersion:
    """Valida el documento de una versión y lo convierte en un ``FrameworkVersion``.

    Comprueba la forma de cada nodo, que los identificadores sean únicos, que cada padre
    exista y que no haya ciclos. En una versión ``published`` exige además que todo nodo
    evaluable tenga descripción, actuaciones y evidencias: una versión publicada no se puede
    completar después.

    Args:
        document: El JSON de la versión ya cargado.

    Returns:
        FrameworkVersion: La versión lista para consultar.

    Raises:
        CatalogFormatError: Si algo no cumple el formato; el mensaje nombra el nodo.
    """
    for required in ("key", "version", "status", "name", "shortName", "publishedAt", "licenseMode",
                     "sources", "nodes"):
        _require(required in document, f"falta la clave «{required}»")
    key, version = document["key"], document["version"]
    _require(isinstance(key, str) and key.strip() and ":" not in key, "«key» no es válida")
    _require(isinstance(version, str) and version.strip() and "/" not in version, "«version» no es válida")
    _require(document["status"] in _STATUSES, f"«status» debe ser uno de {_STATUSES}")
    where_version = f"{key}/{version}"
    _require(document["licenseMode"] in _LICENSE_MODES,
             f"{where_version}: «licenseMode» debe ser uno de {_LICENSE_MODES}")
    is_codes_only = document["licenseMode"] == LICENSE_CODES_ONLY

    sources_raw = document["sources"]
    _require(isinstance(sources_raw, list) and sources_raw, f"{where_version}: «sources» no puede estar vacío")
    sources: list[CatalogSource] = []
    for index, source in enumerate(sources_raw):
        for required in ("name", "url", "license", "consultedAt"):
            _require(isinstance(source.get(required), str) and source[required].strip(),
                     f"{where_version}: la fuente {index} no tiene «{required}»")
        _require(_ISO_DATE.fullmatch(source["consultedAt"]) is not None,
                 f"{where_version}: la fuente {index} tiene «consultedAt» que no es AAAA-MM-DD")
        sources.append(CatalogSource(source["name"], source["url"], source["license"], source["consultedAt"]))

    nodes_raw = document["nodes"]
    _require(isinstance(nodes_raw, list) and nodes_raw, f"{where_version}: «nodes» no puede estar vacío")

    identifiers: set[str] = set()
    for raw in nodes_raw:
        identifier = raw.get("identifier")
        _require(isinstance(identifier, str) and identifier.strip(), f"{where_version}: un nodo no tiene «identifier»")
        _require(identifier not in identifiers, f"{where_version}: el identificador «{identifier}» está repetido")
        identifiers.add(identifier)

    has_children = {raw.get("parent") for raw in nodes_raw}
    nodes: list[CatalogNode] = []
    for raw in nodes_raw:
        identifier = raw["identifier"]
        where = f"{where_version}:{identifier}"
        parent = raw.get("parent")
        _require(parent is None or parent in identifiers, f"{where}: el padre «{parent}» no existe")
        _require(parent != identifier, f"{where}: es su propio padre")
        _require(raw.get("kind") in _KINDS, f"{where}: «kind» debe ser uno de {_KINDS}")
        _require(isinstance(raw.get("order"), int), f"{where}: «order» debe ser un entero")
        _require(isinstance(raw.get("title"), str) and raw["title"].strip(), f"{where}: falta «title»")
        description = raw.get("description", "")
        _require(isinstance(description, str), f"{where}: «description» debe ser un texto")
        if is_codes_only:
            _require(len(raw["title"]) <= CODES_ONLY_MAX_TITLE,
                     f"{where}: el título pasa de {CODES_ONLY_MAX_TITLE} caracteres en una versión codes_only")
            _require(len(description) <= CODES_ONLY_MAX_DESCRIPTION,
                     f"{where}: la descripción pasa de {CODES_ONLY_MAX_DESCRIPTION} caracteres "
                     f"en una versión codes_only")
        actions = _text_list(raw.get("actions", []), f"{where}: «actions»")
        evidence = _text_list(raw.get("evidence", []), f"{where}: «evidence»")
        is_leaf = identifier not in has_children
        is_assessable = raw.get("assessable", is_leaf)
        _require(isinstance(is_assessable, bool), f"{where}: «assessable» debe ser verdadero o falso")
        register = raw.get("register")
        _require(register is None or isinstance(register, str), f"{where}: «register» debe ser texto o nulo")
        if document["status"] == STATUS_PUBLISHED and is_assessable:
            _require(description.strip() and actions and evidence,
                     f"{where}: un requisito evaluable de una versión publicada necesita descripción, "
                     f"actuaciones y evidencias")
        nodes.append(CatalogNode(
            code=f"{key}:{identifier}", framework=key, identifier=identifier,
            parent=None if parent is None else f"{key}:{parent}",
            order=raw["order"], kind=raw["kind"], is_assessable=is_assessable,
            title=raw["title"], description=description, actions=actions, evidence=evidence,
            source=raw.get("source", ""), register=register,
        ))

    by_code = {node.code: node for node in nodes}
    for node in nodes:
        seen: set[str] = set()
        current: Optional[str] = node.code
        while current is not None:
            _require(current not in seen, f"{where_version}: hay un ciclo en «{node.identifier}»")
            seen.add(current)
            current = by_code[current].parent

    grouped: dict[Optional[str], list[CatalogNode]] = {}
    for node in nodes:
        grouped.setdefault(node.parent, []).append(node)
    children = {
        parent: tuple(sorted(siblings, key=lambda sibling: sibling.order))
        for parent, siblings in grouped.items()
    }
    return FrameworkVersion(
        key=key, version=version, status=document["status"], name=document["name"],
        short_name=document["shortName"], published_at=document["publishedAt"],
        license_mode=document["licenseMode"], sources=tuple(sources), notes=document.get("notes", ""), nodes=tuple(nodes),
        _by_code=by_code, _children=children,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _load_index(root: str) -> dict:
    return _read_json(Path(root) / "index.json")


@lru_cache(maxsize=None)
def _load_version(root: str, key: str, version: str) -> FrameworkVersion:
    return parse_version(_read_json(Path(root) / key / f"{version}.json"))


def load_index(root: Path = CATALOG_ROOT) -> dict:
    """Devuelve ``catalog/index.json``: los marcos, sus versiones y cuál es la vigente.

    Args:
        root: Carpeta del catálogo. Por defecto, la que viaja con el código.

    Returns:
        dict: ``{"frameworks": [{"key", "name", "shortName", "current", "versions":
            [{"version", "status"}]}]}``.
    """
    return _load_index(str(root))


def load_version(key: str, version: str, root: Path = CATALOG_ROOT) -> Optional[FrameworkVersion]:
    """Carga y valida una versión de un marco.

    Args:
        key: Clave del marco.
        version: Identificador de la versión.
        root: Carpeta del catálogo. Por defecto, la que viaja con el código.

    Returns:
        Optional[FrameworkVersion]: La versión, o ``None`` si el índice no la declara. Se
            resuelve contra el índice y no contra el disco, de modo que ``key`` y ``version``
            nunca forman una ruta.

    Raises:
        CatalogFormatError: Si el fichero existe y no cumple el formato.
    """
    for framework in load_index(root)["frameworks"]:
        if framework["key"] == key and any(item["version"] == version for item in framework["versions"]):
            return _load_version(str(root), key, version)
    return None


def file_digest(path: Path) -> str:
    """Devuelve el SHA-256 de un fichero de versión, con los saltos de línea normalizados.

    Args:
        path: Fichero de la versión.

    Returns:
        str: El hash en hexadecimal. Se normaliza ``\\r\\n`` a ``\\n`` para que el resultado no
            dependa del sistema donde se hizo el checkout.
    """
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def lock_mismatches(root: Path = CATALOG_ROOT) -> list[str]:
    """Compara las versiones publicadas con ``LOCK.json`` y dice qué no cuadra.

    Args:
        root: Carpeta del catálogo.

    Returns:
        list[str]: Una frase por problema: versión publicada sin línea en el lock, línea del
            lock cuyo hash ya no coincide, línea de una versión que no está publicada o que ya
            no existe. Vacía si todo cuadra.
    """
    lock = _read_json(root / "LOCK.json")
    problems: list[str] = []
    published: set[str] = set()
    for framework in load_index(root)["frameworks"]:
        for item in framework["versions"]:
            if item["status"] != STATUS_PUBLISHED:
                continue
            entry = f"{framework['key']}/{item['version']}"
            published.add(entry)
            path = root / framework["key"] / f"{item['version']}.json"
            if entry not in lock:
                problems.append(f"{entry} está publicada y no tiene línea en LOCK.json")
            elif file_digest(path) != lock[entry]:
                problems.append(f"{entry} está publicada y su contenido ya no coincide con LOCK.json")
    for entry in lock:
        if entry not in published:
            problems.append(f"LOCK.json guarda {entry}, que no es una versión publicada del índice")
    return problems
