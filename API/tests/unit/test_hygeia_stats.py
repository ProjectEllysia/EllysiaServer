"""
Tests unitarios de hygeia.services.stats: el resumen estadístico genérico
(mínimo, máximo, media, percentil 95 y valor actual) y, para la potencia, la
media ponderada por duración, la energía y el coste y su clasificación de
procedencia.

Sin base de datos ni Flask: son funciones puras sobre secuencias de
``(instante, valor)`` construidas a mano.
"""

import random
from datetime import datetime, timedelta
from typing import Optional

import pytest

from src.modules.features.hygeia.services.stats import (
    build_percentile_series,
    calculate_percentile,
    classify_period,
    energy_and_cost,
    resolve_stats_window,
    summarize_series_by_asset,
    summarize_values,
    weighted_average_with_observed_time,
)

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 1, 1, 0, 0, 0)


def _series(hours: list[Optional[float]]) -> list[tuple[datetime, Optional[float]]]:
    """Construye ``(instante, valor)`` a razón de una muestra por hora; ``None`` es una muestra sin dato."""
    return [(_T0 + timedelta(hours=i), value) for i, value in enumerate(hours)]


# =============================================================================
# MEDIA PONDERADA POR DURACIÓN
# =============================================================================

def test_regular_samples_match_the_simple_average():
    """Con intervalos regulares y potencia constante, la ponderada coincide con la aritmética."""
    samples = _series([200.0] * 6)
    result = weighted_average_with_observed_time(samples)
    assert result.average_watts == pytest.approx(200.0)
    assert result.observed == timedelta(hours=5)


def test_the_plans_literal_example_12h_on_12h_gap():
    """200 W durante 12 h y 12 h sin datos: la media es 200 W, no 100 W."""
    samples = [
        (_T0, 200.0),
        (_T0 + timedelta(hours=1), 200.0),
        (_T0 + timedelta(hours=12), 200.0),
        (_T0 + timedelta(hours=13), 200.0),
    ]
    result = weighted_average_with_observed_time(samples)
    assert result.average_watts == pytest.approx(200.0)
    # Solo los dos tramos de 1 h entran; el hueco de 11 h queda excluido.
    assert result.observed == timedelta(hours=2)


def test_a_long_gap_in_the_middle_is_excluded():
    samples = [
        (_T0, 100.0),
        (_T0 + timedelta(minutes=1), 120.0),
        (_T0 + timedelta(hours=5), 300.0),
        (_T0 + timedelta(hours=5, minutes=1), 310.0),
    ]
    result = weighted_average_with_observed_time(samples)
    # Los dos tramos que sobreviven pesan 100 y 300, ambos de 1 minuto.
    assert result.average_watts == pytest.approx(200.0)
    assert result.observed == timedelta(minutes=2)


def test_a_single_isolated_sample_has_no_observed_time():
    """Ni una muestra, cero intervalos: la media es None, no un valor inventado."""
    result = weighted_average_with_observed_time([(_T0, 150.0)])
    assert result.average_watts is None
    assert result.observed == timedelta(0)


def test_empty_series_has_no_observed_time():
    result = weighted_average_with_observed_time([])
    assert result.average_watts is None
    assert result.observed == timedelta(0)


def test_unordered_input_is_sorted_before_computing():
    samples = [
        (_T0 + timedelta(hours=1), 100.0),
        (_T0, 50.0),
        (_T0 + timedelta(hours=2), 150.0),
    ]
    result = weighted_average_with_observed_time(samples)
    # 50 W durante la primera hora + 100 W durante la segunda.
    assert result.average_watts == pytest.approx(75.0)
    assert result.observed == timedelta(hours=2)


# =============================================================================
# ENERGÍA Y COSTE
# =============================================================================

def test_the_plans_literal_example_250w_4h_1kwh():
    kwh, cost = energy_and_cost(250.0, timedelta(hours=4), price_per_kwh=0.15)
    assert kwh == pytest.approx(1.0)
    assert cost == pytest.approx(0.15)


def test_energy_is_computed_over_observed_time_not_the_full_period():
    """Un hueco largo dentro del periodo no debe imputarse como consumo."""
    # 2 h observadas a 500 W, aunque el "periodo" pedido fuera mucho mayor.
    kwh, cost = energy_and_cost(500.0, timedelta(hours=2), price_per_kwh=0.20)
    assert kwh == pytest.approx(1.0)
    assert cost == pytest.approx(0.20)


def test_no_observed_time_yields_none_not_zero():
    """Un activo del que no se sabe nada no ha consumido cero euros."""
    kwh, cost = energy_and_cost(None, timedelta(0), price_per_kwh=0.15)
    assert kwh is None
    assert cost is None


def test_zero_observed_duration_with_average_still_yields_none():
    kwh, cost = energy_and_cost(100.0, timedelta(0), price_per_kwh=0.15)
    assert kwh is None
    assert cost is None


