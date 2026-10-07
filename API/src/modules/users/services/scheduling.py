"""Scheduler de avisos de seguridad de la capa de usuarios."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.modules.infrastructure.scheduling import make_background_scheduler, scheduler_job

from .mfa_notices import send_mfa_reminders

logger = logging.getLogger(__name__)


@scheduler_job(logger, "Fallo borrando las exportaciones de datos caducadas")
def purge_expired_exports_job() -> None:
    """Borra los ZIP de exportación caducados. Lo dispara el planificador cada hora."""
    from ..managers import DataExportManager

    removed = DataExportManager().purge_expired_exports()
    if removed:
        logger.info("Se borraron %d fichero(s) de exportación de datos caducados", removed)


class UsersScheduler:
    """Ciclo de vida del job periódico de recordatorios MFA."""

    _scheduler: Optional[BackgroundScheduler] = None

    @classmethod
    def start(cls) -> None:
        """Arranca el scheduler. Idempotente."""
        if cls._scheduler is not None:
            return

        cls._scheduler = make_background_scheduler()
        cls._scheduler.add_job(
            func=cls._run_mfa_reminders,
            # La cadencia de envío real la decide last_mfa_reminder_at y la
            # configuración; revisar a diario evita depender de un reinicio.
            trigger=CronTrigger(hour=9, minute=0),
            id="users_mfa_reminders",
            replace_existing=True,
            max_instances=1,
            name="Recordatorios de MFA",
        )
        cls._scheduler.add_job(
            func=purge_expired_exports_job,
            # El plazo de descarga es de horas: revisar cada hora borra el ZIP
            # poco después de que caduque, sin mantener un job por exportación.
            trigger=IntervalTrigger(hours=1),
            id="users_purge_exports",
            replace_existing=True,
            max_instances=1,
            name="Borrado de exportaciones de datos caducadas",
        )
        cls._scheduler.start()
        logger.info("Scheduler de users iniciado")

    @classmethod
    def stop(cls) -> None:
        if cls._scheduler is not None:
            cls._scheduler.shutdown(wait=False)
            cls._scheduler = None

    @staticmethod
    @scheduler_job(logger, "Fallo enviando los recordatorios MFA")
    def _run_mfa_reminders() -> None:
        send_mfa_reminders()


