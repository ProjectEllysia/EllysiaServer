"""
hygeia.services.stats
──────────────────────
Agregados sobre series de métricas ya guardadas.

Dos familias de funciones comparten el módulo:

- **Resumen estadístico genérico** (:func:`summarize_values`,
  :func:`calculate_percentile`, :func:`summarize_series_by_asset`): mínimo,
  máximo, media, percentil 95 y valor actual de cualquier métrica, sobre un
  activo o sobre varios. Es la capa común de la que tiran los endpoints de
  estadísticas por activo, por etiqueta y del parque.
- **Consumo eléctrico** (media ponderada por duración, energía, coste y su
  procedencia): el resumen de potencia de un activo.

Funciones puras: sin ORM, sin Flask. Entra una secuencia de ``(instante,
valor)`` ya leída por el repositorio y salen los números que consume el
manager, así que se prueban con listas construidas a mano.
"""

from __future__ import annotations

import math
from collections.abc import Hashable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple, TypeVar

# Suelo del umbral de hueco cuando la mediana de los intervalos es pequeña o
# no existe (menos de dos muestras). Replica el criterio de `gapThresholdMs`
# del frontend (`chartMath.js`) en su modo "serie cruda" (sin cubo): un
# activo late cada pocos segundos, así que 90 s de silencio ya es una señal,
# no ruido de red.
_GAP_FLOOR = timedelta(seconds=90)

# Múltiplo de la mediana que se considera todavía "el mismo ritmo". El mismo
# factor (3×) que usa `gapThresholdMs`, para que servidor y gráfico no
# discrepen sobre qué es un hueco.
_GAP_MULTIPLIER = 3


class PowerAverage(NamedTuple):
    """Resultado de :func:`weighted_average_with_observed_time`.

    Attributes:
        average_watts: Potencia media ponderada por duración sobre los
            tramos observados, o ``None`` si no hubo ni un intervalo válido
            (menos de dos muestras, o todas separadas por huecos).
        observed: Tiempo total cubierto por los intervalos que entraron en
            la media. Nunca incluye los huecos: es lo que permite a quien
            consume este resultado decir "esta media cubre 18 de las 24
            horas" en vez de presentar el número como si cubriera el
            periodo entero.
    """
    average_watts: Optional[float]
    observed: timedelta


class EnergyCost(NamedTuple):
    """Resultado de :func:`energy_and_cost`.

    ``kwh``/``cost`` son ``None`` (no ``0``) cuando no hay tiempo observado:
    un activo del que no se sabe nada no ha consumido cero euros, no se sabe
    cuánto ha consumido.
    """
    kwh: Optional[float]
    cost: Optional[float]


@dataclass(frozen=True)
class PeriodClassification:
    """Procedencia de una cifra de energía/coste sobre un periodo.

    Attributes:
        classification: ``"observed"`` (el periodo cabe en la retención y la
            cobertura de datos es alta), ``"observed_partial"`` (cabe pero
            con cobertura baja) o ``"projected"`` (el periodo excede la
            retención configurada).
        coverage_fraction: Fracción del periodo con datos observados
            (``observed / duración_del_periodo``), acotada a 1.0. ``None``
            si el periodo tiene duración cero.
    """
    classification: str
    coverage_fraction: Optional[float]


