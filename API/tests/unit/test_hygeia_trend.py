"""
Tests de la regresión lineal y de la estimación de días hasta llenarse
(``hygeia/services/stats.py``).

Son funciones puras: entra una lista de ``(instante, valor)`` construida a
mano y salen la pendiente, el ajuste y la estimación. Lo que fijan estos tests
no es tanto que la cuenta sea correcta —que también— como que la función se
**niegue** a estimar cuando no hay base para hacerlo: ese es el contrato que
la hace útil, porque una fecha inventada invita a actuar sobre nada.
"""

from datetime import datetime, timedelta

import pytest

from src.modules.features.hygeia.services.stats import (
    ALREADY_FULL,
    INSUFFICIENT_SAMPLES,
    INSUFFICIENT_TREND,
    estimate_days_until_full,
    fit_linear_trend,
)

pytestmark = pytest.mark.unit

_ORIGIN = datetime(2026, 9, 1, 12, 0, 0)

# Umbrales de confianza con los que se prueba la estimación; son los mismos
# valores que viajan en la configuración por defecto.
_MIN_R_SQUARED = 0.5
_MIN_SLOPE = 0.05


def _daily(values: list, step: timedelta = timedelta(days=1)) -> list:
    """Una muestra por valor, separadas ``step`` a partir de ``_ORIGIN``."""
    return [(_ORIGIN + step * position, value) for position, value in enumerate(values)]


# =============================================================================
# EL AJUSTE DE LA RECTA
# =============================================================================

def test_a_perfectly_linear_series_recovers_its_own_slope():
    """Una serie que sube dos puntos al día da pendiente 2 y ajuste perfecto."""
    trend = fit_linear_trend(_daily([10.0, 12.0, 14.0, 16.0, 18.0]))

    assert trend.slope_per_day == pytest.approx(2.0)
    assert trend.r_squared == pytest.approx(1.0)
    assert trend.sample_count == 5
    assert trend.first_instant == _ORIGIN


def test_a_falling_series_has_a_negative_slope():
    """Un disco que se vacía da pendiente negativa, no un valor absoluto."""
    trend = fit_linear_trend(_daily([50.0, 45.0, 40.0]))

    assert trend.slope_per_day == pytest.approx(-5.0)


def test_a_flat_series_fits_perfectly_and_goes_nowhere():
    """Una serie plana tiene ajuste 1 y pendiente 0.

    La recta la explica entera —no hay variación que dejar sin explicar—, así
    que el ajuste es perfecto aunque la serie no vaya a ninguna parte. Es
    justo el caso en el que fiarse solo del R² daría una falsa confianza, y
    por eso la estimación exige además una pendiente mínima.
    """
    trend = fit_linear_trend(_daily([70.0, 70.0, 70.0, 70.0]))

    assert trend.slope_per_day == pytest.approx(0.0)
    assert trend.r_squared == pytest.approx(1.0)


def test_a_noisy_series_keeps_a_slope_but_loses_its_fit():
    """Una serie que zigzaguea sin dirección da un ajuste bajo."""
    trend = fit_linear_trend(_daily([10.0, 80.0, 15.0, 75.0, 20.0, 70.0]))

    assert trend.r_squared < _MIN_R_SQUARED


def test_a_single_sample_is_not_a_trend():
    """Con una sola muestra no hay recta: todo el ajuste viene nulo."""
    trend = fit_linear_trend(_daily([42.0]))

    assert trend.slope_per_day is None
    assert trend.r_squared is None
    assert trend.sample_count == 1


def test_samples_at_the_very_same_instant_are_not_a_trend():
    """Sin eje temporal no hay pendiente que medir, por muchas muestras que haya."""
    trend = fit_linear_trend([(_ORIGIN, 10.0), (_ORIGIN, 20.0), (_ORIGIN, 30.0)])

    assert trend.slope_per_day is None
    assert trend.sample_count == 3


def test_samples_without_value_are_discarded():
    """Un latido sin dato de disco es ausencia de dato, no un cero.

    Las tres muestras con dato caen a los días 0, 2 y 4 y suben dos puntos
    cada vez: un punto por día. Si los ``None`` contaran como cero, la serie
    se desplomaría dos veces hasta el suelo y la pendiente saldría otra.
    """
    samples = _daily([10.0, None, 12.0, None, 14.0])

    trend = fit_linear_trend(samples)

    assert trend.sample_count == 3
    assert trend.slope_per_day == pytest.approx(1.0)


def test_the_order_of_the_samples_does_not_matter():
    """La serie se ordena por instante antes de ajustar."""
    ordered = fit_linear_trend(_daily([10.0, 12.0, 14.0]))
    shuffled = fit_linear_trend(list(reversed(_daily([10.0, 12.0, 14.0]))))

    assert shuffled.slope_per_day == pytest.approx(ordered.slope_per_day)
    assert shuffled.first_instant == ordered.first_instant


def test_an_empty_series_is_an_empty_trend():
    """Sin muestras, el ajuste es el vacío y no revienta."""
    trend = fit_linear_trend([])

    assert trend.slope_per_day is None
    assert trend.sample_count == 0


# =============================================================================
# LA ESTIMACIÓN DE DÍAS HASTA LLENARSE
# =============================================================================

