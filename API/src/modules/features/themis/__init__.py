"""
src.modules.features.themis - Módulo de escaneos de seguridad

Exponente:
    - NmapScanManager: Escaneo de puertos
    - NiktoScanManager: Escaneo web
    - Modelos: Scan, Host, Port, etc.
    - Endpoints: themis_bp
"""

from src.modules.system.taskqueue import QueueRegistry

from .model import (
    Host,
    NiktoIncident,
    NiktoScan,
    NmapScan,
    OpenPort,
    Port,
    ProgramedScan,
    Scan,
    ScanFolder,
    ScanIncident,
    ScanStatus,
    ThemisDocument,
    TargetPort,
)

from .managers import (
    NmapScanManager,
    NiktoScanManager,
    OsintManager,
    ProgramedScanManager,
    ScanManager,
    ScanFolderManager,
)

from .repositories import (
    ProgramedScanRepository,
    ScanRepository,
    ThemisReportRepository,
)

from .services import (
    NmapPrintingStrategy,
    NiktoPrintingStrategy,
    PDFCreator,
    ThemisScheduler,
)

from .endpoints import themis_blp
from src.modules.features.eunomia import EvidenceProviderRegistry

# Lo que Themis aporta a Eunomia como evidencia automática (la dependencia va de Themis a Eunomia).
def _vulnerability_evidence(owner_user_id: int, framework_key: str, identifier: str):
    """Resume los escaneos del dueño efectivo para los controles de gestión de vulnerabilidades."""
    from datetime import date

    from .managers.scan_history import ScanHistoryManager
    from .services.compliance_evidence import collect_vulnerability_evidence

    summary = ScanHistoryManager().get_vulnerability_management_summary(owner_user_id)
    return collect_vulnerability_evidence(owner_user_id, framework_key, identifier, summary, date.today())


from .services.compliance_evidence import CONTROLS as _VULNERABILITY_CONTROLS  # noqa: E402

EvidenceProviderRegistry.register(
    "themis.vulnerability_management", name="Gestión de vulnerabilidades",
    controls=_VULNERABILITY_CONTROLS, collect=_vulnerability_evidence,
)

# Registro de las categorías de cola de este módulo (OCP).
QueueRegistry.register(
    "themis.scan", "themis.report", "themis.traceroute", "themis.kbsync", "themis.osint",
)

__all__ = [
    "Host", "NiktoIncident", "NiktoScan", "NmapScan", "OpenPort",
    "Port",
    "ProgramedScan", "Scan", "ScanFolder", "ScanIncident", "ScanStatus",
    "ThemisDocument", "TargetPort",
    "NmapScanManager", "NiktoScanManager", "OsintManager",
    "ProgramedScanManager", "ScanManager", "ScanFolderManager",
    "ProgramedScanRepository", "ScanRepository", "ScanFolderRepository",
    "ThemisReportRepository",
    "themis_blp",
    "PDFCreator", "NmapPrintingStrategy", "NiktoPrintingStrategy",
    "ThemisScheduler",
]
