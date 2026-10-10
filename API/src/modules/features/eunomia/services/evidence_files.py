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

from ..exceptions import EvidenceTooLargeError, EvidenceTypeNotAllowedError

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


def check_upload(filename: str, content: bytes, max_bytes: int, allowed_extensions: list[str]) -> str:
    """Comprueba tamaño y extensión de una subida y devuelve su tipo.

    Args:
        filename: Nombre ya saneado.
        content: Los bytes del fichero.
        max_bytes: Tamaño máximo en bytes (``features.eunomia.maxEvidenceBytes``).
        allowed_extensions: Extensiones admitidas, en minúsculas y sin punto.

    Returns:
        str: El tipo MIME asignado a partir de la extensión.

    Raises:
        EvidenceTooLargeError: Si supera el máximo.
        EvidenceTypeNotAllowedError: Si la extensión no está entre las admitidas.
    """
    if len(content) > max_bytes:
        raise EvidenceTooLargeError(max_bytes // (1024 * 1024))
    extension = extension_of(filename)
    if extension not in allowed_extensions:
        raise EvidenceTypeNotAllowedError(extension or "sin extensión", ", ".join(allowed_extensions))
    return mimetypes.types_map.get(f".{extension}", "application/octet-stream")


def digest(content: bytes) -> str:
    """SHA-256 del contenido, en hexadecimal."""
    return hashlib.sha256(content).hexdigest()