class StatSummary(NamedTuple):
    """Resultado de :func:`summarize_values`: los agregados de una serie de una métrica.

    Todos los campos de valor son ``None`` a la vez cuando la serie no tiene
    ninguna muestra con dato (``sample_count == 0``): de un activo que no ha
    reportado una métrica no se sabe su máximo, y ``0`` sería una cifra
    inventada.

    Attributes:
        minimum: Valor más bajo de la serie, o ``None`` sin muestras.
        maximum: Valor más alto de la serie, o ``None`` sin muestras.
        average: Media aritmética de las muestras, o ``None`` sin muestras.
        percentile_95: Percentil 95 por interpolación lineal (ver
            :func:`calculate_percentile`), o ``None`` sin muestras.
        current: Valor de la muestra más reciente, o ``None`` sin muestras.
        timestamp_of_minimum: Instante de la primera muestra (en orden
            cronológico) que alcanza ``minimum``, o ``None`` sin muestras.
        timestamp_of_maximum: Instante de la primera muestra (en orden
            cronológico) que alcanza ``maximum``, o ``None`` sin muestras.
        sample_count: Número de muestras con dato que entraron en el
            resumen; las que traían ``None`` no cuentan. Nunca es negativo.
    """
    minimum: Optional[float]
    maximum: Optional[float]
    average: Optional[float]
    percentile_95: Optional[float]
    current: Optional[float]
    timestamp_of_minimum: Optional[datetime]
    timestamp_of_maximum: Optional[datetime]
    sample_count: int


#: Resumen de una serie sin ninguna muestra con dato. Es un único valor
#: inmutable porque todos los resúmenes vacíos son idénticos.
_EMPTY_SUMMARY = StatSummary(
    minimum=None, maximum=None, average=None, percentile_95=None, current=None,
    timestamp_of_minimum=None, timestamp_of_maximum=None, sample_count=0,
)

#: Percentil que entra en :class:`StatSummary`. El 95 es el corte habitual en
#: monitorización: descarta los picos aislados sin esconder una carga
#: sostenida, que es justo lo que el máximo no distingue.
_SUMMARY_PERCENTILE = 95

AssetKey = TypeVar("AssetKey", bound=Hashable)


def median_delta(times: Sequence[datetime]) -> Optional[timedelta]:
    """
    Mediana de los intervalos entre instantes consecutivos ya ordenados.

    La mediana, no la media: un único apagón largo en medio de una serie
    regular no debe inflar el "intervalo típico" y perdonar huecos que en
    realidad sí lo son.

    Returns:
        La mediana, o ``None`` con menos de dos instantes.
    """
    if len(times) < 2:
        return None
    deltas = sorted(t2 - t1 for t1, t2 in zip(times, times[1:]))
    mid = len(deltas) // 2
    if len(deltas) % 2:
        return deltas[mid]
    return (deltas[mid - 1] + deltas[mid]) / 2


def _gap_threshold(times: Sequence[datetime]) -> timedelta:
    """Umbral de hueco derivado de la mediana de los intervalos observados.

    Se deriva de los datos, no del intervalo de heartbeat configurado: un
    activo puede estar reportando cada minuto legítimamente porque su
    configuración lo dice, y un umbral fijo lo penalizaría por eso.
    """
    delta = median_delta(times)
    if delta is None:
        return _GAP_FLOOR
    return max(delta * _GAP_MULTIPLIER, _GAP_FLOOR)


def weighted_average_with_observed_time(
    samples: Sequence[Tuple[datetime, float]],
) -> PowerAverage:
    """
    Potencia media ponderada por duración, sobre los tramos realmente
    observados de una serie de ``(instante, vatios)``.

    Un activo apagado doce horas y midiendo 200 W las otras doce no tiene
    una media de 100 W: tiene una media observada de 200 W durante el
    tiempo que hubo datos, y doce horas sin información. Meter los huecos en
    el promedio como si fueran ceros hunde la media en proporción al tiempo
    que la máquina estuvo apagada — cuanto menos se sabe, más bajo parecería
    el consumo, que es exactamente al revés de lo útil.

    Cada intervalo `[t_i, t_{i+1})` cuya separación no supere el umbral de
    hueco (derivado de la mediana de los intervalos de esta misma serie)
    aporta `v_i × Δt_i` a la suma ponderada; los intervalos que sí son un
    hueco se excluyen enteros, tanto del numerador como del tiempo
    observado. Se pondera por el valor de la muestra **inicial** del
    intervalo (la lectura se trata como constante hasta la siguiente, igual
    que el resto del módulo trata un heartbeat como el estado del activo
    hasta que llegue otro), no por su promedio con la siguiente.

    Args:
        samples: Pares ``(instante, vatios)``, en cualquier orden.

    Returns:
        Un :class:`PowerAverage`. Con menos de dos muestras, o si todas
        están separadas por huecos, ``average_watts`` es ``None`` y
        ``observed`` es cero — no hay ni un intervalo que promediar, y
        eso no es lo mismo que una media de 0 W.
    """
    if len(samples) < 2:
        return PowerAverage(average_watts=None, observed=timedelta(0))

    ordered = sorted(samples, key=lambda sample: sample[0])
    times = [instant for instant, _ in ordered]
    threshold = _gap_threshold(times)

    weighted_sum = 0.0
    observed = timedelta(0)
    for (t1, watts1), (t2, _watts2) in zip(ordered, ordered[1:]):
        delta = t2 - t1
        if delta <= threshold:
            weighted_sum += watts1 * delta.total_seconds()
            observed += delta

    if observed <= timedelta(0):
        return PowerAverage(average_watts=None, observed=timedelta(0))
    return PowerAverage(average_watts=weighted_sum / observed.total_seconds(), observed=observed)