# =============================================================================
# CLASIFICACIÓN DE PROCEDENCIA
# =============================================================================

def test_full_coverage_within_retention_is_observed():
    result = classify_period(
        _T0, _T0 + timedelta(hours=24), observed=timedelta(hours=23),
        retention_days=30,
    )
    assert result.classification == "observed"
    assert result.coverage_fraction == pytest.approx(23 / 24)


def test_partial_coverage_within_retention_is_observed_partial():
    result = classify_period(
        _T0, _T0 + timedelta(hours=24), observed=timedelta(hours=12),
        retention_days=30,
    )
    assert result.classification == "observed_partial"
    assert result.coverage_fraction == pytest.approx(0.5)


def test_a_period_longer_than_retention_is_always_projected():
    """Un año excede la retención: siempre proyectado, tenga o no cobertura completa."""
    result = classify_period(
        _T0, _T0 + timedelta(days=365), observed=timedelta(days=365),
        retention_days=30,
    )
    assert result.classification == "projected"
    assert result.coverage_fraction is None


def test_period_exactly_at_the_retention_boundary_is_not_projected():
    result = classify_period(
        _T0, _T0 + timedelta(days=30), observed=timedelta(days=29),
        retention_days=30,
    )
    assert result.classification in ("observed", "observed_partial")


def test_coverage_is_capped_at_one():
    """Un solape de reloj no debe producir una cobertura por encima del 100 %."""
    result = classify_period(
        _T0, _T0 + timedelta(hours=1), observed=timedelta(hours=2),
        retention_days=30,
    )
    assert result.coverage_fraction == 1.0


# =============================================================================
# RESUMEN ESTADÍSTICO GENÉRICO
# =============================================================================

def test_summary_of_known_values():
    """Mínimo, máximo, media, p95 y valor actual de una serie conocida, con sus instantes."""
    samples = _series([10.0, 50.0, 30.0, 20.0])

    summary = summarize_values(samples)

    assert summary.minimum == 10.0
    assert summary.maximum == 50.0
    assert summary.average == pytest.approx(27.5)
    # Ordenados: [10, 20, 30, 50]; posición 0.95 × 3 = 2.85 → 30 + 0.85 × 20.
    assert summary.percentile_95 == pytest.approx(47.0)
    assert summary.current == 20.0
    assert summary.timestamp_of_minimum == _T0
    assert summary.timestamp_of_maximum == _T0 + timedelta(hours=1)
    assert summary.sample_count == 4


def test_summary_ignores_missing_values_instead_of_counting_them_as_zero():
    """Una muestra sin dato no hunde el mínimo ni la media: no es un cero."""
    samples = _series([None, 40.0, None, 60.0])

    summary = summarize_values(samples)

    assert summary.minimum == 40.0
    assert summary.average == pytest.approx(50.0)
    assert summary.current == 60.0
    assert summary.sample_count == 2


def test_summary_without_any_value_is_empty_not_zero():
    """Sin ninguna muestra con dato, todos los agregados son ``None`` y el recuento cero."""
    for samples in ([], _series([None, None])):
        summary = summarize_values(samples)
        assert summary.sample_count == 0
        assert summary.minimum is None
        assert summary.maximum is None
        assert summary.average is None
        assert summary.percentile_95 is None
        assert summary.current is None
        assert summary.timestamp_of_maximum is None


def test_summary_ties_resolve_to_the_earliest_instant():
    """Si el extremo se repite, su instante es el de la primera vez que se alcanzó."""
    samples = _series([5.0, 90.0, 90.0, 5.0])

    summary = summarize_values(samples)

    assert summary.timestamp_of_maximum == _T0 + timedelta(hours=1)
    assert summary.timestamp_of_minimum == _T0


def test_summary_does_not_depend_on_input_order():
    """El valor actual es el de la muestra más reciente, venga en el orden que venga."""
    samples = _series([10.0, 20.0, 30.0, 40.0, 55.0])
    shuffled = samples[:]
    random.Random(7).shuffle(shuffled)

    assert summarize_values(shuffled) == summarize_values(samples)
    assert summarize_values(shuffled).current == 55.0


def test_percentile_uses_linear_interpolation():
    """Mismo resultado que el método ``linear`` de NumPy en los puntos de referencia."""
    values = [5.0, 1.0, 3.0, 2.0, 4.0]

    assert calculate_percentile(values, 0) == 1.0
    assert calculate_percentile(values, 50) == 3.0
    assert calculate_percentile(values, 95) == pytest.approx(4.8)
    assert calculate_percentile(values, 100) == 5.0
    assert calculate_percentile([42.0], 95) == 42.0
    assert calculate_percentile([], 95) is None


@pytest.mark.parametrize("percentile", [-1, 100.5])
def test_percentile_out_of_range_is_a_programming_error(percentile):
    """Un percentil fuera de [0, 100] no se recorta en silencio: lanza."""
    with pytest.raises(ValueError):
        calculate_percentile([1.0, 2.0], percentile)


