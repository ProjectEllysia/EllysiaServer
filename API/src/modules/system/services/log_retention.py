"""
Retención del registro de actividad (``secops.log``).

El registro anota cada petición con el usuario y la dirección IP de quien la
hace: guarda datos personales de cualquiera que visite la web, y el RGPD pide
no conservarlos más de lo necesario. Una vez al día se archiva el fichero en
curso como ``secops.log.AAAA-MM-DD`` y se borran los archivados que pasen del
plazo de ``general.logs.retentionDays``.

Es código sin base de datos: recibe el directorio y la fecha, y así se prueba
con un directorio temporal. Lo llama ``LogRetentionScheduler``, que corre solo
en la API; el worker también escribe en el fichero, pero con un
``WatchedFileHandler`` que se reabre solo cuando el fichero se archiva.
"""
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

#: Sufijo de fecha de un fichero archivado: ``secops.log.2026-09-22``.
_ARCHIVE_DATE_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class LogRetentionResult:
    """Qué hizo una pasada de retención.

    Attributes:
        archived_file: Ruta del fichero archivado en esta pasada, o ``None`` si
            no se archivó nada (no había registro, estaba vacío o ese día ya
            estaba archivado).
        deleted_files: Ficheros archivados que se borraron por pasar del plazo.
    """

    archived_file: Path | None
    deleted_files: list[Path]


def apply_log_retention(log_file: Path, today: date, retention_days: int) -> LogRetentionResult:
    """Archiva el registro del día anterior y borra los archivados caducados.

    El fichero en curso se renombra con la fecha de ayer, porque la pasada
    corre poco después de medianoche y lo que contiene es, sobre todo, el día
    que acaba de terminar. Si ese nombre ya existe (la pasada se repitió), no
    se sobrescribe.

    Args:
        log_file: Ruta del registro en curso (``<logdir>/secops.log``).
        today: Fecha de hoy, en UTC. Se pasa en vez de leerla aquí para poder
            probar la función con fechas fijas.
        retention_days: Días que se conserva cada fichero archivado. Un valor
            menor que 1 se trata como 1.

    Returns:
        LogRetentionResult: El fichero archivado, si lo hubo, y los borrados.
    """
    archived_file = _archive_current_log(log_file, today - timedelta(days=1))
    deleted_files = _delete_expired_archives(log_file, today, max(1, retention_days))
    return LogRetentionResult(archived_file=archived_file, deleted_files=deleted_files)


def _archive_current_log(log_file: Path, archive_date: date) -> Path | None:
    """Renombra el registro en curso con la fecha dada, si hay algo que archivar."""
    if not log_file.exists() or log_file.stat().st_size == 0:
        return None
    archive_path = log_file.with_name(f"{log_file.name}.{archive_date.isoformat()}")
    if archive_path.exists():
        return None
    log_file.rename(archive_path)
    return archive_path


def _delete_expired_archives(log_file: Path, today: date, retention_days: int) -> list[Path]:
    """Borra los archivados cuya fecha quede fuera del plazo de conservación."""
    oldest_kept_date = today - timedelta(days=retention_days)
    deleted_files = []
    for archive_path in log_file.parent.glob(f"{log_file.name}.*"):
        match = _ARCHIVE_DATE_RE.search(archive_path.name)
        if match is None:
            continue
        try:
            archive_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if archive_date < oldest_kept_date:
            archive_path.unlink()
            deleted_files.append(archive_path)
    return sorted(deleted_files)