def energy_and_cost(
    average_watts: Optional[float], observed: timedelta, price_per_kwh: float,
) -> EnergyCost:
    """
    Convierte una potencia media observada en energía (kWh) y coste.

    La energía se calcula sobre el **tiempo observado**, nunca sobre la
    duración nominal del periodo que se pidió: multiplicar la media
    observada por la duración completa del periodo imputaría consumo a las
    horas en que el activo no reportó (o estuvo apagado) — el mismo error
    contra el que ``weighted_average_with_observed_time`` ya se protege,
    reintroducido en el último paso si se ignorara ``observed``.

    Args:
        average_watts: Potencia media ponderada, o ``None`` sin datos.
        observed: Tiempo cubierto por esa media.
        price_per_kwh: Precio de la electricidad configurado.

    Returns:
        Un :class:`EnergyCost`. ``(None, None)`` si no hay ni un intervalo
        observado — un activo sin datos no ha consumido cero euros.
    """
    if average_watts is None or observed <= timedelta(0):
        return EnergyCost(kwh=None, cost=None)

    hours = observed.total_seconds() / 3600
    kwh = (average_watts / 1000) * hours
    return EnergyCost(kwh=kwh, cost=kwh * price_per_kwh)


def classify_period(
    period_start: datetime, period_end: datetime, observed: timedelta,
    retention_days: int, coverage_threshold: float = 0.9,
) -> PeriodClassification:
    """
    Clasifica una cifra de energía/coste según cuánto se puede confiar en ella.

    Contra ``retention_days`` de retención y sin tabla de rollup, un periodo
    que exceda esa ventana **nunca** puede ser histórico real: se etiqueta
    siempre como proyección, con independencia de la cobertura que tenga —
    el propio periodo pedido ya no cabe en lo que el servidor conserva.
    Dentro de la ventana, la cobertura decide entre observado (por encima
    del umbral) y observado con datos incompletos (por debajo): "últimas
    24 h" de un activo que estuvo apagado dieciocho es un dato sobre seis
    horas, y hay que decirlo en vez de presentarlo como si cubriera el día
    entero.

    Args:
        period_start: Inicio del periodo pedido.
        period_end: Fin del periodo pedido.
        observed: Tiempo observado dentro de ese periodo (de
            :attr:`PowerAverage.observed`).
        retention_days: Ventana de retención configurada
            (``features.hygeia.retentionDays``).
        coverage_threshold: Fracción de cobertura mínima para contar como
            observado sin matizar (por defecto 0.9, del orden del 90 % que
            describe el issue de origen).

    Returns:
        Un :class:`PeriodClassification`.
    """
    period_duration = period_end - period_start
    if period_duration > timedelta(days=retention_days):
        return PeriodClassification(classification="projected", coverage_fraction=None)

    if period_duration <= timedelta(0):
        return PeriodClassification(classification="observed_partial", coverage_fraction=None)

    coverage = min(1.0, observed.total_seconds() / period_duration.total_seconds())
    classification = "observed" if coverage >= coverage_threshold else "observed_partial"
    return PeriodClassification(classification=classification, coverage_fraction=coverage)


