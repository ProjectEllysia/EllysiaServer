"""Nombre de fichero de las exportaciones de estadísticas de Hygeia.

``build_export_file_name`` decide con qué nombre se descarga un CSV de
estadísticas: lleva el juego de datos, el alcance y el periodo, que es lo que
distingue dos descargas en la carpeta de descargas.
"""

import pytest

from src.modules.features.hygeia.services.export import build_export_file_name

pytestmark = pytest.mark.unit


def test_it_carries_the_dataset_the_scope_and_the_period():
    assert build_export_file_name("summary", "host-web", "24h") == "hygeia-summary-host-web-24h.csv"


# Un hostname o una etiqueta pueden traer acentos, mayúsculas y espacios.
def test_it_normalizes_accents_case_and_separators():
    assert (
        build_export_file_name("summary", "Host-Web · Producción", "7d")
        == "hygeia-summary-host-web-produccion-7d.csv"
    )


def test_the_fleet_has_no_scope_to_name():
    assert build_export_file_name("ranking", None, "7d") == "hygeia-ranking-7d.csv"


def test_the_overview_has_no_period():
    assert build_export_file_name("overview", None, None) == "hygeia-overview.csv"


def test_it_never_leaves_dangling_separators():
    file_name = build_export_file_name("tag-stats", " ?? ", "24h")
    assert file_name == "hygeia-tag-stats-24h.csv"
    assert "--" not in file_name and "-." not in file_name
