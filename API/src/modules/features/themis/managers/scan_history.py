"""Estadísticas históricas de escaneos por host, para gráficas e informes."""

import logging
from typing import List
import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from ..repositories import ProgramedScanRepository, ScanRepository
from ..model import ScanType
from ..services import HistoryStatsService


logger = logging.getLogger(__name__)


class ScanHistoryManager:
    """
    Manager for per-host historical scan statistics.

    Orchestrates UnitOfWork + ScanRepository + HistoryStatsService to produce
    the chart-ready payload consumed by both the REST endpoint and the PDF
    report. Every query is scoped to the owning user, so a user can only ever
    see statistics built from their own scans.
    """

    def list_scanned_hosts(self, user_id: int) -> List[dict]:
        """Return the distinct hosts the user has finished scanning."""
        with UnitOfWork() as uow:
            return ScanRepository(uow).get_scanned_targets(user_id)

    def get_stats(self, user_id: int) -> dict:
        """Return the user's scan counts grouped by type.

        Args:
            user_id: Owner user primary key (scopes the counts to this user).

        Returns:
            A dict with per-type counts (``nmap``/``nikto``/``lybra``/
            ``nuclei``) plus a ``total`` (see ``ScanRepository.get_stats``).
        """
        with UnitOfWork() as uow:
            return ScanRepository(uow).get_stats(user_id)

    def get_vulnerability_management_summary(self, user_id: int) -> dict:
        """El estado de la gestión de vulnerabilidades de un usuario, para quien lo necesite.

        Lo consume Eunomia como evidencia automática: no expone repositorios ni hallazgos
        individuales, solo cifras.

        Args:
            user_id: Usuario cuyos escaneos se resumen (solo los suyos).

        Returns:
            dict: ``lastFinishedAt`` (``None`` si ninguno terminó), ``activeScheduledScans``,
                ``openFindings`` y ``openCritical``.
        """
        with UnitOfWork() as uow:
            summary = ScanRepository(uow).get_vulnerability_summary(user_id)
            summary["activeScheduledScans"] = ProgramedScanRepository(uow).count_active(user_id)
        return summary

    def get_host_history(self, user_id: int, target: str, scan_type: ScanType) -> dict:
        """Build the historical statistics payload for a host + tool.

        Args:
            user_id:   Owner user primary key (enforces the security scope).
            target:    The scanned host.
            scan_type: The tool discriminator.

        Returns:
            JSON-serializable statistics payload (see HistoryStatsService.build).
        """
        scan_type = ScanType(scan_type)
        limit = CR.themis_history().max_scans
        with UnitOfWork() as uow:
            scans = ScanRepository(uow).get_recent_finished(
                user_id, target, scan_type, limit
            )
            scans = list(reversed(scans))  # ascending (oldest -> newest) for charting
            return HistoryStatsService().build(scans, scan_type, target)