def summarize_power_period(
    samples: Sequence[Tuple[datetime, float]], period_start: datetime, period_end: datetime,
    price_per_kwh: float, retention_days: int,
) -> dict:
    """
    Combina media ponderada, energía/coste y clasificación para un periodo.

    Es el punto de entrada que consume el manager: junta los tres cálculos en
    una sola llamada por ventana (24 h, 7 d, 30 d...), para no repetir el
    mismo triplete de pasos por cada una.

    Returns:
        Diccionario con ``averageWatts``, ``kwh``, ``cost``,
        ``classification``, ``coverageFraction``, ``periodFrom`` y
        ``periodTo`` — la forma que espera ``PowerPeriodSchema``.
    """
    average = weighted_average_with_observed_time(samples)
    cost = energy_and_cost(average.average_watts, average.observed, price_per_kwh)
    period = classify_period(period_start, period_end, average.observed, retention_days)

    return {
        "averageWatts": average.average_watts,
        "kwh": cost.kwh,
        "cost": cost.cost,
        "classification": period.classification,
        "coverageFraction": period.coverage_fraction,
        "periodFrom": period_start,
        "periodTo": period_end,
    }


def project_month(
    samples: Sequence[Tuple[datetime, float]], period_start: datetime, period_end: datetime,
    price_per_kwh: float,
) -> dict:
    """
    Proyección mensual, extrapolando la media ponderada de una ventana corta.

    Se apoya en la misma ventana que ``week`` (7 días) en vez de en los 30
    días de ``month``: es la que sigue dando una cifra útil aunque el activo
    lleve poco tiempo reportando, y es lo bastante corta para reflejar el
    ritmo de consumo actual sin que un solo día atípico la desvíe del todo.

    Se marca siempre ``"projected"``, sin excepción: contra la ventana de
    retención configurada, un mes natural nunca es histórico real, así que
    no tiene sentido aplicarle ``classify_period`` — ahí siempre daría el
    mismo resultado por la vía larga.

    Args:
        samples: Muestras de la ventana de origen (la misma que ``week``).
        period_start: Inicio de esa ventana de origen, para que la respuesta
            documente sobre qué datos se extrapoló.
        period_end: Fin de esa ventana de origen.
        price_per_kwh: Precio de la electricidad configurado.

    Returns:
        Igual forma que :func:`summarize_power_period`. ``kwh``/``cost``
        están calculados sobre un mes nominal de 30 días, no sobre la
        duración de la ventana de origen; ``periodFrom``/``periodTo``
        documentan esa ventana de origen, no el mes proyectado.
    """
    average = weighted_average_with_observed_time(samples)
    nominal_month = timedelta(days=30)
    cost = energy_and_cost(average.average_watts, nominal_month, price_per_kwh)

    window_duration = period_end - period_start
    coverage = (
        min(1.0, average.observed.total_seconds() / window_duration.total_seconds())
        if window_duration > timedelta(0) else None
    )

    return {
        "averageWatts": average.average_watts,
        "kwh": cost.kwh,
        "cost": cost.cost,
        "classification": "projected",
        "coverageFraction": coverage,
        "periodFrom": period_start,
        "periodTo": period_end,
    }


