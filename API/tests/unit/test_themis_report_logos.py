"""
Cada informe de Themis tiene que encontrar su logotipo.

El generador de PDF no revienta cuando falta el logotipo: deja un aviso en el
registro y sigue sin él. Por eso un nombre mal escrito o una imagen que no se
copió al módulo no rompen nada visible en los tests de generación; hace falta
comprobar el fichero directamente.
"""

import pytest

from src.modules.features.themis.model import ScanType
from src.modules.features.themis.services.reports.base import PrintingStrategy
from src.modules.features.themis.services.reports.creator import LOGO_DIRECTORY

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("scan_type", list(ScanType), ids=lambda scan_type: scan_type.value)
def test_every_scan_type_report_has_a_logo_that_exists(scan_type):
    strategy_class = PrintingStrategy._registry[scan_type]  # pylint: disable=protected-access
    # Sin __init__: construirla exige un escaneo de la base de datos, y el
    # nombre del logotipo no depende de él.
    strategy = strategy_class.__new__(strategy_class)

    logo_path = LOGO_DIRECTORY / strategy.get_logo_filename()

    assert logo_path.is_file(), f"{scan_type.value}: falta {logo_path.name} en {LOGO_DIRECTORY}"


@pytest.mark.parametrize("logo_path", sorted(LOGO_DIRECTORY.glob("*.png")), ids=lambda path: path.name)
def test_logos_stay_small_enough_to_embed_in_every_report(logo_path):
    """Cada PDF lleva el logotipo embebido: un original de la SPA pesa ~0,5 MB."""
    assert logo_path.stat().st_size < 100_000
