"""
Plantillas de documentos: qué documentos ayuda a redactar un marco y qué datos pide cada uno.

Una plantilla es la estructura de un documento que la normativa exige (una política, un
procedimiento, un registro): sus secciones con el texto fijo y los huecos que rellena el usuario o
que Ellysia rellena por él. Igual que el catálogo, son **datos versionados**, no código: un fichero
``templates/<marco>/<plantilla>@<versión>.json`` por plantilla.

El texto fijo solo admite marcadores ``{{campo}}``, sin bucles ni condiciones, para que el mismo
modelo sirva a la salida en PDF y a la de Word. Cada campo puede declarar un ``source``: el dato
que Ellysia ya conoce y con el que llega precargado.

Puro: no toca base de datos ni red. Quien necesite los valores (el perfil de empresa, las
evaluaciones) los resuelve fuera y los pasa.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .catalog import CATALOG_ROOT, CatalogFormatError, load_version

#: Carpeta con las plantillas (una subcarpeta por marco).
TEMPLATES_ROOT = Path(__file__).resolve().parents[1] / "templates"

FIELD_TEXT = "text"
FIELD_LONG_TEXT = "longtext"
FIELD_DATE = "date"
FIELD_LIST = "list"
FIELD_PERSON = "person"
FIELD_TYPES = (FIELD_TEXT, FIELD_LONG_TEXT, FIELD_DATE, FIELD_LIST, FIELD_PERSON)

#: Campos del perfil de empresa que una plantilla puede usar como origen (``company.<campo>``).
COMPANY_SOURCES = (
    "legalName", "taxId", "addressLine", "postalCode", "city", "province", "country",
    "sector", "companySize", "employeeCount", "jurisdiction", "workModel", "securityContact",
)
#: Datos de una evaluación que una plantilla puede usar (``assessment.<control>.<dato>``).
ASSESSMENT_SOURCES = ("responsible", "dueDate")
SOURCE_TODAY = "system.today"

_MARKER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_FILE = re.compile(r"^([a-z0-9-]+)@(\d+)\.json$")


@dataclass(frozen=True)
class TemplateField:
    """Un hueco de la plantilla.

    Attributes:
        key: Nombre del marcador (``company_name``); único en la plantilla.
        label: Texto que ve el usuario en el formulario.
        type: Uno de ``FIELD_TYPES``. ``list`` es un elemento por línea; ``person`` un nombre.
        is_required: Si hay que rellenarlo para poder generar el documento.
        source: Dato con el que llega precargado (``company.legalName``,
            ``assessment.RE.3.5.responsible``, ``system.today``) o ``None``.
        default: Valor inicial fijo cuando no hay origen; ``""`` si no tiene.
        help: Ayuda breve bajo el campo; ``""`` si no tiene.
    """

    key: str
    label: str
    type: str
    is_required: bool
    source: Optional[str]
    default: str
    help: str


@dataclass(frozen=True)
class TemplateSection:
    """Una sección del documento: encabezado y texto con marcadores ``{{campo}}``.

    Attributes:
        heading: Título de la sección.
        body: Texto; los párrafos van separados por una línea en blanco.
    """

    heading: str
    body: str


@dataclass(frozen=True)
class DocumentTemplate:
    """Una plantilla validada.

    Attributes:
        key: Identificador (``incident-procedure``), único dentro de su marco.
        version: Versión de la plantilla (``"1"``).
        framework: Clave del marco para el que se redacta.
        framework_version: Versión del catálogo con la que se validaron sus controles.
        title: Título del documento.
        summary: Para qué sirve, en una frase.
        controls: Identificadores de los controles que ayuda a cumplir.
        fields: Huecos, en el orden del formulario.
        sections: Secciones, en el orden del documento.
    """

    key: str
    version: str
    framework: str
    framework_version: str
    title: str
    summary: str
    controls: tuple[str, ...]
    fields: tuple[TemplateField, ...]
    sections: tuple[TemplateSection, ...]

    def field(self, key: str) -> Optional[TemplateField]:
        """El campo con esa clave, o ``None``."""
        return next((item for item in self.fields if item.key == key), None)


def _assessment_source(source: str) -> Optional[tuple[str, str]]:
    """Parte ``assessment.<control>.<dato>`` en ``(control, dato)``; ``None`` si no lo es."""
    if not source.startswith("assessment."):
        return None
    control, _, datum = source[len("assessment."):].rpartition(".")
    return (control, datum) if control else None


def parse_template(document: dict, framework: str, root: Path = CATALOG_ROOT) -> DocumentTemplate:
    """Valida una plantilla contra el catálogo y el perfil de empresa.

    Args:
        document: El JSON ya cargado.
        framework: Clave del marco, la de la carpeta en la que está el fichero.
        root: Carpeta del catálogo contra la que se validan los controles.

    Returns:
        DocumentTemplate: La plantilla validada.

    Raises:
        CatalogFormatError: Si falta algo, si un marcador no tiene campo (o un campo no se usa),
            si un ``source`` no apunta a un dato que existe o si un control no existe o no es
            evaluable en la versión del catálogo declarada.
    """
    where = f"{framework}/{document.get('key', '?')}"
    for required in ("key", "version", "frameworkVersion", "title", "summary", "controls", "fields", "sections"):
        if required not in document:
            raise CatalogFormatError(f"{where}: falta «{required}»")
    version = load_version(framework, document["frameworkVersion"], root)
    if version is None:
        raise CatalogFormatError(f"{where}: la versión {document['frameworkVersion']} del marco no existe")

    def assessable(identifier: str) -> bool:
        node = version.node(f"{framework}:{identifier}")
        return node is not None and node.is_assessable

    for identifier in document["controls"]:
        if not assessable(identifier):
            raise CatalogFormatError(f"{where}: el control «{identifier}» no existe o no es evaluable")

    fields: list[TemplateField] = []
    for raw in document["fields"]:
        key = raw.get("key", "")
        if not _KEY.match(key):
            raise CatalogFormatError(f"{where}: la clave de campo «{key}» no es válida")
        if any(item.key == key for item in fields):
            raise CatalogFormatError(f"{where}: el campo «{key}» está repetido")
        if raw.get("type") not in FIELD_TYPES:
            raise CatalogFormatError(f"{where}: el campo «{key}» tiene un tipo desconocido")
        source = raw.get("source")
        if source is not None:
            _check_source(where, key, source, assessable)
        fields.append(TemplateField(
            key=key, label=raw.get("label", key), type=raw["type"], is_required=bool(raw.get("required", False)),
            source=source, default=raw.get("default", ""), help=raw.get("help", ""),
        ))

    sections = tuple(TemplateSection(raw["heading"], raw["body"]) for raw in document["sections"])
    used = {marker for section in sections for marker in _MARKER.findall(section.heading + "\n" + section.body)}
    declared = {item.key for item in fields}
    if used - declared:
        raise CatalogFormatError(f"{where}: marcadores sin campo: {', '.join(sorted(used - declared))}")
    if declared - used:
        raise CatalogFormatError(f"{where}: campos que el texto no usa: {', '.join(sorted(declared - used))}")

    return DocumentTemplate(
        key=document["key"], version=str(document["version"]), framework=framework,
        framework_version=document["frameworkVersion"], title=document["title"], summary=document["summary"],
        controls=tuple(document["controls"]), fields=tuple(fields), sections=sections,
    )


def _check_source(where: str, key: str, source: str, assessable) -> None:
    """Comprueba que el origen de un campo apunta a un dato que existe."""
    if source == SOURCE_TODAY:
        return
    if source.startswith("company."):
        if source[len("company."):] not in COMPANY_SOURCES:
            raise CatalogFormatError(f"{where}: el campo «{key}» usa un dato de empresa que no existe: {source}")
        return
    parsed = _assessment_source(source)
    if parsed is None or parsed[1] not in ASSESSMENT_SOURCES or not assessable(parsed[0]):
        raise CatalogFormatError(f"{where}: el campo «{key}» tiene un origen que no existe: {source}")


@lru_cache(maxsize=None)
def _load_all(templates_root: str, catalog_root: str) -> tuple[DocumentTemplate, ...]:
    found: list[DocumentTemplate] = []
    for path in sorted(Path(templates_root).glob("*/*.json")):
        match = _FILE.match(path.name)
        if match is None:
            raise CatalogFormatError(f"{path.name}: el nombre debe ser <plantilla>@<versión>.json")
        template = parse_template(json.loads(path.read_text(encoding="utf-8")), path.parent.name, Path(catalog_root))
        if (template.key, template.version) != match.groups():
            raise CatalogFormatError(f"{path.name}: la clave o la versión no coinciden con el nombre del fichero")
        found.append(template)
    return tuple(found)


def load_templates(templates_root: Path = TEMPLATES_ROOT, catalog_root: Path = CATALOG_ROOT) -> tuple[DocumentTemplate, ...]:
    """Carga y valida todas las plantillas.

    Args:
        templates_root: Carpeta de plantillas. Por defecto, la que viaja con el código.
        catalog_root: Carpeta del catálogo contra la que se validan.

    Returns:
        tuple[DocumentTemplate, ...]: Todas las versiones de todas las plantillas, por marco y nombre.

    Raises:
        CatalogFormatError: Si alguna no es válida.
    """
    return _load_all(str(templates_root), str(catalog_root))


def get_template(key: str, version: Optional[str] = None, **roots) -> Optional[DocumentTemplate]:
    """Busca una plantilla por clave.

    Args:
        key: Identificador de la plantilla.
        version: Versión concreta; por defecto, la más alta.
        **roots: ``templates_root`` y ``catalog_root``, para pruebas.

    Returns:
        Optional[DocumentTemplate]: La plantilla, o ``None`` si no existe.
    """
    matches = [item for item in load_templates(**roots) if item.key == key and version in (None, item.version)]
    return max(matches, key=lambda item: int(item.version), default=None)


def templates_for_control(framework: str, identifier: str, **roots) -> list[DocumentTemplate]:
    """Las plantillas que ayudan a cumplir un control, para ofrecerlas desde su detalle.

    Args:
        framework: Clave del marco.
        identifier: Identificador del control.
        **roots: ``templates_root`` y ``catalog_root``, para pruebas.

    Returns:
        list[DocumentTemplate]: Solo la última versión de cada plantilla.
    """
    latest = {item.key: item for item in sorted(load_templates(**roots), key=lambda item: int(item.version))}
    return [item for item in latest.values() if item.framework == framework and identifier in item.controls]