def calculate_percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    """
    Percentil de una lista de valores por interpolación lineal entre rangos.

    Es el método por defecto de NumPy (``method="linear"``): se ordenan los
    valores, se sitúa el percentil en la posición ``percentile / 100 × (n - 1)``
    y, si cae entre dos valores, se interpola entre ellos. Se implementa aquí
    en vez de importar NumPy porque el proyecto no depende de él y esta es la
    única cuenta que lo necesitaría. El mismo cálculo sirve para el resumen de
    una serie y para el percentil dentro de un cubo de la serie temporal, que
    SQL no resuelve de forma portable entre Postgres y SQLite.

    Args:
        values: Valores sobre los que calcular el percentil, en cualquier
            orden. No admite ``None``: quien llama descarta antes las
            muestras sin dato.
        percentile: Percentil pedido, en el rango cerrado ``[0, 100]``.
            ``0`` devuelve el mínimo y ``100`` el máximo.

    Returns:
        Optional[float]: El percentil, o ``None`` si ``values`` está vacío.
            Con un solo valor, ese valor.

    Raises:
        ValueError: Si ``percentile`` está fuera de ``[0, 100]``; es un error
            de programación, no un dato de entrada del usuario.
    """
    if not 0 <= percentile <= 100:
        raise ValueError(f"El percentil debe estar en [0, 100]; se pidió {percentile}")
    if not values:
        return None

    ordered = sorted(values)
    position = percentile / 100 * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    lower_value = ordered[lower_index]
    return lower_value + (ordered[upper_index] - lower_value) * (position - lower_index)


def summarize_values(samples: Sequence[Tuple[datetime, Optional[float]]]) -> StatSummary:
    """
    Resume una serie de una métrica: mínimo, máximo, media, percentil 95 y valor actual.

    Es la cuenta común de todas las estadísticas de Hygeia: el resumen de un
    activo, el de cada activo de una etiqueta y el del parque aplican esta
    misma función a series distintas, para que ``avg`` o ``p95`` signifiquen
    lo mismo en todos los endpoints.

    Las muestras con valor ``None`` se descartan: una métrica que el agente no
    reportó en un heartbeat es ausencia de dato, no un cero, y contarla como
    cero hundiría el mínimo y la media.

    La media es **aritmética** sobre las muestras, no ponderada por duración.
    Así coincide con el ``AVG`` que la base de datos calcula al agregar la
    serie temporal por cubos, y un resumen y una gráfica del mismo tramo no dan
    dos medias distintas. Un hueco de telemetría tampoco cuenta como cero,
    porque en un hueco no hay muestras. La media ponderada por duración
    (:func:`weighted_average_with_observed_time`) se reserva para la energía,
    donde el tiempo entra en la propia definición de la magnitud.

    Args:
        samples: Pares ``(instante, valor)`` en cualquier orden. El instante
            es ``received_at`` (reloj del servidor), el mismo eje que el resto
            de la serie temporal.

    Returns:
        StatSummary: Los agregados de la serie. Con ninguna muestra con dato,
            todos los campos de valor son ``None`` y ``sample_count`` es
            ``0``. Si el máximo o el mínimo se repiten, su instante es el de la
            primera vez que se alcanzaron.
    """
    observed = sorted(
        ((instant, value) for instant, value in samples if value is not None),
        key=lambda sample: sample[0],
    )
    if not observed:
        return _EMPTY_SUMMARY

    values = [value for _, value in observed]
    # ``min``/``max`` devuelven el primer elemento extremo que encuentran, y
    # ``observed`` está en orden cronológico: el empate se resuelve a favor
    # del instante más antiguo sin más lógica.
    timestamp_of_minimum, minimum = min(observed, key=lambda sample: sample[1])
    timestamp_of_maximum, maximum = max(observed, key=lambda sample: sample[1])

    return StatSummary(
        minimum=minimum,
        maximum=maximum,
        average=math.fsum(values) / len(values),
        percentile_95=calculate_percentile(values, _SUMMARY_PERCENTILE),
        current=observed[-1][1],
        timestamp_of_minimum=timestamp_of_minimum,
        timestamp_of_maximum=timestamp_of_maximum,
        sample_count=len(values),
    )


