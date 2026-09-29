"""
Varias carpetas por conexión: un cursor por carpeta dentro de ``sync_cursor``.

Cada conector sabe vigilar **una** carpeta y lleva su propio cursor opaco
(``historyId`` de Gmail, ``deltaLink`` de Graph, ``UIDVALIDITY:UID`` de IMAP).
Para vigilar varias, este módulo construye un conector por carpeta, le pasa
el cursor de esa carpeta y junta lo que devuelven.

Formato de ``sync_cursor``:

- **Una sola carpeta**: el cursor del conector, tal cual. Es lo que había
  siempre, así que las conexiones existentes no cambian.
- **Varias**: ``{"folders": {"<carpeta>": <cursor o null>, ...}}`` en JSON,
  donde la bandeja por defecto es la clave ``""``.

Al pasar de una carpeta a varias, el cursor que había se queda en la carpeta
principal; una carpeta recién añadida arranca sin cursor, y el conector la
empieza en el correo que llegue a partir de ese momento (sin backfill).
"""

from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional, Tuple

from .base import MailboxConnector, MessageRef

#: Clave de la bandeja por defecto (``folder`` NULL) dentro del cursor compuesto.
DEFAULT_FOLDER_KEY = ""


def build_watched_folders(primary_folder: Optional[str], additional_folders: Optional[list]) -> List[Optional[str]]:
    """Carpetas que vigila una conexión, sin repetir, empezando por la principal.

    Args:
        primary_folder: ``IrisMailboxConnection.folder`` (``None`` para la bandeja).
        additional_folders: ``IrisMailboxConnection.additional_folders``
            (lista de ``{"id", ...}``).

    Returns:
        List[Optional[str]]: Ids de carpeta; ``None`` es la bandeja por defecto.
    """
    watched: List[Optional[str]] = [primary_folder]
    for folder in additional_folders or []:
        folder_id = folder.get("id") if isinstance(folder, dict) else None
        if folder_id and folder_id not in watched:
            watched.append(folder_id)
    return watched


def split_cursor(cursor: Optional[str], folders: List[Optional[str]]) -> Dict[str, Optional[str]]:
    """Reparte ``sync_cursor`` entre las carpetas vigiladas.

    Args:
        cursor: ``IrisMailboxConnection.sync_cursor``.
        folders: Salida de ``build_watched_folders``.

    Returns:
        Dict[str, Optional[str]]: Cursor de cada carpeta (clave
            ``DEFAULT_FOLDER_KEY`` para la bandeja); ``None`` si aún no tiene.
    """
    keys = [folder or DEFAULT_FOLDER_KEY for folder in folders]
    stored: Dict[str, Optional[str]] = {}
    parsed = None
    if cursor and cursor.startswith("{"):
        try:
            parsed = json.loads(cursor)
        except ValueError:
            parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("folders"), dict):
        stored = {str(key): value for key, value in parsed["folders"].items()}
    elif cursor:
        # Cursor de una sola carpeta: es el de la principal.
        stored = {keys[0]: cursor}
    return {key: stored.get(key) for key in keys}


def join_cursor(cursors: Dict[str, Optional[str]]) -> Optional[str]:
    """Junta los cursores de cada carpeta en el valor de ``sync_cursor``.

    Args:
        cursors: Cursor de cada carpeta, en el orden de vigilancia.

    Returns:
        Optional[str]: El cursor tal cual si solo hay una carpeta; el JSON
            compuesto si hay varias.
    """
    if len(cursors) == 1:
        return next(iter(cursors.values()))
    return json.dumps({"folders": cursors}, separators=(",", ":"))


def list_new_in_folders(build_connector: Callable[[Optional[str]], MailboxConnector], folders: List[Optional[str]],
                        access_token: str, cursor: Optional[str]) -> Tuple[List[MessageRef], Optional[str]]:
    """Mensajes nuevos de todas las carpetas vigiladas, y el cursor compuesto que resulta.

    Un mismo correo puede estar en dos carpetas vigiladas (en Gmail, con dos
    etiquetas): se devuelve una vez.

    Args:
        build_connector: Construye el conector de una carpeta.
        folders: Salida de ``build_watched_folders``.
        access_token: Token de acceso vigente (vacío en IMAP).
        cursor: ``sync_cursor`` actual.

    Returns:
        Tuple[List[MessageRef], Optional[str]]: Los mensajes nuevos y el
            ``sync_cursor`` nuevo.
    """
    current = split_cursor(cursor, folders)
    refs: List[MessageRef] = []
    seen = set()
    new_cursors: Dict[str, Optional[str]] = {}
    for folder in folders:
        key = folder or DEFAULT_FOLDER_KEY
        folder_refs, new_cursors[key] = build_connector(folder).list_new(access_token, current[key])
        for ref in folder_refs:
            if ref.provider_message_id not in seen:
                seen.add(ref.provider_message_id)
                refs.append(ref)
    return refs, join_cursor(new_cursors)
