"""
Reglas sobre el fichero que se sube como evidencia: nombre, tamaño y tipo.

Puro: no toca base de datos ni red. Una subida es una puerta de entrada clásica, y lo que se
guarda lo abren después otras personas de la organización; por eso nada de lo que dice el
navegador (nombre, tipo declarado) se toma por bueno.
"""

import hashlib
import mimetypes
import re
import unicodedata

import io
import zipfile
from types import SimpleNamespace

from src.modules.shared import inspect_attachment

from ..exceptions import (
    EvidenceActiveContentError,
    EvidenceTooLargeError,
    EvidenceTypeMismatchError,
    EvidenceTypeNotAllowedError,
)

_MAX_FILENAME = 200
_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f]+")


def sanitize_filename(filename: str) -> str:
    """Deja un nombre de fichero sin rutas, sin caracteres de control y de largo acotado.

    Args:
        filename: El nombre tal como lo manda el navegador.

    Returns:
        str: Solo el último componente, con lo peligroso sustituido por ``_``. Nunca vacío:
            si no queda nada, ``"evidencia"``.
    """
    name = unicodedata.normalize("NFC", filename or "").replace("\\", "/").split("/")[-1].strip()
    name = _UNSAFE.sub("_", name).strip(" .")
    if len(name) > _MAX_FILENAME:
        stem, dot, extension = name.rpartition(".")
        keep = _MAX_FILENAME - len(extension) - 1 if dot else _MAX_FILENAME
        name = (stem[:keep] + "." + extension) if dot else name[:_MAX_FILENAME]
    return name or "evidencia"


def extension_of(filename: str) -> str:
    """La extensión de un nombre, en minúsculas y sin punto; vacía si no tiene."""
    _, dot, extension = filename.rpartition(".")
    return extension.lower() if dot else ""


#: Firmas de los tipos binarios que se admiten, por extensión: el contenido manda sobre el nombre.
_SIGNATURES = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}
#: Extensiones que son un ZIP con una entrada que las identifica: (entrada, texto que debe llevar).
_ZIP_FAMILIES = {
    "docx": ("word/document.xml", None),
    "xlsx": ("xl/workbook.xml", None),
    "odt": ("mimetype", b"application/vnd.oasis.opendocument.text"),
    "ods": ("mimetype", b"application/vnd.oasis.opendocument.spreadsheet"),
}
_TEXT_EXTENSIONS = frozenset({"txt", "csv"})


def _matches_extension(extension: str, content: bytes) -> bool:
    """Indica si los bytes son de verdad del tipo que dice la extensión.

    Args:
        extension: Extensión en minúsculas y sin punto.
        content: Los bytes del fichero.

    Returns:
        bool: ``True`` si la firma (o la estructura, para Office y OpenDocument) coincide; un
            ``.txt`` o ``.csv`` es texto sin bytes nulos.
    """
    if extension in _SIGNATURES:
        return any(content.startswith(signature) for signature in _SIGNATURES[extension])
    if extension in _ZIP_FAMILIES:
        entry, marker = _ZIP_FAMILIES[extension]
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if entry not in archive.namelist():
                    return False
                return marker is None or archive.read(entry).strip().startswith(marker)
        except (zipfile.BadZipFile, OSError, ValueError, KeyError):
            return False
    if extension in _TEXT_EXTENSIONS:
        return b"\x00" not in content[:8192]
    return False


def check_upload(filename: str, content: bytes, max_bytes: int, allowed_extensions: list[str]) -> str:
    """Valida una subida y devuelve su tipo: tamaño, tipo real y contenido activo.

    Nada de lo que declara el navegador se toma por bueno: el tipo sale de la extensión
    **comprobada contra el contenido**, y el contenido se inspecciona en busca de lo que se
    ejecutaría al abrirlo.

    Args:
        filename: Nombre ya saneado.
        content: Los bytes del fichero.
        max_bytes: Tamaño máximo en bytes (``features.eunomia.maxEvidenceBytes``).
        allowed_extensions: Extensiones admitidas, en minúsculas y sin punto.

    Returns:
        str: El tipo MIME asignado a partir de la extensión ya comprobada.

    Raises:
        EvidenceTooLargeError: Si supera el máximo.
        EvidenceTypeNotAllowedError: Si la extensión no está entre las admitidas.
        EvidenceTypeMismatchError: Si el contenido no es del tipo que dice su extensión.
        EvidenceActiveContentError: Si lleva macros, JavaScript u otro contenido activo.
    """
    if len(content) > max_bytes:
        raise EvidenceTooLargeError(max_bytes // (1024 * 1024))
    extension = extension_of(filename)
    if extension not in allowed_extensions:
        raise EvidenceTypeNotAllowedError(extension or "sin extensión", ", ".join(allowed_extensions))
    if not _matches_extension(extension, content):
        raise EvidenceTypeMismatchError(extension)

    limits = SimpleNamespace(
        max_inspected_bytes=max_bytes, max_expanded_bytes=4 * max_bytes, max_archive_entries=1000,
        max_archive_depth=2, max_compression_ratio=200, max_pdf_streams=1000,
    )
    result = inspect_attachment(filename, "", content, limits, frozenset())
    if result.findings:
        raise EvidenceActiveContentError(result.findings[0]["detail"])
    return mimetypes.types_map.get(f".{extension}", "application/octet-stream")


def digest(content: bytes) -> str:
    """SHA-256 del contenido, en hexadecimal."""
    return hashlib.sha256(content).hexdigest()