def summarize_series_by_asset(
    series_by_asset: Mapping[AssetKey, Sequence[Tuple[datetime, Optional[float]]]],
) -> Dict[AssetKey, StatSummary]:
    """
    Aplica :func:`summarize_values` a varias series a la vez, una por activo.

    Es la forma que devuelve el repositorio en las consultas multi-activo
    (una serie por ``asset_id``), así que el resumen por etiqueta o del
    parque no tiene que recorrer el diccionario a mano en cada endpoint.

    Args:
        series_by_asset: Serie de ``(instante, valor)`` de cada activo,
            indexada por su clave (normalmente el ``asset_id``). Puede estar
            vacío.

    Returns:
        Dict[AssetKey, StatSummary]: El resumen de cada activo con la misma
            clave de entrada. Un activo con una serie vacía conserva su
            entrada, con el resumen vacío (``sample_count == 0``), para que
            quien llama pueda decir "sin datos" en vez de perderlo de la lista.
    """
    return {asset_key: summarize_values(series) for asset_key, series in series_by_asset.items()}


def build_percentile_series(
    samples_by_metric: Mapping[str, Sequence[Tuple[datetime, Optional[float]]]],
    bucket_seconds: int, percentile: float,
) -> List[Tuple[datetime, Dict[str, Optional[float]]]]:
    """
    Agrupa varias métricas en cubos de tiempo y calcula el percentil de cada una en cada cubo.

    Es el camino de la serie temporal con ``agg=p95``, que SQL no resuelve de
    forma portable entre Postgres y SQLite. Los cubos se numeran exactamente
    igual que en la base de datos (``floor(epoch / bucket_seconds)``, con el
    instante tratado como UTC), así que coinciden con los de las otras
    agregaciones y una gráfica puede alternar entre ellas sin que se muevan
    los puntos.

    Args:
        samples_by_metric: Muestras ``(instante, valor)`` de cada métrica,
            indexadas por su nombre público. Los instantes son naive-UTC; las
            muestras con ``None`` se descartan.
        bucket_seconds: Tamaño del cubo en segundos; positivo.
        percentile: Percentil a calcular, en ``[0, 100]``.

    Returns:
        List[Tuple[datetime, Dict[str, Optional[float]]]]: Un elemento por cubo
            con al menos una muestra, en orden cronológico: el inicio del cubo
            y el percentil de cada métrica de ``samples_by_metric``. Una
            métrica sin muestras en ese cubo vale ``None``, no ``0``. Los
            cubos sin ninguna muestra no aparecen, igual que en la serie de
            la base de datos.

    Raises:
        ValueError: Si ``bucket_seconds`` no es positivo o ``percentile`` está
            fuera de ``[0, 100]``.
    """
    if bucket_seconds <= 0:
        raise ValueError(f"El cubo debe ser positivo; se pidió {bucket_seconds} s")

    values_by_bucket: Dict[int, Dict[str, List[float]]] = {}
    for metric_name, samples in samples_by_metric.items():
        for instant, value in samples:
            if value is None:
                continue
            epoch_seconds = instant.replace(tzinfo=timezone.utc).timestamp()
            bucket_id = math.floor(epoch_seconds / bucket_seconds)
            values_by_bucket.setdefault(bucket_id, {}).setdefault(metric_name, []).append(value)

    series = []
    for bucket_id in sorted(values_by_bucket):
        bucket_start = datetime.fromtimestamp(bucket_id * bucket_seconds, tz=timezone.utc)
        values_by_metric = values_by_bucket[bucket_id]
        series.append((
            bucket_start.replace(tzinfo=None),
            {
                metric_name: calculate_percentile(values_by_metric.get(metric_name, []), percentile)
                for metric_name in samples_by_metric
            },
        ))
    return series


#: Formas de combinar entre activos las medias de cada uno.
_ASSET_COMBINATIONS = ("sum", "avg", "max")


