"""
Tokens de integración de Iris: emitirlos y reconocerlos, sin base de datos.

Un token tiene la forma ``irt_<key_id>.<secreto>``:

- ``irt_`` dice qué es a quien lo encuentre pegado en un fichero o en un log.
- ``key_id`` (16 caracteres hexadecimales) es público: sirve para encontrar la
  fila por índice sin comparar el secreto con todas.
- el secreto son 32 bytes aleatorios; de él solo se guarda el SHA-256. No hace
  falta un hash lento como el de las contraseñas: esos existen porque una
  persona elige contraseñas adivinables, y aquí no hay nada que adivinar.

La comparación del hash es de tiempo constante (``hmac.compare_digest``): el
tiempo de respuesta no dice cuántos caracteres del secreto acertó quien prueba.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

from ..model import ReportChannel

#: Prefijo de todo token de integración de Iris.
TOKEN_PREFIX = "irt_"

#: Forma completa de un token: prefijo, 16 hexadecimales, punto y el secreto
#: en base64 URL (43 caracteres para 32 bytes, se admite algo de holgura).
_TOKEN_RE = re.compile(r"^irt_([0-9a-f]{16})\.([A-Za-z0-9_-]{32,128})$")


@dataclass(frozen=True)
class IssuedToken:
    """Un token recién emitido.

    Attributes:
        key_id: Parte pública, a guardar en ``IrisIntegrationToken.key_id``.
        secret_sha256: Hash del secreto, a guardar en ``secret_sha256``.
        token: El token completo en claro, para enseñarlo una sola vez. No se
            guarda en ningún sitio.
    """

    key_id: str
    secret_sha256: str
    token: str


def hash_secret(secret: str) -> str:
    """SHA-256 hexadecimal de la parte secreta de un token.

    Args:
        secret: Parte secreta (lo que va detrás del punto).

    Returns:
        str: 64 caracteres hexadecimales.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_integration_token() -> IssuedToken:
    """Emite un token nuevo.

    Returns:
        IssuedToken: Sus partes y el token completo.
    """
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    return IssuedToken(key_id=key_id, secret_sha256=hash_secret(secret), token=f"{TOKEN_PREFIX}{key_id}.{secret}")


def parse_integration_token(raw: Optional[str]) -> Optional[Tuple[str, str]]:
    """Separa un token en su parte pública y su secreto, si tiene la forma correcta.

    Args:
        raw: Lo que llegó en la cabecera, sin el ``Bearer``.

    Returns:
        Optional[tuple]: ``(key_id, secreto)``, o ``None`` si no es un token de
            integración de Iris (vacío, un JWT de sesión, mal formado…).
    """
    match = _TOKEN_RE.match((raw or "").strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def is_secret_valid(secret: str, stored_sha256: str) -> bool:
    """Si un secreto corresponde al hash guardado, en tiempo constante.

    Args:
        secret: Parte secreta recibida.
        stored_sha256: ``IrisIntegrationToken.secret_sha256``.

    Returns:
        bool: ``True`` si coincide.
    """
    return hmac.compare_digest(hash_secret(secret), stored_sha256)


def parse_report_channel(value: Optional[str]) -> str:
    """Canal de reporte que declara un cliente.

    Args:
        value: Valor de la cabecera ``X-Ellysia-Report-Channel`` (o del campo
            ``channel`` del formulario), en cualquier combinación de mayúsculas.

    Returns:
        str: Un valor de ``ReportChannel``; ``api`` si falta o no se conoce.
    """
    normalized = (value or "").strip().lower().replace("-", "_")
    known = {channel.value for channel in ReportChannel}
    return normalized if normalized in known else ReportChannel.API.value
