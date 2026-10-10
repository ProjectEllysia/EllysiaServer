"""
Scheduler de Eunomia: purga diaria de los marcos archivados que pasaron su plazo.

Propio del módulo y no compartido con los de otras features, a propósito: no se acopla a
módulos hermanos solo por compartir mecanismo (``CLAUDE.md``, § Scheduling).
"""

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.modules.infrastructure.scheduling import make_background_scheduler, scheduler_job

from ..managers import EunomiaFrameworkManager

logger = logging.getLogger(__name__)


class EunomiaScheduler:
    """Ciclo de vida del job de purga de marcos archivados."""

    _scheduler: Optional[BackgroundScheduler] = None

    @classmethod
    def start(cls) -> None:
        """Arranca el scheduler. Idempotente."""
        if cls._scheduler is not None:
            return
        cls._scheduler = make_background_scheduler()
        cls._scheduler.add_job(
            func=cls.run_purge,
            # Una vez al día de madrugada: el plazo se mide en días, no en horas.
            trigger=CronTrigger(hour=3, minute=30),
            id="eunomia_purge_archived_frameworks",
            replace_existing=True,
            max_instances=1,
            name="Purga de marcos de cumplimiento archivados",
        )
        cls._scheduler.start()
        logger.info("Scheduler de Eunomia iniciado")

    @classmethod
    def stop(cls) -> None:
        """Para el scheduler si estaba en marcha."""
        if cls._scheduler is not None:
            cls._scheduler.shutdown(wait=False)
            cls._scheduler = None

    @staticmethod
    @scheduler_job(logger, "Fallo purgando los marcos de cumplimiento archivados")
    def run_purge() -> None:
        purged = EunomiaFrameworkManager().purge_expired()
        if purged:
            logger.info("Marcos de cumplimiento purgados: %d", purged)