def combine_asset_averages(
    averages: Sequence[Optional[float]], aggregation: str,
) -> Optional[float]:
    """
    Combina en una cifra las medias de varios activos sobre un periodo.

    Es el paso final de las estadísticas por etiqueta: cada activo aporta su
    media del periodo y aquí se combinan. Con ``sum`` sale el total típico de
    la etiqueta (el tráfico o la potencia de todos sus equipos a la vez), con
    ``avg`` el equipo medio y con ``max`` el equipo más cargado. ``max`` es la
    **media más alta**, no el pico absoluto: el pico de cada activo viaja
    aparte, en el desglose por activo.

    Los activos sin datos en el periodo (``None``) no entran en la cuenta: un
    equipo apagado no suma cero, simplemente no aporta.

    Args:
        averages: Media del periodo de cada activo, o ``None`` si no tuvo
            ninguna muestra.
        aggregation: ``"sum"``, ``"avg"`` o ``"max"``.

    Returns:
        Optional[float]: La cifra combinada, o ``None`` si ningún activo tuvo
            datos.

    Raises:
        ValueError: Si ``aggregation`` no es una de las tres admitidas; es un
            error de programación, porque el schema del endpoint ya la valida.
    """
    if aggregation not in _ASSET_COMBINATIONS:
        raise ValueError(
            f"Combinación {aggregation!r} no admitida; valores válidos: {list(_ASSET_COMBINATIONS)}"
        )
    values = [average for average in averages if average is not None]
    if not values:
        return None
    if aggregation == "sum":
        return math.fsum(values)
    if aggregation == "avg":
        return math.fsum(values) / len(values)
    return max(values)


@dataclass(frozen=True)
class StatsWindow:
    """Ventana temporal que cubre de verdad una consulta de estadísticas.

    Es lo que un endpoint de estadísticas devuelve junto a sus números para
    que el cliente sepa sobre qué periodo se calcularon, en vez de suponer
    que es el que pidió.

    Attributes:
        since: Inicio de la ventana (``received_at`` inclusivo), naive-UTC.
        until: Fin de la ventana (``received_at`` inclusivo), naive-UTC.
        requested_duration: Duración que pidió el cliente, antes de recortar.
        is_clipped: ``True`` si la ventana es más corta que la pedida, porque
            la petición superaba el límite de estadísticas o la retención.
    """
    since: datetime
    until: datetime
    requested_duration: timedelta
    is_clipped: bool

    @property
    def covered_duration(self) -> timedelta:
        """Duración real de la ventana, ya recortada."""
        return self.until - self.since


def resolve_stats_window(
    requested_duration: timedelta, now: datetime, max_stats_period_days: int, retention_days: int,
) -> StatsWindow:
    """
    Resuelve la ventana de una consulta de estadísticas, recortada a lo que se puede cubrir.

    Pedir un periodo mayor que lo disponible no es un error: se recorta al
    máximo y la ventana resultante lo dice (``is_clipped``). Un error
    obligaría al cliente a conocer la retención del despliegue para no
    equivocarse; un recorte silencioso haría pasar por "últimos 365 días" un
    cálculo sobre 30. El tope es el menor de dos valores: el límite de
    estadísticas (``HygeiaLimits.max_stats_period_days``) y la retención
    (``HygeiaConfig.retention_days``), porque más allá de la retención no
    quedan datos aunque el límite lo permita.

    Args:
        requested_duration: Duración pedida por el cliente (``24h``, ``7d``…
            ya convertido). Tiene que ser positiva.
        now: Instante de referencia, naive-UTC; es el fin de la ventana.
        max_stats_period_days: Límite configurado de estadísticas, en días.
        retention_days: Retención configurada de ``AssetSnapshot``, en días.

    Returns:
        StatsWindow: La ventana ``[now - duración cubierta, now]``, con
            ``is_clipped`` a ``True`` si la duración cubierta es menor que la
            pedida.

    Raises:
        ValueError: Si ``requested_duration`` no es positiva; es un error de
            programación, porque el schema del endpoint ya valida el periodo.
    """
    if requested_duration <= timedelta(0):
        raise ValueError(
            f"El periodo de estadísticas debe ser positivo; se pidió {requested_duration}"
        )

    ceiling = timedelta(days=min(max_stats_period_days, retention_days))
    covered_duration = min(requested_duration, ceiling)
    return StatsWindow(
        since=now - covered_duration,
        until=now,
        requested_duration=requested_duration,
        is_clipped=covered_duration < requested_duration,
    )
