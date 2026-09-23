"""
LogRetentionScheduler — archiva y purga cada noche el registro de actividad.

Corre solo en la API (``run.py::_configure_scheduling``), nunca en el worker:
un único proceso archiva el fichero, y los demás lo siguen gracias a su
``WatchedFileHandler``. La lógica vive en ``log_retention.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import src.modules.system.config_reading as CR
from src.modules.infrastructure.scheduling import make_background_scheduler, scheduler_job

from ..logging import LOG_FILE_NAME
from .log_retention import apply_log_retention

logger = logging.getLogger(__name__)

#: Cinco minutos después de medianoche UTC: el día anterior ya está completo y
#: no coincide con el cambio de fecha exacto de otros trabajos nocturnos.
_RETENTION_CRON = "5 0 * * *"


@scheduler_job(logger, "Error aplicando la retención del registro de actividad")
def _run_log_retention() -> None:
    """Cuerpo del job: archiva el registro de ayer y borra los caducados."""
    log_file = Path(CR.get_directory_of(CR.DirectoryType.LOG)).resolve() / LOG_FILE_NAME
    result = apply_log_retention(
        log_file,
        today=datetime.now(timezone.utc).date(),
        retention_days=CR.logs_config().retention_days,
    )
    if result.archived_file or result.deleted_files:
        logger.info(
            "Retención del registro: archivado=%s, borrados=%d",
            result.archived_file.name if result.archived_file else "nada",
            len(result.deleted_files),
        )


class LogRetentionScheduler:
    """Ciclo de vida del scheduler de retención del registro de actividad."""

    _scheduler: Optional[BackgroundScheduler] = None

    @classmethod
    def start(cls) -> None:
        """Arranca el scheduler y registra el job diario. Idempotente."""
        if cls._scheduler is not None:
            return
        cls._scheduler = make_background_scheduler()
        cls._scheduler.add_job(
            func=_run_log_retention,
            trigger=CronTrigger.from_crontab(_RETENTION_CRON, timezone=timezone.utc),
            id="system_log_retention",
            replace_existing=True,
            max_instances=1,
            name="Retención del registro de actividad",
        )
        cls._scheduler.start()
        logger.info("Scheduler de retención del registro iniciado (%s UTC)", _RETENTION_CRON)

    @classmethod
    def stop(cls) -> None:
        """Detiene el scheduler. Idempotente."""
        if cls._scheduler is None:
            return
        cls._scheduler.shutdown(wait=True)
        cls._scheduler = None
        logger.info("Scheduler de retención del registro detenido")
