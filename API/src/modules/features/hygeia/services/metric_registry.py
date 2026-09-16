"""
hygeia.services.metric_registry
────────────────────────────────
Registro cerrado de las métricas sobre las que se pueden pedir estadísticas.

Cada endpoint de estadísticas recibe el nombre público de una métrica
(``cpuPct``, en camelCase como el resto de la API) y necesita saber de dónde
sale su valor: de una columna desnormalizada de ``AssetSnapshot`` o, para el
detalle que solo vive en el JSONB ``metrics`` (disco por montaje, red por
interfaz), de un extractor que lo lea de ahí. Este registro es la única
traducción entre las dos cosas, para que ningún endpoint repita el mapeo con
sus propios matices.

Añadir una métrica es añadir una entrada, no un endpoint. Una métrica de
columna se declara con :func:`_build_column_metric`; una del JSONB es una
:class:`MetricDefinition` sin ``column`` y con su propio ``extractor``, y
todo lo que consume el registro la trata igual.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Sequence

from sqlalchemy.orm.attributes import InstrumentedAttribute

from ..exceptions import NonAdditiveMetricError, UnknownMetricError
from ..model import AssetSnapshot


class MetricUnit(StrEnum):
    """Unidad en la que se expresa una métrica, tal como viaja en la API.

    Es lo que permite a una respuesta decir "esto son porcentajes" en vez de
    dejar que quien la lee suponga bytes: la memoria, por ejemplo, solo se
    guarda en columna como porcentaje de uso.
    """
    PERCENT = "percent"
    LOAD_AVERAGE = "loadAverage"
    BYTES_PER_SECOND = "bytesPerSecond"
    WATTS = "watts"


@dataclass(frozen=True)
class MetricDefinition:
    """Una métrica consultable: su nombre público y cómo se obtiene su valor.

    Attributes:
        name: Nombre público de la métrica, en camelCase, el mismo que usa
            ``AssetSnapshot.to_dict`` y que llega en los parámetros de los
            endpoints (``cpuPct``, ``netRxBps``…).
        extractor: Función que obtiene el valor de la métrica de un snapshot
            ya cargado. Devuelve ``None`` cuando el snapshot no trae el dato,
            nunca ``0`` en su lugar.
        unit: Unidad de la métrica (``MetricUnit``).
        column: Columna de ``AssetSnapshot`` que guarda la métrica, para que el
            repositorio pueda agregarla en SQL (``MAX``, ``AVG``… por cubo o
            por activo) sin cargar filas. ``None`` en las métricas que solo
            viven en el JSONB ``metrics``, que se agregan en Python. Por
            defecto ``None``.
        is_additive: Si tiene sentido sumar la métrica entre activos. Lo
            tienen el tráfico de red y la potencia (el total de una etiqueta
            es la suma de sus equipos); no un porcentaje ni una carga media,
            cuya suma no mide nada. Por defecto ``False``, que es la opción
            prudente para una métrica nueva.
    """
    name: str
    extractor: Callable[[AssetSnapshot], Optional[float]]
    unit: MetricUnit
    column: Optional[InstrumentedAttribute] = None
    is_additive: bool = False

    @property
    def is_column_backed(self) -> bool:
        """Si la métrica tiene columna propia y, por tanto, se puede agregar en SQL."""
        return self.column is not None

    def extract_value(self, snapshot: AssetSnapshot) -> Optional[float]:
        """Obtiene el valor de la métrica de un snapshot.

        Args:
            snapshot: Heartbeat ya cargado del que leer la métrica.

        Returns:
            Optional[float]: El valor, o ``None`` si el snapshot no lo trae
                (agente sin esa fuente, o heartbeat anterior a que se
                instrumentara la métrica).
        """
        return self.extractor(snapshot)


def _build_column_metric(
    name: str, column: InstrumentedAttribute, unit: MetricUnit, is_additive: bool = False,
) -> MetricDefinition:
    """Declara una métrica que sale de una columna desnormalizada de ``AssetSnapshot``.

    El extractor devuelve ``float`` también para las columnas enteras
    (``net_rx_bps``/``net_tx_bps`` son ``BigInteger``), para que quien agrega
    reciba siempre el mismo tipo; ``None`` sigue siendo ``None``.

    Args:
        name: Nombre público en camelCase.
        column: Atributo de columna de ``AssetSnapshot`` (``AssetSnapshot.cpu_pct``).
        unit: Unidad de la métrica.
        is_additive: Si se puede sumar entre activos. Por defecto ``False``.

    Returns:
        MetricDefinition: La definición, con ``column`` rellena.
    """
    attribute_name = column.key

    def extract_column(snapshot: AssetSnapshot) -> Optional[float]:
        """Lee la columna del snapshot y la normaliza a ``float``."""
        value = getattr(snapshot, attribute_name)
        return None if value is None else float(value)

    return MetricDefinition(
        name=name, extractor=extract_column, unit=unit, column=column, is_additive=is_additive,
    )


#: Las métricas escalares que se desnormalizan a columna en la ingesta
#: (``services/aggregation.py::denormalize``). ``power_watts`` es nula cuando
#: el host no tiene fuente de potencia: su ausencia es "no disponible", no
#: cero, y el extractor la propaga como ``None`` igual que en las demás.
#: Solo lectura: es el catálogo cerrado de la API, no algo que se amplíe en
#: tiempo de ejecución.
METRIC_REGISTRY: Mapping[str, MetricDefinition] = MappingProxyType({
    definition.name: definition
    for definition in (
        _build_column_metric("cpuPct", AssetSnapshot.cpu_pct, MetricUnit.PERCENT),
        _build_column_metric("memPct", AssetSnapshot.mem_pct, MetricUnit.PERCENT),
        _build_column_metric("swapPct", AssetSnapshot.swap_pct, MetricUnit.PERCENT),
        _build_column_metric("load1", AssetSnapshot.load1, MetricUnit.LOAD_AVERAGE),
        _build_column_metric("diskMaxPct", AssetSnapshot.disk_max_pct, MetricUnit.PERCENT),
        _build_column_metric(
            "netRxBps", AssetSnapshot.net_rx_bps, MetricUnit.BYTES_PER_SECOND, is_additive=True,
        ),
        _build_column_metric(
            "netTxBps", AssetSnapshot.net_tx_bps, MetricUnit.BYTES_PER_SECOND, is_additive=True,
        ),
        _build_column_metric(
            "powerWatts", AssetSnapshot.power_watts, MetricUnit.WATTS, is_additive=True,
        ),
    )
})


def assert_metric_definition(name: str) -> MetricDefinition:
    """Obtiene la definición de una métrica que el cliente pidió por su nombre.

    Args:
        name: Nombre público de la métrica tal como llegó en la petición.

    Returns:
        MetricDefinition: La definición registrada con ese nombre.

    Raises:
        UnknownMetricError: Si el nombre no está en :data:`METRIC_REGISTRY`.
            Es un 400 con la lista de métricas válidas, no un
            ``AttributeError`` al buscar una columna que no existe.
    """
    definition = METRIC_REGISTRY.get(name)
    if definition is None:
        raise UnknownMetricError(name, sorted(METRIC_REGISTRY))
    return definition


def validate_metrics_are_additive(definitions: Sequence[MetricDefinition]) -> None:
    """Comprueba que todas las métricas pedidas se pueden sumar entre activos.

    Sumar el porcentaje de CPU de tres equipos da una cifra que no mide nada
    (¿un 180 %?), y presentarla como "total de la etiqueta" sería inventar un
    dato. Por eso ``agg=sum`` solo se admite en las métricas aditivas, y el
    error dice cuáles son para que quien llama no tenga que adivinarlo.

    Args:
        definitions: Métricas ya resueltas contra el registro.

    Raises:
        NonAdditiveMetricError: Con la primera métrica no aditiva de la lista.
    """
    additive_metric_names = sorted(
        name for name, candidate in METRIC_REGISTRY.items() if candidate.is_additive
    )
    for definition in definitions:
        if not definition.is_additive:
            raise NonAdditiveMetricError(definition.name, additive_metric_names)
