"""
Tests de la señal de coincidencia entre picos de métricas distintas
(``hygeia/services/stats.py::detect_peak_coincidence``).

La señal es deliberadamente modesta: compara los instantes de dos máximos que
el resumen ya había localizado y dice si cayeron cerca. Lo que estos tests
fijan es que no se fuerce una coincidencia donde no la hay, que la ausencia de
pico no se cuele como coincidencia, y que la separación viaje siempre para que
quien lee la señal pueda juzgarla en vez de creerse un booleano.
"""

from datetime import datetime, timedelta

import pytest

from src.modules.features.hygeia.services.stats import (
    METRICS_NOT_COMPARED,
    NO_PEAK,
    StatSummary,
    detect_peak_coincidence,
)

pytestmark = pytest.mark.unit

_ORIGIN = datetime(2026, 9, 1, 12, 0, 0)
_TOLERANCE_SEC = 300
_COUNTERPARTS = ("netRxBps", "netTxBps")


def _summary(peak_instant) -> StatSummary:
    """Un resumen del que solo importa el instante del máximo."""
    return StatSummary(
        minimum=0.0, maximum=100.0, average=50.0, percentile_95=90.0, current=50.0,
        timestamp_of_minimum=_ORIGIN, timestamp_of_maximum=peak_instant,
        sample_count=0 if peak_instant is None else 10,
    )


def _pairing(coincidence, metric: str):
    """La pareja de una métrica concreta dentro del resultado."""
    return next(pairing for pairing in coincidence.pairings if pairing.metric == metric)


def test_two_peaks_at_the_same_instant_coincide():
    """Dos máximos en el mismo latido son la coincidencia más clara posible."""
    summaries = {"cpuPct": _summary(_ORIGIN), "netRxBps": _summary(_ORIGIN)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert coincidence.is_any_coincident is True
    assert _pairing(coincidence, "netRxBps").separation_seconds == pytest.approx(0.0)
    assert coincidence.reason is None


def test_peaks_inside_the_window_coincide():
    """Dos minutos de separación entran en una ventana de cinco."""
    summaries = {
        "cpuPct": _summary(_ORIGIN),
        "netRxBps": _summary(_ORIGIN + timedelta(minutes=2)),
    }

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert _pairing(coincidence, "netRxBps").is_coincident is True
    assert _pairing(coincidence, "netRxBps").separation_seconds == pytest.approx(120.0)


def test_peaks_outside_the_window_do_not_coincide():
    """Seis horas de separación no se fuerzan como coincidencia."""
    summaries = {
        "cpuPct": _summary(_ORIGIN),
        "netRxBps": _summary(_ORIGIN + timedelta(hours=6)),
    }

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert coincidence.is_any_coincident is False
    assert _pairing(coincidence, "netRxBps").is_coincident is False
    assert _pairing(coincidence, "netRxBps").separation_seconds == pytest.approx(21600.0)
    assert coincidence.reason is None


def test_the_separation_is_a_distance_and_not_an_order():
    """Un pico anterior al de referencia separa lo mismo que uno posterior.

    La señal no afirma cuál vino antes —para eso están los dos instantes en la
    respuesta—, solo cuánto distaron.
    """
    earlier = detect_peak_coincidence(
        {"cpuPct": _summary(_ORIGIN), "netRxBps": _summary(_ORIGIN - timedelta(minutes=3))},
        "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC,
    )
    later = detect_peak_coincidence(
        {"cpuPct": _summary(_ORIGIN), "netRxBps": _summary(_ORIGIN + timedelta(minutes=3))},
        "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC,
    )

    assert _pairing(earlier, "netRxBps").separation_seconds == pytest.approx(180.0)
    assert _pairing(later, "netRxBps").separation_seconds == pytest.approx(180.0)


def test_the_boundary_of_the_window_still_counts():
    """Una separación exactamente igual a la tolerancia coincide."""
    summaries = {
        "cpuPct": _summary(_ORIGIN),
        "netRxBps": _summary(_ORIGIN + timedelta(seconds=_TOLERANCE_SEC)),
    }

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert _pairing(coincidence, "netRxBps").is_coincident is True


def test_one_coincident_pairing_is_enough_for_the_signal():
    """La señal global se enciende si al menos una métrica hizo pico a la vez."""
    summaries = {
        "cpuPct": _summary(_ORIGIN),
        "netRxBps": _summary(_ORIGIN + timedelta(hours=8)),
        "netTxBps": _summary(_ORIGIN + timedelta(seconds=30)),
    }

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert coincidence.is_any_coincident is True
    assert _pairing(coincidence, "netRxBps").is_coincident is False
    assert _pairing(coincidence, "netTxBps").is_coincident is True


def test_a_counterpart_without_samples_never_coincides():
    """Una métrica sin pico no coincide con nada: no hay instante que comparar.

    El riesgo que cierra este test es que un instante ausente se tratara como
    el origen del tiempo y produjera una separación enorme, o peor, como el
    mismo instante y produjera una coincidencia falsa.
    """
    summaries = {"cpuPct": _summary(_ORIGIN), "netRxBps": _summary(None)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert _pairing(coincidence, "netRxBps").is_coincident is False
    assert _pairing(coincidence, "netRxBps").separation_seconds is None
    assert coincidence.is_any_coincident is False
    assert coincidence.reason is None


def test_a_reference_without_samples_gives_no_signal():
    """Sin pico de referencia no hay señal, y se dice por qué."""
    summaries = {"cpuPct": _summary(None), "netRxBps": _summary(_ORIGIN)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert coincidence.reason == NO_PEAK
    assert coincidence.pairings == ()
    assert coincidence.is_any_coincident is False


def test_a_summary_without_the_reference_metric_gives_no_signal():
    """Si la petición no resumió la CPU, no hay nada contra lo que comparar."""
    summaries = {"netRxBps": _summary(_ORIGIN), "netTxBps": _summary(_ORIGIN)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert coincidence.reason == METRICS_NOT_COMPARED
    assert coincidence.pairings == ()


def test_a_summary_without_any_counterpart_gives_no_signal():
    """Con la referencia sola tampoco hay cruce posible."""
    summaries = {"cpuPct": _summary(_ORIGIN), "memPct": _summary(_ORIGIN)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert coincidence.reason == METRICS_NOT_COMPARED


def test_only_the_requested_counterparts_are_compared():
    """Una métrica que no está en el resumen se ignora, no rompe la señal."""
    summaries = {"cpuPct": _summary(_ORIGIN), "netRxBps": _summary(_ORIGIN)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, _TOLERANCE_SEC)

    assert [pairing.metric for pairing in coincidence.pairings] == ["netRxBps"]


def test_the_tolerance_travels_in_the_result():
    """La ventana aplicada viaja en la respuesta, para poder ponderar la señal."""
    summaries = {"cpuPct": _summary(_ORIGIN), "netRxBps": _summary(_ORIGIN)}

    coincidence = detect_peak_coincidence(summaries, "cpuPct", _COUNTERPARTS, 60)

    assert coincidence.tolerance_seconds == 60
    assert coincidence.reference_instant == _ORIGIN