def _forecast(values: list, current: float = None):
    """Ajusta la serie y estima, con los umbrales de confianza por defecto."""
    trend = fit_linear_trend(values)
    latest = values[-1][1] if current is None else current
    return estimate_days_until_full(trend, latest, 100.0, _MIN_R_SQUARED, _MIN_SLOPE)


def test_a_clear_slope_gives_a_correct_estimate():
    """Un disco al 80 % que sube dos puntos al día se llena en diez días."""
    forecast = _forecast(_daily([72.0, 74.0, 76.0, 78.0, 80.0]))

    assert forecast.days_until_full == pytest.approx(10.0)
    assert forecast.reason is None


def test_the_estimate_starts_from_the_current_value_and_not_from_the_line():
    """La cuenta arranca del valor actual, no del que la recta predice para hoy.

    Lo que le queda a un disco se mide desde donde está; la recta solo dice a
    qué ritmo se mueve. Sobre una serie con un último punto por debajo de su
    recta, estimar desde la recta daría menos días de los que quedan.
    """
    forecast = _forecast(_daily([50.0, 61.0, 70.0, 81.0, 90.0]), current=90.0)

    trend = fit_linear_trend(_daily([50.0, 61.0, 70.0, 81.0, 90.0]))
    assert forecast.days_until_full == pytest.approx(10.0 / trend.slope_per_day)


def test_a_flat_series_refuses_to_estimate():
    """Un disco quieto no devuelve una fecha, devuelve la razón."""
    forecast = _forecast(_daily([70.0, 70.0, 70.0]))

    assert forecast.days_until_full is None
    assert forecast.reason == INSUFFICIENT_TREND


def test_an_oscillating_series_refuses_to_estimate():
    """Un disco que oscila entre el 60 y el 62 % no está creciendo.

    Su pendiente es minúscula y de un signo u otro según el tramo; proyectarla
    daría cifras que cambian solas con el disco quieto.
    """
    forecast = _forecast(_daily([60.0, 62.0, 60.5, 61.5, 60.2, 61.8]))

    assert forecast.days_until_full is None
    assert forecast.reason == INSUFFICIENT_TREND


def test_a_shrinking_disk_refuses_to_estimate():
    """Un disco que se vacía nunca se va a llenar: no hay nada que estimar."""
    forecast = _forecast(_daily([90.0, 80.0, 70.0]))

    assert forecast.days_until_full is None
    assert forecast.reason == INSUFFICIENT_TREND


def test_a_noisy_climb_refuses_to_estimate():
    """Una subida a saltos impredecibles no sostiene una fecha.

    La pendiente es claramente positiva y aun así la estimación se retira: el
    ajuste es demasiado malo para creerse el ritmo, y es la diferencia entre
    "sube" y "sube a este ritmo".
    """
    values = _daily([10.0, 90.0, 20.0, 95.0, 30.0, 99.0])

    trend = fit_linear_trend(values)
    forecast = estimate_days_until_full(trend, 99.0, 100.0, _MIN_R_SQUARED, _MIN_SLOPE)

    assert trend.slope_per_day > _MIN_SLOPE
    assert trend.r_squared < _MIN_R_SQUARED
    assert forecast.days_until_full is None
    assert forecast.reason == INSUFFICIENT_TREND


def test_too_few_samples_refuse_to_estimate():
    """Con una sola muestra la razón distingue el caso de una tendencia floja."""
    forecast = _forecast(_daily([80.0]))

    assert forecast.days_until_full is None
    assert forecast.reason == INSUFFICIENT_SAMPLES


def test_a_series_without_a_current_value_refuses_to_estimate():
    """Sin valor actual no hay desde dónde contar."""
    trend = fit_linear_trend(_daily([10.0, 12.0, 14.0]))

    forecast = estimate_days_until_full(trend, None, 100.0, _MIN_R_SQUARED, _MIN_SLOPE)

    assert forecast.days_until_full is None
    assert forecast.reason == INSUFFICIENT_SAMPLES


def test_a_disk_already_full_reports_zero_days():
    """Un disco que ya está al 100 % no tiene días por delante, tiene cero."""
    forecast = _forecast(_daily([96.0, 98.0, 100.0]))

    assert forecast.days_until_full == pytest.approx(0.0)
    assert forecast.reason == ALREADY_FULL


def test_a_disk_over_the_ceiling_is_also_already_full():
    """Un valor por encima del techo no da días negativos."""
    trend = fit_linear_trend(_daily([98.0, 100.0]))

    forecast = estimate_days_until_full(trend, 104.0, 100.0, _MIN_R_SQUARED, _MIN_SLOPE)

    assert forecast.days_until_full == pytest.approx(0.0)
    assert forecast.reason == ALREADY_FULL


def test_a_stricter_fit_threshold_withdraws_a_borderline_estimate():
    """Subir el R² exigido retira una estimación que antes pasaba.

    Es lo que hace configurable el umbral: un despliegue que prefiera callarse
    más a menudo lo sube, y el mismo disco deja de tener fecha.
    """
    values = _daily([70.0, 73.0, 74.0, 79.0, 80.0, 86.0])
    trend = fit_linear_trend(values)

    tolerant = estimate_days_until_full(trend, 86.0, 100.0, 0.5, _MIN_SLOPE)
    strict = estimate_days_until_full(trend, 86.0, 100.0, 0.999, _MIN_SLOPE)

    assert tolerant.days_until_full is not None
    assert strict.days_until_full is None
    assert strict.reason == INSUFFICIENT_TREND
