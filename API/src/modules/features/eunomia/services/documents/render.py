"""
Del modelo de una plantilla y sus valores al documento listo para componer.

Es el paso común a las dos salidas: el PDF y el DOCX reciben el mismo ``RenderedDocument`` y solo
deciden cómo dibujarlo, así que no pueden divergir en el contenido. Puro: sin base de datos ni red.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from ..templates import FIELD_DATE, FIELD_LIST, DocumentTemplate, TemplateField

#: Lo que se imprime donde un campo opcional quedó vacío.
EMPTY_VALUE = "—"

_MARKER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_ALONE = re.compile(r"^\{\{\s*([a-z][a-z0-9_]*)\s*\}\}$")
_BULLET = re.compile(r"^\s*[-•]\s+")

KIND_PARAGRAPH = "paragraph"
KIND_BULLETS = "bullets"


@dataclass(frozen=True)
class Block:
    """Un bloque de una sección.

    Attributes:
        kind: ``"paragraph"`` (un texto, con ``**negrita**`` y saltos de línea) o ``"bullets"``
            (una lista con viñetas).
        texts: El texto del párrafo (un elemento) o los elementos de la lista.
    """

    kind: str
    texts: tuple[str, ...]


@dataclass(frozen=True)
class RenderedSection:
    """Una sección ya con sus valores puestos.

    Attributes:
        heading: Encabezado.
        blocks: Bloques en orden.
    """

    heading: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class RenderedDocument:
    """El documento completo, listo para componerse en cualquier formato.

    Attributes:
        title: Título del documento.
        sections: Secciones en orden.
    """

    title: str
    sections: tuple[RenderedSection, ...]


def _display(field: TemplateField, value: str) -> str:
    """El valor tal como se lee en el documento: las fechas en ``dd/mm/aaaa``."""
    value = value.strip()
    if not value:
        return EMPTY_VALUE
    if field.type == FIELD_DATE:
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return value
    return value


def _items(value: str) -> list[str]:
    """Los elementos de un campo de lista: una línea cada uno, sin viñeta, sin vacíos."""
    return [_BULLET.sub("", line).strip() for line in value.splitlines() if line.strip()]


def missing_required(template: DocumentTemplate, values: Mapping[str, str]) -> list[str]:
    """Las claves obligatorias que no tienen valor.

    Args:
        template: La plantilla.
        values: ``{campo: texto}`` ya resueltos (guardados y precargados).

    Returns:
        list[str]: Claves, en el orden de la plantilla; vacía si se puede generar.
    """
    return [item.key for item in template.fields if item.is_required and not values.get(item.key, "").strip()]


def _fill(text: str, template: DocumentTemplate, values: Mapping[str, str]) -> str:
    """Sustituye los marcadores de un texto por sus valores."""
    def replace(match: re.Match) -> str:
        field = template.field(match.group(1))
        raw = values.get(match.group(1), "")
        if field.type == FIELD_LIST:
            items = _items(raw)
            return "; ".join(items) if items else EMPTY_VALUE
        return _display(field, raw)

    return _MARKER.sub(replace, text)


def _blocks(body: str, template: DocumentTemplate, values: Mapping[str, str]) -> tuple[Block, ...]:
    """Parte el texto de una sección en párrafos y listas con los valores puestos."""
    blocks: list[Block] = []
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        alone = _ALONE.match(paragraph)
        field = template.field(alone.group(1)) if alone else None
        if field is not None and field.type == FIELD_LIST:
            items = _items(values.get(field.key, ""))
            blocks.append(Block(KIND_BULLETS, tuple(items)) if items else Block(KIND_PARAGRAPH, (EMPTY_VALUE,)))
            continue
        lines = paragraph.splitlines()
        if all(_BULLET.match(line) for line in lines):
            blocks.append(Block(KIND_BULLETS, tuple(_fill(_BULLET.sub("", line), template, values) for line in lines)))
        else:
            blocks.append(Block(KIND_PARAGRAPH, (_fill(paragraph, template, values),)))
    return tuple(blocks)


def render_document(template: DocumentTemplate, values: Mapping[str, str]) -> RenderedDocument:
    """Pone los valores en una plantilla.

    Un campo de lista que ocupa un párrafo entero se convierte en una lista con viñetas; dentro
    de una frase se une con «;». Un campo opcional vacío se imprime como «—».

    Args:
        template: La plantilla validada.
        values: ``{campo: texto}`` ya resueltos; los que falten cuentan como vacíos.

    Returns:
        RenderedDocument: El título y las secciones, sin marcadores.
    """
    sections = tuple(
        RenderedSection(_fill(section.heading, template, values), _blocks(section.body, template, values))
        for section in template.sections
    )
    return RenderedDocument(template.title, sections)
