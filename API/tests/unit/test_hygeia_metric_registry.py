"""
Tests unitarios de hygeia.services.metric_registry: el catálogo cerrado de
métricas sobre las que se piden estadísticas y la traducción de su nombre
público a la columna (o al extractor del JSONB) de la que sale el valor.

Sin base de datos: los snapshots se construyen en memoria, sin sesión.
"""

from datetime import datetime

import pytest

from src.modules.features.hygeia.exceptions import UnknownMetricError
from src.modules.features.hygeia.model import AssetSnapshot
from src.modules.features.hygeia.services.metric_registry import (
    METRIC_REGISTRY,
    MetricDefinition,
    assert_metric_definition,
)

pytestmark = pytest.mark.unit

#: Claves de ``AssetSnapshot.to_dict`` que no son una métrica numérica: los
#: dos relojes, el montaje asociado a ``diskMaxPct`` y los dos campos que
#: describen de dónde sale ``powerWatts``.
_NON_METRIC_KEYS = {
    "collectedAt", "receivedAt", "diskMaxMount", "powerEstimated", "powerSource",
}


def _snapshot(**columns) -> AssetSnapshot:
    """Snapshot en memoria con las columnas dadas y el resto a ``None``."""
    return AssetSnapshot(
        asset_id=1, collected_at=datetime(2026, 1, 1), received_at=datetime(2026, 1, 1),
        metrics={}, **columns,
    )


def test_registry_covers_every_numeric_field_of_the_snapshot():
    """Una métrica desnormalizada nueva en ``to_dict`` sin entrada en el registro rompe aquí."""
    numeric_keys = set(_snapshot().to_dict()) - _NON_METRIC_KEYS

    assert set(METRIC_REGISTRY) == numeric_keys


def test_there_are_eight_column_metrics_including_power():
    """Las siete métricas de sistema más ``powerWatts``, todas con columna propia."""
    assert len(METRIC_REGISTRY) == 8
    assert "powerWatts" in METRIC_REGISTRY
    assert all(definition.is_column_backed for definition in METRIC_REGISTRY.values())


@pytest.mark.parametrize("name", sorted(METRIC_REGISTRY))
def test_column_metric_extracts_the_model_attribute(name):
    """El valor extraído es el del atributo real del modelo, como ``float``."""
    definition = METRIC_REGISTRY[name]
    snapshot = _snapshot(**{definition.column.key: 42})

    value = definition.extract_value(snapshot)

    assert value == getattr(snapshot, definition.column.key)
    assert isinstance(value, float)
    assert definition.column is getattr(AssetSnapshot, definition.column.key)


def test_a_missing_value_stays_missing_instead_of_becoming_zero():
    """Un host sin fuente de potencia no consume 0 W: su valor sigue siendo ``None``."""
    snapshot = _snapshot(cpu_pct=12.5)

    assert METRIC_REGISTRY["powerWatts"].extract_value(snapshot) is None
    assert METRIC_REGISTRY["cpuPct"].extract_value(snapshot) == 12.5


def test_unknown_metric_is_a_400_with_the_valid_catalogue():
    """Un nombre fuera del registro da un error de validación claro, no un ``AttributeError``."""
    with pytest.raises(UnknownMetricError) as raised:
        assert_metric_definition("cpu_pct")

    error = raised.value
    assert error.status_code == 400
    assert error.expose_details is True
    assert error.details["metric"] == "cpu_pct"
    assert error.details["valid_metrics"] == sorted(METRIC_REGISTRY)


def test_known_metric_resolves_to_its_definition():
    """Un nombre registrado devuelve su definición."""
    assert assert_metric_definition("memPct") is METRIC_REGISTRY["memPct"]


def test_a_jsonb_metric_fits_the_same_definition_without_a_column():
    """El punto de extensión para el JSONB: una definición sin columna y con su extractor."""
    root_disk = MetricDefinition(
        name="rootDiskPct",
        extractor=lambda snapshot: snapshot.metrics["disk"]["/"]["usagePct"],
    )
    snapshot = AssetSnapshot(metrics={"disk": {"/": {"usagePct": 71.0}}})

    assert root_disk.is_column_backed is False
    assert root_disk.extract_value(snapshot) == 71.0


def test_registry_is_read_only():
    """El catálogo no se puede ampliar en tiempo de ejecución."""
    with pytest.raises(TypeError):
        METRIC_REGISTRY["newMetric"] = METRIC_REGISTRY["cpuPct"]
