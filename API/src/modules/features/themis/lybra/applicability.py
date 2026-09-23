"""A qué componente de un producto afecta una CVE, y bajo qué condición.

La NVD identifica los productos con un CPE, y hay productos cuyo CPE cubre
varios programas: ``openbsd:openssh`` es a la vez el servidor ``sshd`` y el
cliente ``ssh``, ``scp``, ``sftp`` y ``ssh-agent``. Una CVE que sólo afecta al
cliente cuando se conecta a un servidor malicioso se publica contra el mismo CPE
que una del servidor, y la detección por versión las atribuía todas al ``sshd``
que había visto en la red. En el contraste de campo, 8 de 21 CVEs atribuidas a
un OpenSSH eran del cliente, y otras 8 sólo aplicaban con una opción concreta
de ``sshd_config``.

La fuente es un feed curado (``feeds/cve_applicability.json``), con una
heurística sobre la descripción de la NVD como respaldo para las CVEs no
curadas de los productos que la admiten. Es puro: no toca base de datos ni red.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

_BUNDLED_FEED = Path(__file__).parent / "feeds" / "cve_applicability.json"

# Programas del paquete OpenSSH que no son el servidor. Si la descripción los
# nombra y no nombra a ``sshd``, el fallo es de un cliente.
_CLIENT_PROGRAMS_RE = re.compile(
    r"\b(ssh-agent|ssh-add|ssh-keygen|scp|sftp|ssh client|client side|client-side)\b",
    re.IGNORECASE,
)
_SERVER_PROGRAM_RE = re.compile(r"\bsshd\b|\bserver\b", re.IGNORECASE)

#: Las dos respuestas que cambian algo: el fallo es sólo del cliente, o sólo
#: aplica si el servidor usa cierta opción (con su descripción).
Applicability = Tuple[str, Optional[str]]


@lru_cache(maxsize=1)
def load_cve_applicability(path: Optional[str] = None) -> dict:
    """Carga el feed de aplicabilidad.

    Args:
        path: Ruta a otro feed. Por defecto, ``None``: el que acompaña al
            módulo.

    Returns:
        dict: ``{"vendor:product": {"heuristic": bool, "cves": {cve_id:
            {"component": "client"|"server", "condition": str}}}}``.
    """
    feed_path = Path(path) if path else _BUNDLED_FEED
    return json.loads(feed_path.read_text(encoding="utf-8")).get("products", {})


def classify_cve_applicability(vendor: str, product: str, cve_id: str,
                               description: str = "") -> Optional[Applicability]:
    """Dice si una CVE no aplica a un servicio de red, o sólo con una condición.

    Args:
        vendor: El vendor del CPE, p. ej. ``"openbsd"``.
        product: El producto del CPE, p. ej. ``"openssh"``.
        cve_id: La CVE.
        description: La descripción de la NVD, para la heurística de respaldo.
            Por defecto vacía, con lo que la heurística no decide nada.

    Returns:
        Optional[Applicability]: ``("client", None)`` si sólo afecta a un
            cliente; ``("condition", texto)`` si afecta al servidor sólo con esa
            configuración; ``None`` si aplica sin más o si no se sabe (que es
            el comportamiento de siempre).
    """
    entry = load_cve_applicability().get(f"{vendor}:{product}")
    if entry is None:
        return None
    curated = entry.get("cves", {}).get(cve_id)
    if curated is not None:
        if curated.get("component") == "client":
            return "client", None
        if curated.get("condition"):
            return "condition", curated["condition"]
        return None
    if entry.get("heuristic") and _describes_a_client_flaw(description):
        return "client", None
    return None


def _describes_a_client_flaw(description: str) -> bool:
    """Si la descripción de la NVD atribuye el fallo a un cliente y no al servidor."""
    return (bool(_CLIENT_PROGRAMS_RE.search(description))
            and not _SERVER_PROGRAM_RE.search(description))