def test_summary_by_asset_keeps_every_asset_even_without_data():
    """Cada activo conserva su entrada; el que no tiene datos sale con el resumen vacío."""
    series_by_asset = {
        1: _series([10.0, 30.0]),
        2: _series([70.0]),
        3: [],
    }

    summaries = summarize_series_by_asset(series_by_asset)

    assert set(summaries) == {1, 2, 3}
    assert summaries[1].average == pytest.approx(20.0)
    assert summaries[2].maximum == 70.0
    assert summaries[3].sample_count == 0


# =============================================================================
# VENTANA DE UNA CONSULTA DE ESTADÍSTICAS
# =============================================================================

_NOW = datetime(2026, 9, 15, 12, 0, 0)


def test_a_period_longer_than_retention_is_clipped_and_says_so():
    """365 días con 30 de retención: la ventana cubre 30 y lo declara."""
    window = resolve_stats_window(
        timedelta(days=365), _NOW, max_stats_period_days=30, retention_days=30,
    )

    assert window.since == _NOW - timedelta(days=30)
    assert window.until == _NOW
    assert window.covered_duration == timedelta(days=30)
    assert window.requested_duration == timedelta(days=365)
    assert window.is_clipped is True


def test_a_period_within_the_limits_is_left_alone():
    """Una semana cabe en la retención: ni se recorta ni se marca."""
    window = resolve_stats_window(
        timedelta(days=7), _NOW, max_stats_period_days=30, retention_days=30,
    )

    assert window.since == _NOW - timedelta(days=7)
    assert window.is_clipped is False


def test_the_period_exactly_at_the_ceiling_is_not_clipped():
    """Pedir justo el tope no es un recorte."""
    window = resolve_stats_window(
        timedelta(days=30), _NOW, max_stats_period_days=30, retention_days=30,
    )

    assert window.is_clipped is False


@pytest.mark.parametrize(
    "max_stats_period_days, retention_days, expected_days",
    [(10, 30, 10), (90, 30, 30)],
    ids=["the-stats-limit-is-lower", "the-retention-is-lower"],
)
def test_the_ceiling_is_the_lower_of_the_limit_and_the_retention(
    max_stats_period_days, retention_days, expected_days,
):
    """Más allá de la retención no hay datos, aunque el límite lo permita; y al revés."""
    window = resolve_stats_window(
        timedelta(days=365), _NOW,
        max_stats_period_days=max_stats_period_days, retention_days=retention_days,
    )

    assert window.covered_duration == timedelta(days=expected_days)
    assert window.is_clipped is True


@pytest.mark.parametrize("requested_duration", [timedelta(0), timedelta(hours=-1)])
def test_a_non_positive_period_is_a_programming_error(requested_duration):
    """El schema del endpoint ya valida el periodo: aquí un valor no positivo lanza."""
    with pytest.raises(ValueError):
        resolve_stats_window(requested_duration, _NOW, max_stats_period_days=30, retention_days=30)


# =============================================================================
# PERCENTIL POR CUBO DE LA SERIE TEMPORAL
# =============================================================================

def test_percentile_series_groups_each_metric_by_bucket():
    """Cada cubo de una hora lleva el p95 de cada métrica; la que no tiene muestras, ``None``."""
    samples_by_metric = {
        "cpuPct": [(_T0 + timedelta(minutes=minute), float(minute)) for minute in range(1, 6)]
                  + [(_T0 + timedelta(hours=1, minutes=5), 10.0)],
        "memPct": [(_T0 + timedelta(minutes=3), 50.0)],
    }

    series = build_percentile_series(samples_by_metric, bucket_seconds=3600, percentile=95)

    assert [bucket_start for bucket_start, _ in series] == [_T0, _T0 + timedelta(hours=1)]
    first_values, second_values = series[0][1], series[1][1]
    assert first_values["cpuPct"] == pytest.approx(4.8)
    assert first_values["memPct"] == 50.0
    assert second_values == {"cpuPct": 10.0, "memPct": None}


def test_percentile_series_skips_missing_values_and_empty_buckets():
    """Una muestra sin dato no crea un cubo ni cuenta como cero."""
    samples_by_metric = {
        "cpuPct": [(_T0, None), (_T0 + timedelta(hours=2), 40.0)],
    }

    series = build_percentile_series(samples_by_metric, bucket_seconds=3600, percentile=95)

    assert series == [(_T0 + timedelta(hours=2), {"cpuPct": 40.0})]


def test_percentile_series_rejects_a_non_positive_bucket():
    """Un cubo de cero segundos es un error de programación."""
    with pytest.raises(ValueError):
        build_percentile_series({"cpuPct": [(_T0, 1.0)]}, bucket_seconds=0, percentile=95)
