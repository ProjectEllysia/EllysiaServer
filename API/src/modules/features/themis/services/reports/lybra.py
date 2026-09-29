"""Estrategia de impresión de los informes del motor Lybra."""

from ...model import ScanType
from ..analyzers import LybraAIWriter
from .base import PrintingStrategy
from .findings import FindingsPrintingStrategy

#: Paleta verde de Lybra cuando ``SecOpsConfig.json`` no trae la suya. La usan
#: el informe de un escaneo Lybra y el de exposición cloud, que son del mismo
#: motor y se tienen que leer como tal.
LYBRA_DEFAULT_PALETTE = {
    "black": "#1A2410", "dark": "#4A6132", "main": "#7CA163",
    "secondary": "#A8C98F", "light": "#D4E8C4", "white": "#F3F8EE",
}


@PrintingStrategy.register(ScanType.LYBRA)
class LybraPrintingStrategy(FindingsPrintingStrategy):
    """Printing strategy for Lybra engine scan reports.

    Color palette: Green theme, matching Lybra's own UI identity. All the
    rendering logic lives in `FindingsPrintingStrategy`; this class only fixes
    Lybra's identity.
    """

    _TOOL = ScanType.LYBRA
    _WRITER_CLASS = LybraAIWriter
    _WRITER_PROMPT_KEY = "lybra"
    _OWN_SOURCE = "lybra"
    _HEADER_TITLE = "Informe del Motor Lybra"
    _REPORT_TITLE = "Veredicto del Motor Lybra"
    _FILENAME_SUFFIX = "_Lybra.pdf"
    _LOGO_FILENAME = "Themis-Turqoise-BgW.png"
    # Traducción a MITRE ATT&CK y a marcos de cumplimiento: exclusiva del motor propio.
    _SHOWS_COMPLIANCE = True
    # Riesgo lateral entre los equipos de un escaneo de red: razonamiento del motor propio.
    _SHOWS_LATERAL_RISK = True
    _DEFAULT_PALETTE = LYBRA_DEFAULT_PALETTE

