"""
Lógica de negocio del módulo Hygeia.

Sigue la convención del proyecto para el acceso a datos: las **lecturas**
usan ``build_repository(RepoCls)`` (sesión ambiental de la request, sin
demarcar transacción) y las **escrituras** van dentro de un ``UnitOfWork``.
El manager nunca crea ni cierra sesiones — de eso se encargan los bordes
(``teardown_request`` en HTTP, ``job_context``/``Scheduler.execute`` en
background).
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import NamedTuple, Optional, Sequence, Tuple

import src.modules.system.config_reading as CR
from src.modules.accounts import LimitKey, OrganizationManager, QuotaManager
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import assert_owned, utcnow_naive
from src.modules.system.taskqueue import job_context
from src.modules.system.taskqueue.dispatcher import OutboxDispatcher
from src.modules.system.taskqueue.outbox import TaskDispatch, build_dispatch
from src.modules.system.taskqueue.outbox_repository import TaskDispatchRepository
from src.modules.tools.herald import EmailMessage, build_mailer, render_email
from src.modules.users.model import User

from .exceptions import (
    AnomalyNotFoundError,
    AnomalyStillOpenError,
    AssetNotFoundError,
    AssetQuotaExceededError,
    IngestTooFrequentError,
    InventoryNotAvailableError,
    OrganizationScopeNotAllowedError,
    SystemTagImmutableError,
    TagAlreadyExistsError,
    TagNotFoundError,
    TagQuotaExceededError,
)
from .model import Anomaly, AssetSnapshot, HygeiaTag, MonitoredAsset, UserTag
from .repositories import (
    AnomalyRepository,
    AssetSnapshotRepository,
    HygeiaTagRepository,
    MonitoredAssetRepository,
)
from .services import (
    METRIC_REGISTRY, MetricDefinition, MetricUnit, assert_metric_definition,
    build_histogram, build_inventory_report, build_percentile_series, calculate_core_spread,
    check_clock_skew,
    combine_asset_averages, denormalize, evaluate, extract_entity_series, generate_agent_key,
    is_agent_outdated,
    project_month, resolve_stats_window, services_from_inventory, summarize_power_period,
    summarize_values, validate_metrics_are_additive,
)

# ---------------------------------------------------------------------------
# Dependencia de Hygeia sobre Themis: el análisis del inventario con Lybra.
#
# Es el ÚNICO import entre módulos de ``features/`` en todo el backend, y es
# deliberado: Hygeia sabe leer lo que hay instalado en un host, pero no sabe
# nada de CVEs; el motor de detección ya existe y vive en Themis. Consumirlo
# es infinitamente mejor que duplicarlo.
#
# La dependencia es UNIDIRECCIONAL y así debe seguir: Themis no importa nada
# de Hygeia ni sabe que existe (la columna ``LybraScan.asset_id`` es un
# entero sin ForeignKey, precisamente para no acoplar el esquema). Antes de
# tomar esto como precedente para un import en la otra dirección, o entre
# otro par de módulos, conviene tener una razón igual de fuerte.
# ---------------------------------------------------------------------------
from src.modules.features.themis.managers import LybraEngineManager

logger = logging.getLogger(__name__)


#: Valor de ``agg`` que la serie temporal calcula en Python y no en SQL.
_PERCENTILE_AGGREGATION = "p95"

#: Percentil que corresponde a ``_PERCENTILE_AGGREGATION``.
_SERIES_PERCENTILE = 95

#: Estados de presencia de un activo (``MonitoredAsset.status``). El panorama
#: del parque devuelve siempre los cuatro, a cero si no hay ninguno, para que
#: el cliente no tenga que distinguir "cero" de "no vino la clave".
_ASSET_STATUSES = ("pending", "online", "stale", "offline")

#: Severidades de una anomalía (``Anomaly.severity``), con el mismo criterio.
_ANOMALY_SEVERITIES = ("info", "warning", "critical")

#: Límites del histograma de una métrica en porcentaje. Fijos, y no los del
#: parque, para que la franja 75–100 % signifique lo mismo en cualquier
#: parque: con límites observados, un parque todo entre el 10 y el 20 %
#: pintaría su franja más alta como si fuera la de los equipos saturados.
_PERCENT_RANGE = (0.0, 100.0)

#: Procedencia de una cifra de energía (``classify_period``), de la más fiable
#: a la menos. El orden es el que decide la procedencia de un total.
_POWER_CLASSIFICATIONS = ("observed", "observed_partial", "projected")


def _combine_power_classifications(classifications: Sequence[str]) -> Optional[str]:
    """Procedencia de un total de energía: la peor de las de sus sumandos.

    Un total que mezcla un activo medido de principio a fin con otro que
    tuvo un hueco de horas no es "observado": solo es tan fiable como su
    parte menos fiable.

    Args:
        classifications: Procedencia de cada activo que aporta al total.

    Returns:
        Optional[str]: La menos fiable de ``_POWER_CLASSIFICATIONS``, o
            ``None`` si no hay ningún sumando.
    """
    if not classifications:
        return None
    return max(classifications, key=_POWER_CLASSIFICATIONS.index)


def _build_power_breakdown(
    assets: list, samples_by_asset: dict, estimated_asset_ids: set, window, config,
) -> list:
    """Energía de cada activo del agregado, de más a menos kWh.

    Cada activo se calcula con ``summarize_power_period``, igual que en su
    propio resumen de consumo, para que la cifra de un activo sea la misma
    en su ficha y en el agregado.

    Args:
        assets: Activos del agregado.
        samples_by_asset: ``{asset_id: [(instante, vatios), …]}`` de la
            ventana, tal como lo devuelve ``get_metric_samples_by_asset``.
        estimated_asset_ids: Activos con alguna lectura estimada en la ventana.
        window: ``StatsWindow`` de la consulta.
        config: ``HygeiaConfig`` vigente (precio de la electricidad y retención).

    Returns:
        list: Una entrada por activo con ``assetId``, ``hostname``,
            ``averageWatts``, ``kwh``, ``cost``, ``classification``,
            ``coverageFraction`` e ``isEstimated``; las de más kWh primero y
            las que no tienen datos al final.
    """
    breakdown = []
    for asset in assets:
        summary = summarize_power_period(
            samples_by_asset[asset.id], window.since, window.until,
            config.energy_price_per_kwh, config.retention_days,
        )
        breakdown.append({
            "assetId": asset.id,
            "hostname": asset.hostname,
            "averageWatts": summary["averageWatts"],
            "kwh": summary["kwh"],
            "cost": summary["cost"],
            "classification": summary["classification"],
            "coverageFraction": summary["coverageFraction"],
            "isEstimated": asset.id in estimated_asset_ids,
        })
    return sorted(breakdown, key=_sort_key_for_power_breakdown)


def _sort_key_for_power_breakdown(entry: dict) -> tuple:
    """Clave de orden del desglose de energía: más kWh primero, sin datos al final.

    Args:
        entry: Una entrada del desglose, con ``kwh`` y ``hostname``.

    Returns:
        tuple: ``(sin_datos, -kwh, hostname_en_minúsculas)``.
    """
    kwh = entry["kwh"]
    return (kwh is None, -(kwh or 0.0), entry["hostname"].lower())


def _assert_visible_tag(user_id: int, tag_id: int) -> HygeiaTag:
    """Obtiene una etiqueta que el usuario puede ver: una de sistema o una suya.

    La etiqueta personal de otro usuario da el mismo error que una
    inexistente, para no permitir enumerar el catálogo ajeno por diferencia
    de respuesta.

    Args:
        user_id: Usuario que pide la etiqueta.
        tag_id: Etiqueta pedida.

    Returns:
        HygeiaTag: La etiqueta.

    Raises:
        TagNotFoundError: Si no existe o es personal de otro usuario.
    """
    tag = build_repository(HygeiaTagRepository).get_by_id(tag_id)
    if tag is None or tag.user_id not in (None, user_id):
        raise TagNotFoundError(tag_id)
    return tag


def _resolve_series_assets(
    user_id: int, tag_id: Optional[int], asset_ids: Optional[Sequence[int]],
) -> Tuple[Optional[HygeiaTag], list]:
    """Activos de una serie multi-activo: los de una etiqueta o una lista explícita.

    Args:
        user_id: Dueño de los activos.
        tag_id: Etiqueta cuyos activos se quieren, o ``None``.
        asset_ids: Ids pedidos, o ``None``. Exactamente uno de los dos viene
            informado (lo valida el schema).

    Returns:
        Tuple[Optional[HygeiaTag], list]: La etiqueta (``None`` con una lista
            de ids) y los activos, ordenados por hostname.

    Raises:
        TagNotFoundError: Si la etiqueta no es visible para el usuario.
        AssetNotFoundError: Si algún id pedido no existe o es de otro usuario;
            lleva el menor de los que faltan, sin distinguir los dos casos.
    """
    asset_repo = build_repository(MonitoredAssetRepository)
    if tag_id is not None:
        return _assert_visible_tag(user_id, tag_id), asset_repo.get_by_tag(user_id, tag_id)

    assets = asset_repo.get_by_ids_for_user(user_id, list(asset_ids))
    missing_asset_ids = sorted(set(asset_ids) - {asset.id for asset in assets})
    if missing_asset_ids:
        raise AssetNotFoundError(missing_asset_ids[0])
    return None, assets


#: Horas del día que devuelve siempre el patrón horario, tenga muestras o no.
_HOURS_OF_DAY = range(24)


def _resolve_scope_assets(
    user_id: int, scope: str, tag_id: Optional[int], asset_id: Optional[int],
) -> Tuple[Optional[HygeiaTag], list]:
    """Activos sobre los que se calcula una estadística con ámbito declarado.

    Es la resolución común de ``scope``: un activo suyo, los de una etiqueta
    visible, o todo su parque. Devuelve siempre una lista de activos, aunque
    el ámbito sea uno solo, para que quien llama agregue igual en los tres
    casos.

    Args:
        user_id: Dueño de los activos.
        scope: ``"asset"``, ``"tag"`` o ``"fleet"``.
        tag_id: Etiqueta, obligatoria con ``scope="tag"`` y ``None`` en el
            resto (lo valida el schema).
        asset_id: Activo, obligatorio con ``scope="asset"`` y ``None`` en el
            resto (lo valida el schema).

    Returns:
        Tuple[Optional[HygeiaTag], list]: La etiqueta (``None`` fuera de
            ``scope="tag"``) y los activos del ámbito.

    Raises:
        TagNotFoundError: Con ``scope="tag"``, si la etiqueta no es visible
            para el usuario.
        AssetNotFoundError: Con ``scope="asset"``, si el activo no existe o
            pertenece a otro usuario.
    """
    asset_repo = build_repository(MonitoredAssetRepository)
    if scope == "asset":
        asset = assert_owned(
            MonitoredAssetRepository, asset_id, user_id, AssetNotFoundError,
        )
        return None, [asset]
    if scope == "tag":
        return _assert_visible_tag(user_id, tag_id), asset_repo.get_by_tag(user_id, tag_id)
    return None, asset_repo.get_by_user(user_id)


def _resolve_series_bucket(
    window, requested_bucket_seconds: Optional[int], max_points: int,
) -> Tuple[int, bool]:
    """Cubo de una serie multi-activo: el pedido, o el mínimo que cabe en ``maxSeriesPoints``.

    Un cubo tan fino que la ventana daría más puntos que el tope no se
    rechaza: se ensancha al mínimo que cabe y la respuesta lo dice, igual que
    un periodo mayor que la retención se recorta en vez de fallar. Sin cubo
    pedido se usa ese mínimo, que da la serie más detallada que cabe.

    Args:
        window: ``StatsWindow`` de la consulta.
        requested_bucket_seconds: Cubo pedido en segundos, o ``None``.
        max_points: Tope de puntos por serie (``maxSeriesPoints``).

    Returns:
        Tuple[int, bool]: El cubo que se usa y si se ensanchó respecto al
            pedido.
    """
    covered_seconds = (window.until - window.since).total_seconds()
    # El repositorio cuenta un cubo más que ventana / cubo (la ventana no tiene
    # por qué empezar alineada), de ahí el ``- 1``.
    minimum_bucket_seconds = max(1, math.ceil(covered_seconds / max(1, max_points - 1)))
    if requested_bucket_seconds is None:
        return minimum_bucket_seconds, False
    if requested_bucket_seconds < minimum_bucket_seconds:
        return minimum_bucket_seconds, True
    return requested_bucket_seconds, False


class _SeriesQuery(NamedTuple):
    """Lo que comparten todas las series de una misma respuesta.

    La serie principal y la de comparación se piden con los mismos valores,
    y eso es lo que garantiza que sus cubos coincidan instante a instante.

    Attributes:
        definition: Métrica del registro.
        bucket_seconds: Cubo en segundos.
        window: ``StatsWindow`` de la consulta.
        bucket_aggregation: Cómo se resume cada cubo dentro de un activo.
        aggregation: Cómo se combinan los activos, o ``None`` para una serie
            por activo.
        max_points: Tope de cubos por serie.
    """
    definition: MetricDefinition
    bucket_seconds: int
    window: object
    bucket_aggregation: str
    aggregation: Optional[str]
    max_points: int


def _build_series(
    snapshot_repo: AssetSnapshotRepository, series_query: _SeriesQuery,
    tag: Optional[HygeiaTag], assets: list, is_combined: bool,
) -> list:
    """Series de unos activos: una por activo, o una sola que los combina.

    Args:
        snapshot_repo: Repositorio de snapshots ya construido.
        series_query: Métrica, cubo, ventana y agregaciones de la respuesta.
        tag: Etiqueta de la que salen los activos, o ``None``.
        assets: Activos, en el orden en que se quieren las series.
        is_combined: ``True`` para una sola serie combinada con
            ``series_query.aggregation`` (que entonces no es ``None``).

    Returns:
        list: Las series, con la forma de ``MetricSeriesSchema``.
    """
    query_arguments = (
        [asset.id for asset in assets], series_query.definition.column,
        series_query.bucket_seconds, series_query.window.since, series_query.window.until,
    )
    if not is_combined:
        return _render_asset_series(assets, snapshot_repo.get_bucketed_metric_by_asset(
            *query_arguments, within_bucket=series_query.bucket_aggregation,
            max_buckets=series_query.max_points,
        ))
    return [_render_combined_series(tag, snapshot_repo.get_bucketed_metric_across_assets(
        *query_arguments, within_bucket=series_query.bucket_aggregation,
        across_assets=series_query.aggregation, max_buckets=series_query.max_points,
    ))]


def _build_comparison_series(
    user_id: int, snapshot_repo: AssetSnapshotRepository, series_query: _SeriesQuery,
    compare_to: Tuple[str, int],
) -> list:
    """La serie con la que se compara la principal, marcada como comparación.

    Un activo se compara con su propia serie; una etiqueta, con la
    combinación de sus activos, con el mismo ``agg`` que la serie principal
    (el schema lo exige en ese caso). Las dos se piden con el mismo
    ``series_query``, así que sus cubos coinciden.

    Args:
        user_id: Dueño de los activos.
        snapshot_repo: Repositorio de snapshots ya construido.
        series_query: Los mismos valores que la serie principal.
        compare_to: ``("asset", id)`` o ``("tag", id)``.

    Returns:
        list: Una serie, con ``isComparison`` a ``True``.

    Raises:
        TagNotFoundError: Si la etiqueta no es visible para el usuario.
        AssetNotFoundError: Si el activo no existe o no es suyo.
    """
    compare_kind, compare_id = compare_to
    if compare_kind == "tag":
        tag, assets = _resolve_series_assets(user_id, compare_id, None)
        comparison = _build_series(snapshot_repo, series_query, tag, assets, is_combined=True)
    else:
        _, assets = _resolve_series_assets(user_id, None, [compare_id])
        comparison = _build_series(snapshot_repo, series_query, None, assets, is_combined=False)
    return [{**entry, "isComparison": True} for entry in comparison]


def _render_asset_series(assets: list, series_by_asset: dict) -> list:
    """Una serie por activo, con su hostname como etiqueta.

    Args:
        assets: Activos de la consulta, en el orden en que se quieren.
        series_by_asset: ``{asset_id: [(inicio_del_cubo, valor), …]}``.

    Returns:
        list: Las series, con ``kind="asset"``.
    """
    return [
        {
            "kind": "asset",
            "assetId": asset.id,
            "tagId": None,
            "label": asset.hostname,
            "points": [{"at": at, "value": value} for at, value in series_by_asset[asset.id]],
        }
        for asset in assets
    ]


def _render_combined_series(tag: Optional[HygeiaTag], points: list) -> dict:
    """La serie que combina varios activos, con cuántos aportan a cada punto.

    Args:
        tag: Etiqueta de la que salen los activos, o ``None`` con una lista
            explícita de ids.
        points: ``[(inicio_del_cubo, valor, activos_con_dato), …]``.

    Returns:
        dict: La serie, con ``kind="tag"`` (y el nombre de la etiqueta como
            ``label``) o ``kind="assets"``.
    """
    return {
        "kind": "assets" if tag is None else "tag",
        "assetId": None,
        "tagId": None if tag is None else tag.id,
        "label": None if tag is None else tag.name,
        "points": [
            {"at": at, "value": value, "assetCount": asset_count}
            for at, value, asset_count in points
        ],
    }


def _resolve_histogram_range(
    definition: MetricDefinition, values: Sequence[float],
) -> Optional[Tuple[float, float]]:
    """Límites del histograma de una métrica: fijos para porcentajes, observados para el resto.

    Args:
        definition: Métrica del histograma.
        values: Valores por activo que se van a repartir.

    Returns:
        Optional[Tuple[float, float]]: ``(0, 100)`` para un porcentaje; el
            mínimo y el máximo observados para cualquier otra unidad (tráfico,
            potencia, carga), que no tiene un tope natural; ``None`` si no es
            un porcentaje y no hay ningún valor del que sacar el rango.
    """
    if definition.unit == MetricUnit.PERCENT:
        return _PERCENT_RANGE
    if not values:
        return None
    return (min(values), max(values))


def _build_percentile_series_points(
    snapshot_repo: AssetSnapshotRepository, asset_id: int, bucket_seconds: int,
    since: Optional[object], until: Optional[object],
) -> list:
    """Serie por cubos con el percentil 95 de cada métrica, en la forma de ``get_series_bucketed``.

    Lee las muestras de cada métrica del registro con su propia consulta de
    dos columnas y las agrupa en Python (``build_percentile_series``). Sin
    ``since``/``until`` explícitos, la ventana es la de retención: la consulta
    de muestras necesita límites, y más atrás no quedan datos.

    Args:
        snapshot_repo: Repositorio de snapshots ya construido.
        asset_id: Activo cuya serie se consulta; ya comprobado su dueño.
        bucket_seconds: Tamaño del cubo en segundos.
        since: Límite inferior opcional de ``receivedAt``.
        until: Límite superior opcional de ``receivedAt``.

    Returns:
        list: Puntos (diccionarios con las claves de ``AssetSnapshotPointSchema``)
            de más antiguo a más reciente, sin recortar.
    """
    now = utcnow_naive()
    retention = timedelta(days=CR.hygeia_config().retention_days)
    window_since = since if since is not None else now - retention
    window_until = until if until is not None else now
    samples_by_metric = {
        definition.name: snapshot_repo.get_metric_samples_by_asset(
            [asset_id], definition.column, window_since, window_until,
        )[asset_id]
        for definition in METRIC_REGISTRY.values()
    }
    return [
        {
            "collectedAt": bucket_start,
            "receivedAt": bucket_start,
            **values_by_metric,
            "diskMaxMount": None,
            "powerEstimated": None,
            "powerSource": None,
        }
        for bucket_start, values_by_metric in build_percentile_series(
            samples_by_metric, bucket_seconds, _SERIES_PERCENTILE,
        )
    ]


def _resolve_configured_stats_window(requested_duration: timedelta):
    """Ventana de una consulta de estadísticas con los límites de la configuración vigente.

    Todos los endpoints de estadísticas recortan el periodo igual: al menor
    entre ``maxStatsPeriodDays`` y ``retentionDays``. Tenerlo en un solo sitio
    evita que uno de ellos lea un límite distinto.

    Args:
        requested_duration: Duración pedida por el cliente, positiva.

    Returns:
        StatsWindow: La ventana que termina ahora, ya recortada.
    """
    return resolve_stats_window(
        requested_duration, utcnow_naive(),
        max_stats_period_days=CR.hygeia_limits().max_stats_period_days,
        retention_days=CR.hygeia_config().retention_days,
    )


def _resolve_entity_stats_window(requested_duration: timedelta):
    """Ventana de una estadística por entidad (montaje, interfaz, núcleo).

    Estas estadísticas leen el JSONB de cada heartbeat, así que se recortan a
    ``maxEntityStatsPeriodDays``, además de al límite general y a la
    retención.

    Args:
        requested_duration: Duración pedida por el cliente, positiva.

    Returns:
        StatsWindow: La ventana que termina ahora, ya recortada.
    """
    limits = CR.hygeia_limits()
    return resolve_stats_window(
        requested_duration, utcnow_naive(),
        max_stats_period_days=min(
            limits.max_entity_stats_period_days, limits.max_stats_period_days,
        ),
        retention_days=CR.hygeia_config().retention_days,
    )


def _rank_assets(entries: list, order: str, limit: int) -> list:
    """Ordena las entradas del ranking de activos y se queda con las ``limit`` primeras.

    Los empates se resuelven por hostname en los dos sentidos, para que el
    orden sea estable entre llamadas.

    Args:
        entries: Entradas con ``value`` (nunca ``None``: los activos sin
            datos ya se han apartado) y ``hostname``.
        order: ``"desc"`` (mayor valor primero) o ``"asc"``.
        limit: Cuántas entradas conservar; positivo.

    Returns:
        list: Las ``limit`` primeras entradas en el orden pedido.
    """
    sign = -1 if order == "desc" else 1
    ordered = sorted(entries, key=lambda entry: (sign * entry["value"], entry["hostname"].lower()))
    return ordered[:limit]


def _sort_key_for_breach_ranking(entry: dict) -> tuple:
    """Clave de orden del ranking de incumplimientos: más incumplimientos primero.

    A igualdad de incumplimientos en el periodo manda la racha viva
    (``currentBreachStreak``): entre dos activos que cruzaron su umbral las
    mismas veces, el que sigue cruzándolo ahora mismo es el que pide atención
    antes. El último desempate es el hostname, para que el orden sea estable
    entre llamadas.

    Args:
        entry: Una entrada del ranking, con ``breachCount``,
            ``currentBreachStreak`` y ``hostname``.

    Returns:
        tuple: ``(-incumplimientos, -racha, nombre_en_minúsculas)``.
    """
    return (
        -entry["breachCount"], -entry["currentBreachStreak"], entry["hostname"].lower(),
    )


def _total_breach_streak(breach_counters: Optional[dict]) -> int:
    """Suma la racha viva de cruces de umbral de un activo, sobre todas sus métricas.

    ``MonitoredAsset.breach_counters`` guarda, por regla (``cpu_spike``,
    ``disk_full:/var``…), cuántos latidos consecutivos lleva esa métrica por
    encima de su umbral. No es un histórico: el detector lo pone a cero en
    cuanto la métrica se recupera. Por eso sirve para decir "esto está
    cruzando el umbral ahora", y no para contar cuántas veces lo cruzó.

    Args:
        breach_counters: El mapa tal como está persistido, o ``None`` en un
            activo que todavía no ha sido evaluado nunca. Los valores que no
            sean enteros (una fila antigua manipulada a mano) se ignoran en
            vez de reventar la respuesta entera.

    Returns:
        int: La suma de las rachas de todas las métricas; ``0`` si no hay
            ninguna.
    """
    if not breach_counters:
        return 0
    return sum(
        streak for streak in breach_counters.values() if isinstance(streak, int)
    )


def _sort_key_for_tag_ranking(entry: dict) -> tuple:
    """Clave de orden del ranking de etiquetas: mayor valor primero, sin datos al final.

    Una etiqueta sin datos no está "a cero": no se sabe su valor, así que no
    compite con las que sí lo tienen y va detrás de todas. Los empates se
    resuelven por nombre, para que el orden sea estable entre llamadas.

    Args:
        entry: Una entrada del ranking, con ``value`` y ``tag``.

    Returns:
        tuple: ``(sin_valor, -valor, nombre_en_minúsculas)``.
    """
    value = entry["value"]
    return (value is None, -(value or 0.0), entry["tag"]["name"].lower())


def _render_tag_metric(
    definition: MetricDefinition, aggregates_by_asset: dict, hostnames_by_asset: dict,
    aggregation: str,
) -> dict:
    """Arma el bloque de una métrica en las estadísticas de una etiqueta.

    Args:
        definition: Métrica del registro que se está agregando.
        aggregates_by_asset: ``{asset_id: (media, máximo, muestras)}`` tal
            como lo devuelve ``get_metric_aggregates_by_asset``, en el orden
            de los activos de la etiqueta.
        hostnames_by_asset: ``{asset_id: hostname}`` de esos mismos activos.
        aggregation: ``"sum"``, ``"avg"`` o ``"max"``, cómo se combinan las
            medias de los activos.

    Returns:
        dict: ``unit``, ``value`` (la cifra combinada, o ``None`` si ningún
            activo tuvo datos), ``assetsWithData`` y ``assets`` (el desglose
            por activo, con su media, su máximo y su número de muestras).
    """
    assets = [
        {
            "assetId": asset_id,
            "hostname": hostnames_by_asset[asset_id],
            "average": average,
            "maximum": maximum,
            "sampleCount": sample_count,
        }
        for asset_id, (average, maximum, sample_count) in aggregates_by_asset.items()
    ]
    return {
        "unit": definition.unit,
        "value": combine_asset_averages([asset["average"] for asset in assets], aggregation),
        "assetsWithData": sum(1 for asset in assets if asset["sampleCount"]),
        "assets": assets,
    }


def _resolve_host_down_if_open(uow: UnitOfWork, asset_id: int) -> None:
    """Cierra una anomalía ``host_down`` abierta de este activo, si la había.

    Dos caminos la resuelven, y por eso vive aquí y no dentro de un manager:
    recibir un heartbeat **es** la condición de resolución para este tipo
    concreto de anomalía (no hace falta mirar las métricas del
    payload), y marcar el activo como no persistente también — silenciar un
    host mientras su aviso sigue sonando no silenciaría nada.
    """
    anomaly_repo = AnomalyRepository(uow)
    open_host_down = anomaly_repo.get_active(asset_id, "host_down")
    if open_host_down is not None:
        open_host_down.state = "resolved"
        open_host_down.resolved_at = utcnow_naive()
        anomaly_repo.update(open_host_down)


class HygeiaAssetManager:
    """
    Gestiona el alta, consulta, baja y credenciales de los activos
    monitorizados de un usuario.
    """

    def __init__(self, user: User) -> None:
        self.user = user

    @staticmethod
    def inventory_products(user_id: int) -> list[str]:
        """Nombres distintos del software instalado en los activos del usuario.

        Lectura pura, pensada para que Aegis sepa de qué productos habla la
        organización sin que nadie los teclee. Devuelve nombres tal como los
        reporta el agente ("Microsoft Edge", "IntelliJ IDEA 2025.2.2"); quien
        los consuma decide cómo resolverlos a coordenadas CPE.

        No exige que el agente esté vivo ahora mismo: ``inventory`` guarda el
        último escaneo completo y no caduca, así que un portátil apagado sigue
        contando. Lo contrario haría que una píldora generada de noche hablara
        de cosas distintas que la misma de día.
        """
        repo = build_repository(MonitoredAssetRepository)
        names: list[str] = []
        seen: set[str] = set()
        for asset in repo.get_by_user(user_id):
            for entry in (asset.inventory or []):
                name = (entry.get("name") or "").strip()
                key = name.lower()
                if name and key not in seen:
                    seen.add(key)
                    names.append(name)
        return names

    @staticmethod
    def has_inventory(user_id: int) -> bool:
        """Si el usuario tiene algún activo que haya reportado inventario.

        Es lo que decide si la UI de Aegis ofrece siquiera la opción de
        deducir los productos de los agentes.
        """
        repo = build_repository(MonitoredAssetRepository)
        return any(asset.inventory for asset in repo.get_by_user(user_id))

    def create_asset(
        self, hostname: str, os_name: Optional[str], labels: dict, is_persistent: bool = True,
    ) -> dict:
        """
        Da de alta un nuevo activo y emite su clave de agente.

        La clave completa (``keyId.secreto``) se genera aquí y se devuelve
        en claro en la respuesta; a partir de este momento es irrecuperable
        — solo persiste su hash Argon2id.

        Args:
            hostname: Nombre del host que reportará el agente.
            os_name: Sistema operativo del host, si se conoce de antemano.
            labels: Etiquetas libres del activo (entorno, rol, ubicación...).
            is_persistent: Si se espera que el host esté siempre encendido.
                ``False`` para un host que se apaga a propósito: su caída no
                abrirá anomalía ni disparará correo.

        Returns:
            Diccionario con ``asset`` (vista serializada del activo) y
            ``agentKey`` (la clave completa en claro, una única vez).

        Raises:
            QuotaExceededError: Si el plan del usuario no da para más activos
                (402). Es el tope comercial y es el que se agota en la práctica.
            AssetQuotaExceededError: Si se alcanza el techo absoluto de la
                instancia (``features.hygeia.limits.maxAssetsPerUser``, 409).
        """
        # Dos topes que parecen lo mismo y no lo son: el del plan es comercial y
        # lo edita el equipo sin desplegar; el de configuración es una defensa
        # del servidor, muy por encima de cualquier plan, y protege a un
        # despliegue on-premise de que alguien se dedique a dar de alta activos.
        QuotaManager().consume(self.user.id, LimitKey.HYGEIA_ASSETS)

        with UnitOfWork() as uow:
            repo = MonitoredAssetRepository(uow)

            max_assets = CR.hygeia_limits().max_assets_per_user
            if repo.count_by_user(self.user.id) >= max_assets:
                raise AssetQuotaExceededError(max_assets)

            key_id, secret_hash, full_key = generate_agent_key()
            asset = MonitoredAsset(
                hostname=hostname,
                os=os_name,
                labels=labels,
                agent_key_id=key_id,
                agent_key_hash=secret_hash,
                heartbeat_interval_sec=CR.hygeia_config().heartbeat_interval_sec,
                is_persistent=is_persistent,
                user_id=self.user.id,
            )
            saved = repo.save(asset)

        return {"asset": saved.to_dict(), "agentKey": full_key}

    def list_assets(self) -> list[dict]:
        """Devuelve todos los activos monitorizados del usuario, más recientes primero.

        Cada activo trae además ``totalFindings``: los hallazgos de su
        último análisis Lybra, o ``None`` si nunca se analizó. Lo pide el
        mundo de agentes de Themis para pintar el contador de cada tarjeta
        sin un request por activo (una query agrupada para todos); el
        detalle completo de Hygeia sigue viniendo de
        ``get_analysis_summary``.

        También trae ``agentOutdated``: si la versión de agente reportada
        está por debajo de ``features.hygeia.minAgentVersion``, calculado
        aquí (no en ``MonitoredAsset.to_dict()``, que es serialización pura
        sin acceso a configuración) para que la SPA pueda avisar en la
        lista sin comparar versiones por su cuenta. ``None`` cuando no se
        puede afirmar nada (el activo nunca ha reportado, o la versión no
        encaja en el formato esperado) — nunca se presenta como un "no hay
        problema" ni como un aviso falso.
        """
        repo = build_repository(MonitoredAssetRepository)
        assets = repo.get_by_user(self.user.id)
        counts = LybraEngineManager().latest_findings_by_asset(
            self.user.id, [asset.id for asset in assets],
        )
        min_agent_version = CR.hygeia_config().min_agent_version
        return [
            {
                **asset.to_dict(),
                "totalFindings": counts.get(asset.id),
                "agentOutdated": is_agent_outdated(asset.agent_version, min_agent_version),
            }
            for asset in assets
        ]

    def get_metrics(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, asset_id: int, since: Optional[object] = None, until: Optional[object] = None,
        bucket: Optional[int] = None, aggregation: str = "max",
    ) -> dict:
        """
        Devuelve la serie temporal de métricas de un activo del usuario, para
        el gráfico de la SPA.

        Solo se devuelven los escalares ya desnormalizados por punto — nunca
        el JSONB completo de cada snapshot, que multiplicaría el peso de la
        respuesta por cada punto de la serie sin aportar nada a un gráfico.
        Lo que tiene cardinalidad por entidad (disco por montaje, red por
        interfaz) o solo tiene sentido "ahora" (procesos, núcleos) se sirve
        por ``get_latest_metrics``.

        Con ``bucket`` (segundos) la serie viaja agregada — un punto por cubo
        con el agregado ``aggregation`` de cada métrica — para que ventanas
        largas no se recorten contra el tope de puntos: a 15 s de heartbeat,
        24 h son 5.760 puntos y 7 días 40.320, pero 288 y 336 cubos
        respectivamente. ``min``/``avg``/``max`` se resuelven en SQL
        (``get_series_bucketed``); ``p95`` se calcula en Python sobre las
        muestras de cada métrica, porque SQL no tiene un percentil portable
        entre Postgres y SQLite. Sin ``bucket``, el camino es el de siempre y
        ``aggregation`` no tiene efecto.

        Args:
            asset_id: Activo cuya serie se consulta.
            since: Límite inferior opcional de ``receivedAt``.
            until: Límite superior opcional de ``receivedAt``.
            bucket: Segundos del cubo de agregación; ``None`` para serie cruda.
            aggregation: Cómo se resume cada cubo: ``"min"``, ``"avg"``,
                ``"p95"`` o ``"max"``. Por defecto ``"max"``, el
                comportamiento de siempre (no se traga un pico).

        Returns:
            Diccionario con ``snapshots``, ``truncated``, ``bucket`` y ``agg``.
            ``bucket`` y ``agg`` ecoan el cubo y la agregación usados (los dos
            ``None`` en serie cruda) para que el consumidor rotule la ventana
            con honestidad. ``truncated`` avisa de que el histórico da para
            más puntos de los devueltos, para que la SPA no presente un
            recorte silencioso como si fuera la serie entera.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)

        limit = CR.hygeia_limits().max_series_points
        snapshot_repo = build_repository(AssetSnapshotRepository)
        if bucket and aggregation == _PERCENTILE_AGGREGATION:
            snapshots = _build_percentile_series_points(
                snapshot_repo, asset_id, bucket, since, until,
            )[:limit]
        elif bucket:
            snapshots = snapshot_repo.get_series_bucketed(
                asset_id, bucket, since=since, until=until, limit=limit, aggregation=aggregation,
            )
        else:
            raw = snapshot_repo.get_series(
                asset_id, since=since, until=until, limit=limit,
            )
            snapshots = [snapshot.to_dict() for snapshot in raw]

        return {
            "snapshots": snapshots,
            "truncated": len(snapshots) == limit,
            "bucket": bucket,
            "agg": aggregation if bucket else None,
        }

    def get_latest_metrics(self, asset_id: int) -> dict:
        """
        Devuelve el último heartbeat completo de un activo del usuario.

        A diferencia de la serie temporal, aquí sí viaja el JSONB íntegro:
        es un único punto, así que el desglose por punto de montaje, por
        interfaz de red, por núcleo y la lista de procesos caben sin
        penalizar la respuesta.

        Un activo dado de alta que aún no ha reportado devuelve los tres
        campos a ``None``. No es un 404: el activo existe y "todavía no ha
        latido" es un estado suyo legítimo (``status == "pending"``); un 404
        sería indistinguible del de un activo ajeno y haría que el sondeo de
        la SPA pintase un error cada pocos segundos sobre algo normal.

        Args:
            asset_id: Activo cuyas últimas métricas se consultan.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)

        snapshot_repo = build_repository(AssetSnapshotRepository)
        snapshot = snapshot_repo.get_latest(asset_id)
        if snapshot is None:
            return {"collectedAt": None, "receivedAt": None, "metrics": None}

        return {
            "collectedAt": snapshot.collected_at,
            "receivedAt":  snapshot.received_at,
            "metrics":     snapshot.metrics,
        }

    def get_power_summary(self, asset_id: int) -> dict:
        """
        Resume el consumo eléctrico de un activo del usuario.

        Devuelve la última lectura conocida más energía y coste de 24 h, 7 d
        y 30 d, cada una con su procedencia (observada, observada con
        cobertura parcial, o proyectada), más una proyección mensual
        extrapolada de la ventana de 7 días.

        Las tres ventanas reales (24 h, 7 d, 30 d) nunca exceden
        ``retention_days``: pedir más de lo que la retención guarda no
        añadiría histórico, solo lo etiquetaría igual que si lo tuviera. Con
        la retención por defecto (30 días), la ventana de 30 días coincide
        con el límite exacto de lo que se puede llamar observado.

        Returns:
            Diccionario con la forma de ``PowerSummaryResponseSchema``.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)

        snapshot_repo = build_repository(AssetSnapshotRepository)
        config = CR.hygeia_config()
        now = utcnow_naive()

        week_since, week_samples = self._power_window_samples(snapshot_repo, asset_id, now, 7, config)
        day_summary, _ = self._power_window(snapshot_repo, asset_id, now, 1, config)
        week_summary = self._summarize_window(week_since, now, week_samples, config)
        month_summary, _ = self._power_window(snapshot_repo, asset_id, now, 30, config)

        return {
            "current": self._current_power_reading(snapshot_repo.get_latest(asset_id)),
            "day": day_summary,
            "week": week_summary,
            "month": month_summary,
            "monthProjected": {
                **project_month(week_samples, week_since, now, config.energy_price_per_kwh),
                "currency": config.energy_price_currency,
            },
        }

    @staticmethod
    def _current_power_reading(latest: Optional[AssetSnapshot]) -> dict:
        """Última lectura de potencia conocida, o los tres campos a ``None`` sin heartbeats."""
        return {
            "watts": latest.power_watts if latest else None,
            "estimated": latest.power_estimated if latest else None,
            "source": latest.power_source if latest else None,
        }

    @staticmethod
    def _power_window_samples(
        snapshot_repo: AssetSnapshotRepository, asset_id: int, now, days: int, config,
    ) -> tuple:
        """Ventana ``[now - min(days, retención), now]`` y sus muestras de potencia."""
        since = now - timedelta(days=min(days, config.retention_days))
        return since, snapshot_repo.get_power_samples(asset_id, since, now)

    @staticmethod
    def _summarize_window(since, now, samples: list, config) -> dict:
        """Media ponderada, energía, coste y procedencia de una ventana ya resuelta."""
        summary = summarize_power_period(
            samples, since, now, config.energy_price_per_kwh, config.retention_days,
        )
        return {**summary, "currency": config.energy_price_currency}

    @classmethod
    def _power_window(
        cls, snapshot_repo: AssetSnapshotRepository, asset_id: int, now, days: int, config,
    ) -> tuple:
        """Resume una ventana completa de ``days`` días: consulta y cálculo de consumo."""
        since, samples = cls._power_window_samples(snapshot_repo, asset_id, now, days, config)
        return cls._summarize_window(since, now, samples, config), samples

    def get_stats_summary(
        self, asset_id: int, metric_names: Sequence[str], requested_duration: timedelta,
    ) -> dict:
        """
        Resume las métricas de un activo del usuario sobre un periodo.

        Para cada métrica pedida devuelve mínimo, máximo, media, percentil 95
        y valor actual, en una sola llamada en vez de una por métrica. La
        cuenta es la común de todas las estadísticas (``summarize_values``),
        así que ``avg`` o ``p95`` significan aquí lo mismo que en los
        agregados por etiqueta o del parque.

        El periodo se recorta a lo que se puede cubrir (``resolve_stats_window``:
        el menor entre el límite de estadísticas y la retención), y la
        respuesta dice qué ventana cubrió de verdad y si hubo recorte: un
        "máximo de los últimos 365 días" calculado sobre 30 tiene que decirlo.

        Cada métrica se lee con su propia consulta de dos columnas (instante
        y valor): son como mucho ocho, y cada una ya descarta en SQL los
        heartbeats sin dato para esa métrica.

        Args:
            asset_id: Activo cuyas métricas se resumen.
            metric_names: Nombres públicos de las métricas (``cpuPct``…). Los
                repetidos se resumen una sola vez; una lista vacía equivale a
                todas las métricas del registro. La respuesta los indexa por
                nombre, sin garantizar orden: el JSON sale con las claves
                ordenadas alfabéticamente.
            requested_duration: Duración del periodo pedido, antes de recortar;
                positiva (la valida el schema de la query).

        Returns:
            Diccionario con la forma de ``AssetStatsSummaryResponseSchema``:
            ``metrics`` (un ``StatSummary`` por nombre de métrica),
            ``periodCoveredFrom``/``periodCoveredTo`` e ``isPeriodClipped``.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
            UnknownMetricError: Si algún nombre no está en el registro de métricas.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)
        definitions = [
            assert_metric_definition(name)
            for name in dict.fromkeys(metric_names or METRIC_REGISTRY)
        ]
        window = _resolve_configured_stats_window(requested_duration)

        snapshot_repo = build_repository(AssetSnapshotRepository)
        summaries_by_metric = {}
        for definition in definitions:
            samples_by_asset = snapshot_repo.get_metric_samples_by_asset(
                [asset_id], definition.column, window.since, window.until,
            )
            summaries_by_metric[definition.name] = summarize_values(samples_by_asset[asset_id])

        return {
            "metrics": summaries_by_metric,
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_disk_stats(
        self, asset_id: int, mount: Optional[str], requested_duration: timedelta,
    ) -> dict:
        """
        Resume el uso de cada punto de montaje de un activo sobre un periodo.

        ``diskMaxPct`` solo guarda el montaje más lleno de cada heartbeat, así
        que un ``/var`` que se llena mientras ``/`` sigue ligero no se ve en
        su serie. Aquí se lee el detalle por montaje del JSONB y se resume
        cada uno con la misma cuenta que el resto de las estadísticas
        (``summarize_values``).

        Args:
            asset_id: Activo cuyos montajes se resumen.
            mount: Punto de montaje concreto (``/var``), o ``None`` para todos.
                Un montaje que el activo no reportó en el periodo da una lista
                vacía, no un error.
            requested_duration: Duración del periodo pedido, antes de recortar;
                positiva.

        Returns:
            Diccionario con la forma de ``DiskStatsResponseSchema``: ``mounts``
            (``mount`` y el ``StatSummary`` de ``usagePct``, por nombre de
            montaje) y la ventana cubierta.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)
        window = _resolve_entity_stats_window(requested_duration)

        samples = build_repository(AssetSnapshotRepository).get_metrics_section_samples(
            asset_id, "disk", window.since, window.until,
        )
        usage_by_mount = extract_entity_series(samples, "mount", "usagePct")
        return {
            "mounts": [
                {"mount": name, "usagePct": summarize_values(series)}
                for name, series in sorted(usage_by_mount.items())
                if mount is None or name == mount
            ],
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_network_stats(
        self, asset_id: int, interface: Optional[str], requested_duration: timedelta,
    ) -> dict:
        """
        Resume el tráfico de cada interfaz de red de un activo sobre un periodo.

        ``netRxBps``/``netTxBps`` son el total del activo; qué interfaz genera
        ese tráfico solo vive en el JSONB. Aquí se lee ese detalle y se resumen
        la recepción y el envío de cada interfaz con ``summarize_values``. Las
        interfaces loopback se excluyen, con el mismo criterio que el total.

        Args:
            asset_id: Activo cuyas interfaces se resumen.
            interface: Interfaz concreta (``eth0``), o ``None`` para todas. Una
                interfaz que el activo no reportó en el periodo, o una
                loopback, da una lista vacía, no un error.
            requested_duration: Duración del periodo pedido, antes de recortar;
                positiva.

        Returns:
            Diccionario con la forma de ``NetworkStatsResponseSchema``:
            ``interfaces`` (``interface`` y los ``StatSummary`` de
            ``rxBytesPerSec`` y ``txBytesPerSec``, por nombre de interfaz) y la
            ventana cubierta.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)
        window = _resolve_entity_stats_window(requested_duration)

        samples = build_repository(AssetSnapshotRepository).get_metrics_section_samples(
            asset_id, "network", window.since, window.until,
        )
        received_by_interface = extract_entity_series(
            samples, "iface", "rxBytesPerSec", is_loopback_excluded=True,
        )
        sent_by_interface = extract_entity_series(
            samples, "iface", "txBytesPerSec", is_loopback_excluded=True,
        )
        return {
            "interfaces": [
                {
                    "interface": name,
                    "rxBytesPerSec": summarize_values(received_by_interface.get(name, [])),
                    "txBytesPerSec": summarize_values(sent_by_interface.get(name, [])),
                }
                for name in sorted(received_by_interface.keys() | sent_by_interface.keys())
                if interface is None or name == interface
            ],
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_cpu_core_stats(self, asset_id: int, requested_duration: timedelta) -> dict:
        """
        Resume el desequilibrio de carga entre los núcleos de CPU de un activo.

        ``cpuPct`` es la media de los núcleos, y un proceso que satura uno solo
        queda escondido tras una media moderada. Aquí se calcula, en cada
        heartbeat, la distancia entre el núcleo más cargado y el menos cargado
        (``calculate_core_spread``), y se resume esa serie con
        ``summarize_values``: su máximo dice cuánto llegó a desequilibrarse la
        máquina en el periodo, y ``timestampOfMax`` cuándo. Junto al resumen va
        el uso por núcleo del último heartbeat del periodo que lo trae.

        Args:
            asset_id: Activo cuyos núcleos se analizan.
            requested_duration: Duración del periodo pedido, antes de recortar;
                positiva.

        Returns:
            Diccionario con la forma de ``CpuCoreStatsResponseSchema``:
            ``coreSpreadPct`` (un ``StatSummary``, vacío si ningún heartbeat
            trae dos núcleos o más), ``latestPerCorePct`` (lista vacía y
            ``latestAt`` a ``None`` si ningún heartbeat trae el uso por núcleo)
            y la ventana cubierta.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)
        window = _resolve_entity_stats_window(requested_duration)

        samples = build_repository(AssetSnapshotRepository).get_metrics_section_samples(
            asset_id, "cpu", window.since, window.until,
        )
        latest_at, latest_cores = next(
            (
                (instant, cpu["perCorePct"]) for instant, cpu in reversed(samples)
                if cpu and cpu.get("perCorePct")
            ),
            (None, []),
        )
        return {
            "coreSpreadPct": summarize_values(
                [(instant, calculate_core_spread(cpu)) for instant, cpu in samples],
            ),
            "latestPerCorePct": latest_cores,
            "latestAt": latest_at,
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_inventory(self, asset_id: int) -> dict:
        """
        Devuelve el último inventario de software conocido de un activo del usuario.

        No hay histórico (§ contrato de ingesta v1.0): lo que se guarda es
        siempre el resultado íntegro del último escaneo, así que no hay nada
        que paginar ni filtrar por rango temporal aquí.

        Un activo que nunca ha mandado un escaneo de inventario (agente
        antiguo, o el primero aún no le llegó) devuelve ``collectedAt: null``
        y ``software: []`` — no es un error, igual que ``get_latest_metrics``
        con un activo que aún no ha reportado.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        asset = assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)
        return {
            "collectedAt": asset.inventory_collected_at,
            "software": asset.inventory or [],
        }

    def get_asset(self, asset_id: int) -> dict:
        """
        Devuelve el detalle de un activo del usuario.

        Returns:
            Diccionario con la vista serializada del activo en forma
            de diccionario.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro
                usuario (misma excepción en ambos casos, para no permitir
                enumerar activos ajenos por diferencia de respuesta).
        """
        asset = assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)
        return asset.to_dict()

    def analyze_inventory(self, asset_id: int) -> dict:
        """
        Lanza un análisis de vulnerabilidades de Lybra sobre el inventario del activo.

        Es un "escaneo autenticado" sin escaneo ni
        autenticación remota: el agente ya vive dentro del host y ya reportó
        qué hay instalado, así que basta con traducir ese listado a la forma
        que el motor consume y encolarlo. **No se manda ni un paquete al
        activo** — el modo payload de Lybra tiene desactivados por
        contrato el fingerprinting y las comprobaciones activas.

        Cada llamada crea un escaneo nuevo; los anteriores se conservan. Eso
        es lo que permite al motor marcar como ``fixed`` un hallazgo que ya no
        aparece (correlación de ciclo de vida), algo que se perdería
        si cada re-análisis borrase al anterior.

        Returns:
            Diccionario con ``scanId`` del escaneo encolado.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
            InventoryNotAvailableError: Si el activo aún no ha reportado
                inventario, o si ninguno de sus paquetes trae versión (sin
                versión no hay CPE que resolver, así que el análisis no
                produciría ni una sola detección).
        """
        asset = assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)

        services = services_from_inventory(asset.inventory or [])
        if not services:
            raise InventoryNotAvailableError(asset_id)

        scan_id = LybraEngineManager().run_scan(
            user_id=self.user.id,
            target=asset.hostname,
            services=services,
            asset_id=asset.id,
        )
        logger.info(
            f"Análisis de inventario lanzado: escaneo Lybra {scan_id} "
            f"para el activo {asset_id} ('{asset.hostname}', {len(services)} paquetes)"
        )
        return {"scanId": scan_id}

    def get_analysis_summary(self, asset_id: int) -> dict:
        """
        Resume el último análisis de inventario del activo, si lo hay.

        Solo el recuento por prioridad, no la lista de hallazgos: el desglose
        completo se consulta en Themis (que ya tiene la interfaz para ello),
        y traerlo aquí duplicaría ese componente por un panel que solo quiere
        responder "¿cómo de mal está este activo?".

        Returns:
            El resumen, o ``{"scanId": None}`` si el activo nunca se analizó
            — no es un error, es el estado inicial de todo activo.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)

        manager = LybraEngineManager()
        scans, _total = manager.get_scans_paginated(
            self.user.id, page=1, per_page=1, asset_id=asset_id,
        )
        if not scans:
            return {"scanId": None}

        scan = scans[0]

        # Los recuentos llegan hechos desde el listado de Themis. Antes se
        # derivaban aquí recorriendo la lista completa de hallazgos, que era
        # una de las razones por las que ese listado tenía que mandarla entera;
        # `unresolvedPackages` (`Finding.cpe_resolved`)
        # sigue siendo el número real de paquetes que no se pudieron
        # identificar, no una advertencia genérica de "puede que alguno".
        return {
            "scanId":          scan["id"],
            "status":          scan.get("status"),
            "startedAt":       scan.get("startedAt"),
            "finishedAt":      scan.get("finishedAt"),
            "totalFindings":   scan.get("totalFindings", 0),
            "byPriority":      scan.get("byPriority", {}),
            "confirmedCount":  scan.get("confirmedFindings", 0),
            "vulnerableCount": scan.get("vulnerableFindings", 0),
            "packageCount":    scan.get("installedPackages", 0),
            "unresolvedCount": scan.get("unresolvedPackages", 0),
        }

    def delete_asset(self, asset_id: int) -> None:
        """
        Da de baja un activo, revocando su clave de agente.

        Al eliminar la fila se revoca implícitamente la clave: cualquier
        heartbeat posterior con esa clave falla la búsqueda por ``keyId``
        en ``require_agent_key`` con el mismo 401 genérico que una clave
        nunca emitida.

        Borra además los escaneos Lybra que el inventario de este activo
        originó. Va explícito aquí y no como cascada de base de
        datos porque ``LybraScan.asset_id`` es una referencia blanda sin
        ForeignKey, para no acoplar el esquema de Themis al de Hygeia. Se
        hace *antes* de borrar el activo: si fallara, el activo sigue en pie
        y la operación se puede reintentar, en vez de dejar escaneos
        huérfanos apuntando a un id que ya no existe.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        assert_owned(MonitoredAssetRepository, asset_id, self.user.id, AssetNotFoundError)

        LybraEngineManager().delete_scans_for_asset(asset_id)

        with UnitOfWork() as uow:
            asset = assert_owned(
                MonitoredAssetRepository, asset_id, self.user.id,
                AssetNotFoundError, uow=uow,
            )
            MonitoredAssetRepository(uow).delete(asset)

    def set_persistence(self, asset_id: int, is_persistent: bool) -> dict:
        """
        Cambia la expectativa de encendido de un activo.

        Al marcarlo como no persistente se resuelve además su ``host_down``
        abierto, si lo hay: quien silencia un host caído está silenciando ese
        aviso concreto, no solo los futuros.

        Args:
            asset_id: Activo a modificar.
            is_persistent: ``True`` si el host debería estar siempre
                encendido; ``False`` si se apaga a propósito.

        Returns:
            La vista serializada del activo ya actualizado.

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        with UnitOfWork() as uow:
            asset = assert_owned(
                MonitoredAssetRepository, asset_id, self.user.id,
                AssetNotFoundError, uow=uow,
            )

            asset.is_persistent = is_persistent
            if not is_persistent:
                _resolve_host_down_if_open(uow, asset.id)
            MonitoredAssetRepository(uow).update(asset)

            # Serializado dentro del bloque: fuera, la instancia queda detached.
            return asset.to_dict()

    def rotate_key(self, asset_id: int) -> dict:
        """
        Regenera la clave de agente de un activo, invalidando la anterior.

        Args:
            asset_id: Activo cuya clave se rota.

        Returns:
            Diccionario con ``agentKey`` (la nueva clave completa en claro,
            una única vez).

        Raises:
            AssetNotFoundError: Si el activo no existe o pertenece a otro usuario.
        """
        with UnitOfWork() as uow:
            asset = assert_owned(
                MonitoredAssetRepository, asset_id, self.user.id,
                AssetNotFoundError, uow=uow,
            )

            key_id, secret_hash, full_key = generate_agent_key()
            asset.agent_key_id = key_id
            asset.agent_key_hash = secret_hash
            MonitoredAssetRepository(uow).update(asset)

        return {"agentKey": full_key}


#: Tope de etiquetas personales por usuario.
#:
#: Es una constante de módulo y no un valor de ``SecOpsConfig.json`` a
#: propósito: nadie va a querer ajustar este número, y llevarlo a la
#: configuración obligaría a tocar ``config_reading.py``, el JSON, la vista de
#: configuración de la SPA y ``test_config_shape.py`` para algo que solo existe
#: para que la tabla no crezca sin fondo si alguien automatiza el alta.
MAX_TAGS_PER_USER = 50


class HygeiaTagManager:
    """
    Gestiona el catálogo de etiquetas de un usuario y su asignación a activos.

    Un usuario ve dos cosas como si fueran una: el catálogo común
    (``SystemTag``, sembrado por migración) y su repositorio personal
    (``UserTag``). Puede asignar cualquiera de las dos a sus activos, pero
    solo crear y borrar las suyas.
    """

    def __init__(self, user: User) -> None:
        self.user = user

    def list_tags(self) -> list[dict]:
        """
        Devuelve el catálogo visible con la actividad de cada etiqueta.

        Para cada etiqueta, cuántos activos del usuario la llevan y cuándo
        dio señal el último de ellos: es el listado del que tira un selector
        de etiqueta, que así puede avisar de una etiqueta cuyos equipos llevan
        días sin reportar sin tener que pedir todos los activos.

        Returns:
            Lista de diccionarios ``{id, name, color, tagType, assetCount,
            lastActivityAt}``, las de sistema primero y por nombre dentro de
            cada grupo. Una etiqueta sin activos del usuario sale con
            ``assetCount`` 0 y ``lastActivityAt`` ``None``, no desaparece.
        """
        tag_repository = build_repository(HygeiaTagRepository)
        activity_by_tag = tag_repository.get_asset_activity_per_tag(self.user.id)

        tags = []
        for tag in tag_repository.get_visible_for_user(self.user.id):
            asset_count, last_activity_at = activity_by_tag.get(tag.id, (0, None))
            tags.append({
                **tag.to_dict(), "assetCount": asset_count, "lastActivityAt": last_activity_at,
            })
        return tags

    def create_tag(self, name: str, color: str) -> dict:
        """
        Crea una etiqueta personal.

        El nombre se normaliza (espacios de sobra colapsados y recortados)
        antes de comprobar duplicados: «  Base   de datos » y «Base de datos»
        son la misma etiqueta escrita con menos cuidado, no dos.

        Args:
            name: Texto de la etiqueta.
            color: Nombre del color, ya validado contra ``TAG_COLORS`` por el schema.

        Returns:
            La vista serializada de la etiqueta creada, con ``assetCount`` a 0.

        Raises:
            TagAlreadyExistsError: Si ya existe una con ese nombre (sin
                distinguir mayúsculas), sea del catálogo común o suya.
            TagQuotaExceededError: Si ya tiene ``MAX_TAGS_PER_USER`` etiquetas.
        """
        normalized_name = " ".join(name.split())

        with UnitOfWork() as uow:
            tag_repository = HygeiaTagRepository(uow)

            if tag_repository.count_user_tags(self.user.id) >= MAX_TAGS_PER_USER:
                raise TagQuotaExceededError(MAX_TAGS_PER_USER)
            if tag_repository.get_by_name_for_user(self.user.id, normalized_name) is not None:
                raise TagAlreadyExistsError(normalized_name)

            tag = UserTag(name=normalized_name, color=color, user_id=self.user.id)
            tag_repository.save(tag)

            # Serializado dentro del bloque: fuera, la instancia queda detached.
            return {**tag.to_dict(), "assetCount": 0, "lastActivityAt": None}

    def delete_tag(self, tag_id: int) -> None:
        """
        Borra una etiqueta personal del usuario.

        Se lleva por delante sus asociaciones con los activos —esa es la
        operación—, pero **ningún activo**: quitar la etiqueta «Producción»
        del catálogo no borra los servidores de producción. De la limpieza se
        encargan el ORM (que vacía la tabla de asociación al borrar el padre)
        y el ``ondelete="CASCADE"`` de ``AssetTag``.

        Args:
            tag_id: Etiqueta a borrar.

        Raises:
            TagNotFoundError: Si no existe o es de otro usuario.
            SystemTagImmutableError: Si es del catálogo común.
        """
        with UnitOfWork() as uow:
            tag_repository = HygeiaTagRepository(uow)
            tag = tag_repository.get_by_id(tag_id)

            # Una etiqueta de sistema sí existe y sí se ve, así que decir "no
            # existe" sería mentir; una de otro usuario, en cambio, no debe
            # distinguirse de una inexistente.
            if tag is not None and tag.user_id is None:
                raise SystemTagImmutableError(tag_id)
            if tag is None or tag.user_id != self.user.id:
                raise TagNotFoundError(tag_id)

            tag_repository.delete(tag)

    def set_asset_tags(self, asset_id: int, tag_ids: list[int]) -> dict:
        """
        Reemplaza el conjunto de etiquetas de un activo.

        Es un reemplazo y no un añadido: llega la lista definitiva, y lo que
        no aparezca se quita. Así poner y quitar son la misma operación y el
        cliente no tiene que calcular diferencias ni encadenar llamadas.

        Args:
            asset_id: Activo a etiquetar.
            tag_ids: Ids de las etiquetas que debe llevar al terminar.

        Returns:
            La vista serializada del activo ya actualizado.

        Raises:
            AssetNotFoundError: Si el activo no existe o es de otro usuario.
            TagNotFoundError: Si alguna etiqueta no existe o no es visible
                para el usuario.
        """
        requested_ids = set(tag_ids)

        with UnitOfWork() as uow:
            asset = assert_owned(
                MonitoredAssetRepository, asset_id, self.user.id,
                AssetNotFoundError, uow=uow,
            )

            # Se resuelven contra las visibles, no por id suelto: así una
            # etiqueta personal ajena da el mismo 404 que una inexistente y no
            # se puede colar en un activo propio.
            visible = {
                tag.id: tag
                for tag in HygeiaTagRepository(uow).get_visible_for_user(self.user.id)
            }
            unknown_ids = requested_ids - visible.keys()
            if unknown_ids:
                raise TagNotFoundError(min(unknown_ids))

            asset.tags = [visible[tag_id] for tag_id in requested_ids]
            MonitoredAssetRepository(uow).update(asset)

            return asset.to_dict()


class HygeiaStatsManager:
    """
    Estadísticas que cruzan varios activos del usuario.

    El resumen de un único activo vive en ``HygeiaAssetManager.get_stats_summary``;
    aquí la unidad es un conjunto de activos: los de una etiqueta, o los de
    cada etiqueta del usuario para compararlas entre sí. Todo lo que
    se agrega son activos **del usuario**: una etiqueta de sistema la comparte
    todo el mundo, y contar los activos ajenos que la llevan filtraría el
    parque de otros usuarios.
    """

    def __init__(self, user: User) -> None:
        self.user = user

    def get_tag_stats(
        self, tag_id: int, metric_names: Sequence[str], aggregation: str,
        requested_duration: timedelta,
    ) -> dict:
        """
        Agrega las métricas de los activos del usuario que llevan una etiqueta.

        Cada activo aporta su media del periodo (calculada en SQL, una
        consulta por métrica para todos los activos) y las medias se combinan
        con ``aggregation``: ``sum`` para el total de la etiqueta, ``avg``
        para el equipo medio, ``max`` para el más cargado. La respuesta trae
        además el desglose por activo, con su media y su pico.

        Args:
            tag_id: Etiqueta a agregar; tiene que ser visible para el usuario
                (de sistema o suya).
            metric_names: Nombres públicos de las métricas; una lista vacía
                equivale a todas las del registro.
            aggregation: ``"sum"``, ``"avg"`` o ``"max"``. ``sum`` solo se
                admite en métricas aditivas.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``TagStatsResponseSchema``: ``tag``,
            ``assetCount``, ``agg``, ``metrics`` (un bloque por métrica) y la
            ventana cubierta (``periodCoveredFrom``/``To``, ``isPeriodClipped``).

        Raises:
            TagNotFoundError: Si la etiqueta no existe o es personal de otro
                usuario; los dos casos dan la misma respuesta.
            UnknownMetricError: Si algún nombre no está en el registro.
            NonAdditiveMetricError: Si se pide ``sum`` de una métrica que no
                se puede sumar entre activos.
        """
        tag = _assert_visible_tag(self.user.id, tag_id)

        definitions = [
            assert_metric_definition(name)
            for name in dict.fromkeys(metric_names or METRIC_REGISTRY)
        ]
        if aggregation == "sum":
            validate_metrics_are_additive(definitions)
        window = _resolve_configured_stats_window(requested_duration)

        assets = build_repository(MonitoredAssetRepository).get_by_tag(self.user.id, tag_id)
        hostnames_by_asset = {asset.id: asset.hostname for asset in assets}
        snapshot_repo = build_repository(AssetSnapshotRepository)
        metrics = {
            definition.name: _render_tag_metric(
                definition,
                snapshot_repo.get_metric_aggregates_by_asset(
                    list(hostnames_by_asset), definition.column, window.since, window.until,
                ),
                hostnames_by_asset,
                aggregation,
            )
            for definition in definitions
        }

        return {
            "tag": tag.to_dict(),
            "assetCount": len(hostnames_by_asset),
            "agg": aggregation,
            "metrics": metrics,
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_tag_ranking(
        self, metric_name: str, aggregation: str, requested_duration: timedelta,
    ) -> dict:
        """
        Ordena todas las etiquetas visibles para el usuario por una métrica.

        Responde a "¿qué etiqueta consume más?" en una llamada. Cada etiqueta
        se calcula igual que en ``get_tag_stats`` (medias del periodo de sus
        activos, combinadas con ``aggregation``), pero sin repetir la consulta
        por etiqueta: primero se resuelve qué activos lleva cada una, después
        se agregan todos esos activos en una sola consulta y la combinación
        por etiqueta se hace en memoria. El coste no crece con el número de
        etiquetas.

        Args:
            metric_name: Nombre público de la métrica por la que se ordena.
            aggregation: ``"sum"``, ``"avg"`` o ``"max"``. ``sum`` solo se
                admite en métricas aditivas.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``TagRankingResponseSchema``: la
            métrica, su unidad, ``agg``, ``tags`` (de mayor a menor valor, las
            etiquetas sin datos al final) y la ventana cubierta.

        Raises:
            UnknownMetricError: Si la métrica no está en el registro.
            NonAdditiveMetricError: Si se pide ``sum`` de una métrica que no
                se puede sumar entre activos.
        """
        definition = assert_metric_definition(metric_name)
        if aggregation == "sum":
            validate_metrics_are_additive([definition])
        window = _resolve_configured_stats_window(requested_duration)

        tag_repository = build_repository(HygeiaTagRepository)
        asset_ids_by_tag = tag_repository.get_asset_ids_by_tag(self.user.id)
        tagged_asset_ids = sorted({
            asset_id for asset_ids in asset_ids_by_tag.values() for asset_id in asset_ids
        })
        snapshot_repo = build_repository(AssetSnapshotRepository)
        aggregates_by_asset = snapshot_repo.get_metric_aggregates_by_asset(
            tagged_asset_ids, definition.column, window.since, window.until,
        )

        ranking = []
        for tag in tag_repository.get_visible_for_user(self.user.id):
            asset_ids = asset_ids_by_tag.get(tag.id, [])
            averages = [aggregates_by_asset[asset_id][0] for asset_id in asset_ids]
            ranking.append({
                "tag": tag.to_dict(),
                "assetCount": len(asset_ids),
                "assetsWithData": sum(1 for average in averages if average is not None),
                "value": combine_asset_averages(averages, aggregation),
            })
        ranking.sort(key=_sort_key_for_tag_ranking)

        return {
            "metric": definition.name,
            "unit": definition.unit,
            "agg": aggregation,
            "tags": ranking,
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_asset_ranking(
        self, metric_name: str, aggregation: str, order: str, limit: int,
        requested_duration: timedelta,
    ) -> dict:
        """
        Ordena los activos del usuario por una métrica y devuelve los ``limit`` extremos.

        Responde a "¿qué equipo está peor?" en una llamada. El valor de cada
        activo es su media (``avg``) o su máximo (``max``) del periodo, y
        salen de una sola consulta agrupada por activo para todo el parque del
        usuario. Los activos sin ninguna muestra de la métrica en el periodo
        no entran en el ranking: no se sabe su valor, y colocarlos como si
        valiera cero los pondría en cabeza de un orden ascendente sin razón.

        Args:
            metric_name: Nombre público de la métrica por la que se ordena.
            aggregation: ``"avg"`` o ``"max"``, qué valor de cada activo se
                compara.
            order: ``"desc"`` (los de mayor valor primero) o ``"asc"``.
            limit: Cuántos activos devolver; positivo.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``AssetRankingResponseSchema``: la
            métrica y su unidad, ``agg``, ``order``, ``assetCount`` (activos
            del usuario), ``assetsWithData``, ``assets`` (el ranking) y la
            ventana cubierta.

        Raises:
            UnknownMetricError: Si la métrica no está en el registro.
        """
        definition = assert_metric_definition(metric_name)
        window = _resolve_configured_stats_window(requested_duration)

        assets = build_repository(MonitoredAssetRepository).get_by_user(self.user.id)
        snapshot_repo = build_repository(AssetSnapshotRepository)
        aggregates_by_asset = snapshot_repo.get_metric_aggregates_by_asset(
            [asset.id for asset in assets], definition.column, window.since, window.until,
        )
        entries = []
        for asset in assets:
            average, maximum, sample_count = aggregates_by_asset[asset.id]
            if sample_count:
                entries.append({
                    "assetId": asset.id,
                    "hostname": asset.hostname,
                    "value": average if aggregation == "avg" else maximum,
                    "sampleCount": sample_count,
                })

        return {
            "metric": definition.name,
            "unit": definition.unit,
            "agg": aggregation,
            "order": order,
            "assetCount": len(assets),
            "assetsWithData": len(entries),
            "assets": _rank_assets(entries, order, limit),
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_breach_ranking(self, limit: int, requested_duration: timedelta) -> dict:
        """
        Ordena los activos del usuario por cuántas veces cruzaron sus umbrales en el periodo.

        Responde a "¿qué máquina da más guerra?" con lo que el detector ya
        dejó escrito. Cada anomalía abierta es un cruce de umbral sostenido
        (``services/detection.py`` solo la crea cuando la métrica lleva por
        encima del umbral los latidos que pide ``sustainedHeartbeats``), así
        que el recuento de aperturas del periodo **es** el recuento de
        incumplimientos. No se recalcula ningún umbral aquí: es exposición de
        un dato ya persistido.

        Junto al recuento va ``currentBreachStreak``, la suma de
        ``MonitoredAsset.breach_counters``, que es otra cosa y por eso viaja
        aparte: cuántos latidos consecutivos lleva el activo en rojo **ahora
        mismo**. Un activo puede encabezar el ranking del mes con la racha a
        cero (cruzó muchas veces y se recuperó) o cerrarlo con una racha viva
        (está rompiendo por primera vez). Los dos datos responden preguntas
        distintas y ninguno sustituye al otro.

        ``mostConflictiveMetric`` mira el parque entero, no solo los ``limit``
        activos devueltos: es la métrica con más aperturas acumuladas entre
        todos los activos del usuario. Las anomalías sin métrica (``host_down``,
        que nace del silencio de un agente y no de un umbral) cuentan en el
        recuento por activo —es un incidente del activo— pero no compiten por
        ser "la métrica más conflictiva", porque no son una métrica.

        Args:
            limit: Cuántos activos devolver; positivo.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``BreachRankingResponseSchema``:
            ``assetCount`` (activos del usuario), ``totalBreaches`` (los del
            parque entero en la ventana, no solo los de las entradas
            devueltas), ``assets`` (el ranking), ``mostConflictiveMetric``
            (``None`` si no hubo ninguna apertura con métrica) y la ventana
            cubierta.
        """
        window = _resolve_configured_stats_window(requested_duration)

        assets = build_repository(MonitoredAssetRepository).get_by_user(self.user.id)
        asset_ids = [asset.id for asset in assets]
        anomaly_repo = build_repository(AnomalyRepository)
        breaches_by_asset = anomaly_repo.count_opened_by_asset(
            asset_ids, window.since, window.until,
        )
        breaches_by_metric = anomaly_repo.count_opened_by_metric(
            asset_ids, window.since, window.until,
        )

        entries = [
            {
                "assetId": asset.id,
                "hostname": asset.hostname,
                "breachCount": breaches_by_asset[asset.id],
                "currentBreachStreak": _total_breach_streak(asset.breach_counters),
            }
            for asset in assets
        ]
        entries.sort(key=_sort_key_for_breach_ranking)

        most_conflictive = max(
            breaches_by_metric.items(), key=lambda item: (item[1], item[0]), default=None,
        )
        return {
            "assetCount": len(assets),
            "totalBreaches": sum(breaches_by_asset.values()),
            "assets": entries[:limit],
            "mostConflictiveMetric": (
                {"metric": most_conflictive[0], "breachCount": most_conflictive[1]}
                if most_conflictive is not None else None
            ),
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_fullest_mounts(self, limit: int) -> dict:
        """
        Lista los activos del usuario cuyo montaje más lleno está más cerca de llenarse.

        Responde a "¿qué disco del parque se va a llenar antes?" sin abrir
        cada activo. Usa solo el **último** heartbeat de cada activo y su
        columna ``disk_max_pct``, nunca el histórico ni el JSONB: es una foto
        del estado actual, así que no recibe ``period``. Un activo cuyo último
        heartbeat no traía disco, o que nunca reportó, no entra: no se sabe su
        uso. Los empates se resuelven por hostname.

        Args:
            limit: Cuántos activos devolver; positivo.

        Returns:
            Diccionario con la forma de ``FleetDiskResponseSchema``:
            ``assetCount``, ``assetsWithData`` y ``mounts`` (``assetId``,
            ``hostname``, ``mount``, ``usagePct`` y ``receivedAt``), de mayor
            a menor uso.
        """
        assets = build_repository(MonitoredAssetRepository).get_by_user(self.user.id)
        latest_by_asset = build_repository(
            AssetSnapshotRepository,
        ).get_latest_disk_usage_by_asset([asset.id for asset in assets])

        entries = []
        for asset in assets:
            received_at, usage, mount = latest_by_asset.get(asset.id, (None, None, None))
            if usage is not None:
                entries.append({
                    "assetId": asset.id,
                    "hostname": asset.hostname,
                    "mount": mount,
                    "usagePct": usage,
                    "receivedAt": received_at,
                })
        entries.sort(key=lambda entry: (-entry["usagePct"], entry["hostname"].lower()))

        return {
            "assetCount": len(assets),
            "assetsWithData": len(entries),
            "mounts": entries[:limit],
        }

    def get_fleet_overview(self) -> dict:
        """
        Resume el estado actual del parque del usuario en una sola llamada.

        Es la pantalla de aterrizaje de las estadísticas: cuántos activos hay
        en cada estado, cuántas anomalías piden atención y cuándo reportó el
        parque por última vez, sin que el cliente tenga que orquestar varias
        llamadas. Es una foto del instante actual, no un periodo: por eso no
        recibe ``period`` ni pasa por la ventana de estadísticas.

        Returns:
            Diccionario con la forma de ``FleetOverviewResponseSchema``:
            ``assetCount``, ``assetsByStatus`` (los cuatro estados, a cero si
            no hay ninguno), ``openAnomaliesBySeverity`` (las tres
            severidades), ``acknowledgedAnomalyCount``, ``averageUptimeSec``
            (solo de los activos en línea; ``None`` si no hay) y
            ``lastActivityAt`` (``None`` si ningún activo ha reportado).
        """
        asset_repo = build_repository(MonitoredAssetRepository)
        assets_by_status = asset_repo.count_by_status(self.user.id)
        anomalies_by_state_and_severity = build_repository(
            AnomalyRepository,
        ).count_active_by_state_and_severity(self.user.id)

        return {
            "assetCount": sum(assets_by_status.values()),
            "assetsByStatus": {
                status: assets_by_status.get(status, 0) for status in _ASSET_STATUSES
            },
            "openAnomaliesBySeverity": {
                severity: anomalies_by_state_and_severity.get(("open", severity), 0)
                for severity in _ANOMALY_SEVERITIES
            },
            "acknowledgedAnomalyCount": sum(
                anomaly_count
                for (state, _), anomaly_count in anomalies_by_state_and_severity.items()
                if state == "acknowledged"
            ),
            "averageUptimeSec": asset_repo.get_average_online_uptime(self.user.id),
            "lastActivityAt": asset_repo.get_last_activity(self.user.id),
        }

    def get_metric_histogram(
        self, metric_name: str, aggregation: str, bin_count: int, requested_duration: timedelta,
    ) -> dict:
        """
        Reparte los activos del usuario en franjas según una métrica.

        El ranking enseña los extremos; el histograma enseña la forma del
        parque: cuántos equipos están cómodos y cuántos empiezan a apretar. Un
        activo al 60 % de memoria en un parque donde todos están al 20 % no
        sale entre los primeros de un ranking corto, pero sí salta a la vista
        en una franja casi vacía.

        El valor de cada activo es su media (``avg``) o su máximo (``max``)
        del periodo, de una sola consulta agrupada por activo. Los activos sin
        datos no se reparten en ninguna franja.

        Args:
            metric_name: Nombre público de la métrica.
            aggregation: ``"avg"`` o ``"max"``.
            bin_count: Número de franjas.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``MetricHistogramResponseSchema``: la
            métrica y su unidad, ``agg``, ``assetCount``, ``assetsWithData``,
            ``bins`` y la ventana cubierta. ``bins`` va vacío si la métrica no
            es un porcentaje y ningún activo tuvo datos: no hay rango que
            partir.

        Raises:
            UnknownMetricError: Si la métrica no está en el registro.
        """
        definition = assert_metric_definition(metric_name)
        window = _resolve_configured_stats_window(requested_duration)

        assets = build_repository(MonitoredAssetRepository).get_by_user(self.user.id)
        snapshot_repo = build_repository(AssetSnapshotRepository)
        aggregates_by_asset = snapshot_repo.get_metric_aggregates_by_asset(
            [asset.id for asset in assets], definition.column, window.since, window.until,
        )
        values = [
            average if aggregation == "avg" else maximum
            for average, maximum, sample_count in aggregates_by_asset.values()
            if sample_count
        ]
        value_range = _resolve_histogram_range(definition, values)

        return {
            "metric": definition.name,
            "unit": definition.unit,
            "agg": aggregation,
            "assetCount": len(assets),
            "assetsWithData": len(values),
            "bins": [] if value_range is None else build_histogram(values, bin_count, *value_range),
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_power_stats(
        self, scope: str, tag_id: Optional[int], requested_duration: timedelta,
    ) -> dict:
        """
        Energía y coste de un conjunto de activos: todo el parque o los de una etiqueta.

        Cada activo se calcula exactamente igual que en su resumen de consumo
        (``summarize_power_period``: media ponderada por duración, energía
        solo sobre el tiempo observado, y su procedencia), y después se
        agregan. Las muestras de potencia de todos los activos salen de una
        sola consulta.

        Los kWh y el coste se **suman**, porque cada uno ya está calculado
        sobre su propio tiempo observado. La potencia media del conjunto no
        se da: sumar o promediar medias de activos con coberturas distintas
        no mide nada claro, y el desglose ya trae la de cada activo. Un
        activo sin datos de energía no aporta un cero al total.

        Args:
            scope: ``"fleet"`` (todos los activos del usuario) o ``"tag"``.
            tag_id: Etiqueta, con ``scope="tag"``; tiene que ser visible para
                el usuario. ``None`` con ``scope="fleet"``.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``PowerStatsResponseSchema``: el
            alcance y la etiqueta, recuentos de activos (con datos y con
            potencia estimada), ``kwh``/``cost``/``currency`` totales (``None``
            si ningún activo tuvo datos), la procedencia del conjunto (la peor
            de sus activos), el desglose por activo de más a menos kWh y la
            ventana cubierta.

        Raises:
            TagNotFoundError: Con ``scope="tag"``, si la etiqueta no existe o
                es personal de otro usuario.
        """
        asset_repo = build_repository(MonitoredAssetRepository)
        tag = None
        if scope == "tag":
            tag = _assert_visible_tag(self.user.id, tag_id)
            assets = asset_repo.get_by_tag(self.user.id, tag_id)
        else:
            assets = asset_repo.get_by_user(self.user.id)

        window = _resolve_configured_stats_window(requested_duration)
        asset_ids = [asset.id for asset in assets]
        snapshot_repo = build_repository(AssetSnapshotRepository)
        estimated_asset_ids = snapshot_repo.get_asset_ids_with_estimated_power(
            asset_ids, window.since, window.until,
        )
        config = CR.hygeia_config()
        breakdown = _build_power_breakdown(
            assets,
            snapshot_repo.get_metric_samples_by_asset(
                asset_ids, AssetSnapshot.power_watts, window.since, window.until,
            ),
            estimated_asset_ids, window, config,
        )
        with_data = [entry for entry in breakdown if entry["kwh"] is not None]

        return {
            "scope": scope,
            "tag": None if tag is None else tag.to_dict(),
            "assetCount": len(assets),
            "assetsWithData": len(with_data),
            "assetsEstimated": len(estimated_asset_ids),
            "kwh": sum(entry["kwh"] for entry in with_data) if with_data else None,
            "cost": sum(entry["cost"] for entry in with_data) if with_data else None,
            "currency": config.energy_price_currency,
            "classification": _combine_power_classifications(
                [entry["classification"] for entry in with_data],
            ),
            "assets": breakdown,
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_hourly_pattern(  # pylint: disable=too-many-arguments
        self, metric_name: str, *, scope: str, tag_id: Optional[int], asset_id: Optional[int],
        aggregation: str, requested_duration: timedelta,
    ) -> dict:
        """
        Reparte una métrica por hora del día: a qué horas aprieta un ámbito.

        Responde a "¿siempre a las nueve?" sin exportar la serie cruda y
        agruparla a mano. Todos los heartbeats del periodo caen en el cubo de
        su hora (``received_at``, el reloj del servidor) y se resumen con
        ``aggregation``, así que una ventana de 30 días de todo un parque
        vuelve como 24 cifras en una sola consulta.

        La hora es la del **servidor**, no la del agente: el reloj de un host
        puede ir mal puesto o en otra zona horaria, y mezclarlos daría un
        patrón que no es el de nadie. Quien pinte el resultado sabe en qué
        huso está la API y puede desplazarlo.

        Las 24 horas salen siempre, también las que no tuvieron ningún
        heartbeat: su valor es ``None`` y su ``sampleCount`` ``0``, nunca un
        cero que se confundiría con "a esa hora el parque estaba a cero". Un
        parque que se apaga de noche tiene que verse como un hueco, no como un
        valle.

        Args:
            metric_name: Nombre público de la métrica (``cpuPct``…).
            scope: ``"asset"``, ``"tag"`` o ``"fleet"``.
            tag_id: Etiqueta, con ``scope="tag"``. ``None`` en el resto.
            asset_id: Activo, con ``scope="asset"``. ``None`` en el resto.
            aggregation: ``"min"``, ``"avg"`` o ``"max"``, cómo se resume cada
                hora.
            requested_duration: Duración del periodo pedido, antes de recortar.

        Returns:
            Diccionario con la forma de ``HourlyPatternResponseSchema``: la
            métrica y su unidad, ``agg``, el ámbito (``scope``, ``tag`` y
            ``assetCount``), ``hours`` (24 entradas, de la 0 a la 23),
            ``peakHour`` (la de mayor valor, ``None`` si ninguna tuvo
            muestras) y la ventana cubierta.

        Raises:
            UnknownMetricError: Si la métrica no está en el registro.
            TagNotFoundError: Si la etiqueta no es visible para el usuario.
            AssetNotFoundError: Si el activo no existe o no es suyo.
        """
        definition = assert_metric_definition(metric_name)
        tag, assets = _resolve_scope_assets(self.user.id, scope, tag_id, asset_id)
        window = _resolve_configured_stats_window(requested_duration)

        aggregates_by_hour = build_repository(AssetSnapshotRepository).get_hour_of_day_aggregates(
            [asset.id for asset in assets], definition.column,
            window.since, window.until, aggregation,
        )
        hours = [
            {
                "hour": hour,
                "value": aggregates_by_hour.get(hour, (None, 0))[0],
                "sampleCount": aggregates_by_hour.get(hour, (None, 0))[1],
            }
            for hour in _HOURS_OF_DAY
        ]
        peak = max(
            (entry for entry in hours if entry["value"] is not None),
            key=lambda entry: entry["value"], default=None,
        )

        return {
            "metric": definition.name,
            "unit": definition.unit,
            "agg": aggregation,
            "scope": scope,
            "tag": None if tag is None else tag.to_dict(),
            "assetCount": len(assets),
            "hours": hours,
            "peakHour": None if peak is None else peak["hour"],
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }

    def get_metric_series(  # pylint: disable=too-many-arguments,too-many-locals
        self, metric_name: str, *, tag_id: Optional[int], asset_ids: Optional[Sequence[int]],
        aggregation: Optional[str], bucket_aggregation: str,
        requested_bucket_seconds: Optional[int], requested_duration: timedelta,
        compare_to: Optional[Tuple[str, int]] = None,
    ) -> dict:
        """
        Serie temporal por cubos de una métrica sobre varios activos.

        Es la base de una gráfica apilada o comparativa: "tráfico total de la
        etiqueta producción en las últimas 24 horas", sin que el navegador
        tenga que sumar punto a punto N series. Sin ``aggregation`` devuelve
        una serie por activo; con ella, una única serie que los combina. Todo
        sale de una sola consulta, sea cual sea el número de activos.

        Cada activo se resume primero dentro de su cubo (``bucket_aggregation``)
        y después se combinan los activos (``aggregation``): así un activo que
        mandó dos heartbeats en el mismo cubo no cuenta dos veces.

        Args:
            metric_name: Nombre público de la métrica.
            tag_id: Etiqueta cuyos activos entran, o ``None``.
            asset_ids: Ids de los activos que entran, o ``None``. Exactamente
                uno de los dos viene informado (lo valida el schema).
            aggregation: ``"sum"``, ``"avg"`` o ``"max"`` para combinar los
                activos en una serie, o ``None`` para una serie por activo.
                ``sum`` solo en métricas aditivas.
            bucket_aggregation: ``"min"``, ``"avg"`` o ``"max"``, cómo se
                resume cada cubo dentro de un activo.
            requested_bucket_seconds: Cubo pedido en segundos, o ``None`` para
                el más fino que cabe en ``maxSeriesPoints``.
            requested_duration: Duración del periodo pedido, antes de recortar.
            compare_to: Segunda fuente con la que comparar, ``("asset", id)``
                o ``("tag", id)``, o ``None``. Su serie va al final de
                ``series``, marcada con ``isComparison``, y comparte los cubos
                de la principal. Por defecto ``None``.

        Returns:
            Diccionario con la forma de ``MetricSeriesResponseSchema``: la
            métrica y su unidad, el cubo usado (``bucket``, e
            ``isBucketWidened`` si hubo que ensancharlo), ``bucketAgg``,
            ``agg``, ``series`` y la ventana cubierta.

        Raises:
            UnknownMetricError: Si la métrica no está en el registro.
            NonAdditiveMetricError: Si se pide ``sum`` de una métrica no aditiva.
            TagNotFoundError: Si la etiqueta no es visible para el usuario.
            AssetNotFoundError: Si algún activo pedido no existe o no es suyo.
        """
        definition = assert_metric_definition(metric_name)
        if aggregation == "sum":
            validate_metrics_are_additive([definition])
        tag, assets = _resolve_series_assets(self.user.id, tag_id, asset_ids)

        window = _resolve_configured_stats_window(requested_duration)
        max_points = CR.hygeia_limits().max_series_points
        bucket_seconds, is_bucket_widened = _resolve_series_bucket(
            window, requested_bucket_seconds, max_points,
        )
        series_query = _SeriesQuery(
            definition=definition, bucket_seconds=bucket_seconds, window=window,
            bucket_aggregation=bucket_aggregation, aggregation=aggregation, max_points=max_points,
        )
        snapshot_repo = build_repository(AssetSnapshotRepository)
        series = _build_series(
            snapshot_repo, series_query, tag, assets, is_combined=aggregation is not None,
        )
        if compare_to is not None:
            series += _build_comparison_series(
                self.user.id, snapshot_repo, series_query, compare_to,
            )

        return {
            "metric": definition.name,
            "unit": definition.unit,
            "bucket": bucket_seconds,
            "isBucketWidened": is_bucket_widened,
            "bucketAgg": bucket_aggregation,
            "agg": aggregation,
            "series": series,
            "periodCoveredFrom": window.since,
            "periodCoveredTo": window.until,
            "isPeriodClipped": window.is_clipped,
        }


class HygeiaReportManager:
    """
    Genera el informe PDF del inventario de activos de un usuario.

    Síncrono a propósito: un inventario son filas de una tabla, no un escaneo.
    Construirlo cuesta milisegundos, así que no necesita cola, ni fila en
    ``Document``, ni que la SPA sondee un estado — se pide y se descarga. Si
    algún día hubiera que archivarlo o tardara segundos, ese es el momento de
    llevarlo a la TaskQueue, no antes.
    """

    def __init__(self, user: User) -> None:
        self.user = user

    def build_inventory_report(self, scope: str, include_software: bool) -> tuple[bytes, str]:
        """
        Construye el PDF del inventario.

        Args:
            scope: ``"user"`` (los activos propios) u ``"organization"`` (los
                de todos los miembros, solo para el dueño).
            include_software: Añade el anexo con el software instalado.

        Returns:
            ``(bytes del PDF, nombre de fichero sugerido)``.

        Raises:
            OrganizationScopeNotAllowedError: Si se pide el ámbito de
                organización sin ser dueño de una.
        """
        if scope == "organization":
            assets, scope_label, owner_names = self._organization_scope()
        else:
            assets = build_repository(MonitoredAssetRepository).get_by_user(self.user.id)
            scope_label, owner_names = "Mis activos", {}

        author = f"{self.user.first_name} {self.user.last_name}".strip() or self.user.username
        pdf = build_inventory_report(
            assets=assets,
            scope_label=scope_label,
            author=author,
            include_software=include_software,
            owner_names=owner_names,
        )

        stamp = utcnow_naive().strftime("%Y%m%d")
        suffix = "organizacion" if scope == "organization" else "propio"
        return pdf, f"inventario-hygeia-{suffix}-{stamp}.pdf"

    def _organization_scope(self) -> tuple[list, str, dict]:
        """Activos de toda la organización, si el usuario es su dueño.

        Se apoya en la superficie pública de ``accounts`` (``OrganizationManager``)
        y no en sus repositorios: el recuento de miembros y sus nombres ya los
        resuelve ``list_members`` con un solo JOIN, y de paso vuelve a exigir la
        propiedad ahí dentro. Tampoco usa el decorador
        ``require_organization_owner``, que espera un ``organization_id`` en la
        ruta mientras que aquí el ámbito viaja en el cuerpo.

        No tener organización y tener una que no es tuya fallan igual y con el
        mismo error: distinguirlos diría a un miembro cualquiera si su
        organización existe y quién manda en ella.
        """
        organization_manager = OrganizationManager()
        organization = organization_manager.get_mine(self.user.id)
        if organization is None or not organization.get("isOwner"):
            raise OrganizationScopeNotAllowedError()

        members = organization_manager.list_members(organization["id"], self.user.id)
        owner_names = {
            member["userId"]: member["fullName"] or member["username"]
            for member in members
        }

        assets = build_repository(MonitoredAssetRepository).get_by_users(list(owner_names))
        return assets, organization["name"], owner_names


class HygeiaIngestManager:
    """
    Procesa los heartbeats que empujan los agentes Hygeia.

    Toda la lógica de un heartbeat vive en una única transacción: actualizar
    la presencia del activo, resolver una posible caída ya detectada,
    persistir el snapshot y evaluar los umbrales de CPU/memoria/disco
    (histéresis, apertura/resolución de anomalías). Comparar unos umbrales
    estáticos contra un único snapshot son microsegundos — no justifica una
    tarea RQ aparte; vive en la misma transacción del request.
    """

    def __init__(self, asset_id: int) -> None:
        self.asset_id = asset_id

    def ingest_heartbeat(self, payload: dict) -> dict:
        """
        Procesa un heartbeat ya autenticado y validado por schema.

        El orden importa: actualizar la presencia y resolver una
        anomalía ``host_down`` abierta ocurre **antes** de tocar las
        métricas del propio payload, para que el primer heartbeat tras una
        caída cierre la incidencia sin depender de si sus valores cruzan o
        no un umbral.

        Args:
            payload: Heartbeat ya validado por ``IngestRequestSchema``
                (``collectedAt`` ya normalizado a naive-UTC por el schema).

        Returns:
            Diccionario con ``ok``, ``nextIntervalSec`` (el intervalo que
            este activo debe usar en su próximo envío) y ``serverTime``.

        Raises:
            AssetNotFoundError: Si el activo resuelto por la clave ya no
                existe (no debería ocurrir: ``require_agent_key`` ya lo
                resolvió en esta misma request).
            IngestTooFrequentError: Si el heartbeat llega por debajo del
                suelo de cadencia configurado para esta clave.
        """
        check_clock_skew(payload["collectedAt"])

        notify_dispatch_ids: list[int] = []

        with UnitOfWork() as uow:
            asset_repo = MonitoredAssetRepository(uow)
            asset = asset_repo.get_by_id(self.asset_id)
            if asset is None:
                raise AssetNotFoundError(self.asset_id)

            now = utcnow_naive()
            self._enforce_min_interval(asset, now)

            asset.last_seen_at = now
            asset.status = "online"
            asset.agent_version = payload["agentVersion"]
            asset.os = payload["host"]["os"] or asset.os
            # El kernel es identidad del host: si un heartbeat no lo trae, se
            # conserva el último conocido. El uptime es estado instantáneo, así
            # que se sobreescribe siempre — un None ahí también es información.
            asset.kernel = payload["host"]["kernel"] or asset.kernel
            # Mismo trato que el kernel: un agente que aún no reporte
            # estos dos campos (versión anterior a esta necesidad) no debe
            # borrar lo que ya se sabía.
            host = payload["host"]
            asset.virtualization_system = (
                host["virtualizationSystem"] or asset.virtualization_system
            )
            asset.virtualization_role = host["virtualizationRole"] or asset.virtualization_role
            asset.uptime_sec = payload["host"]["uptimeSec"]
            # `inventory` es opcional (omitempty en el agente) y, cuando llega,
            # es el estado COMPLETO del software instalado, nunca un delta: se
            # reemplaza sin fusionar. `None` = el agente no escaneó en este
            # heartbeat (se conserva el inventario anterior); `[]` sí es un
            # reemplazo válido (host sin software, o stub Linux/macOS).
            if payload["inventory"] is not None:
                asset.inventory = payload["inventory"]["software"]
                asset.inventory_collected_at = now
            asset_repo.update(asset)

            _resolve_host_down_if_open(uow, asset.id)

            metrics = payload["metrics"]
            # La forma del payload la conocen el schema de ingesta y
            # ``denormalize``, y nadie más: el camino de lectura sirve la serie
            # temporal desde columnas y no abre el JSONB jamás.
            snapshot = AssetSnapshot(
                asset_id=asset.id,
                collected_at=payload["collectedAt"],
                received_at=now,
                metrics=metrics,
                **denormalize(metrics),
            )
            AssetSnapshotRepository(uow).save(snapshot)

            critical_anomaly_ids = self._evaluate_thresholds(uow, asset, metrics)

            next_interval = asset.heartbeat_interval_sec or CR.hygeia_config().heartbeat_interval_sec

            if critical_anomaly_ids:
                # La anomalía abierta es el guardia anti-duplicado: el próximo
                # heartbeat la ve activa y no la reabre. Por eso su intención
                # de avisar viaja en el mismo commit; confirmada sola,
                # un encolado fallido perdía el correo para siempre.
                dispatch_repo = TaskDispatchRepository(uow)
                notify_dispatch_ids = [
                    dispatch_repo.save(HygeiaNotifyManager.build_dispatch_for(anomaly_id)).id
                    for anomaly_id in critical_anomaly_ids
                ]
                # Durable antes de publicar: el worker de notificación
                # corre en otro proceso y debe poder leer ya la anomalía.
                uow.commit_for_handoff()

        # Publicar siempre fuera del UnitOfWork: nunca bloquear la respuesta
        # al agente por la latencia de SMTP — el correo lo manda el
        # worker, no esta request. Si Redis falla, las filas quedan `pending`
        # y las recoge el barrido de la outbox.
        for dispatch_id in notify_dispatch_ids:
            OutboxDispatcher.dispatch(dispatch_id)

        return {
            "ok": True,
            "nextIntervalSec": next_interval,
            "serverTime": utcnow_naive(),
        }

    @staticmethod
    def _enforce_min_interval(asset: MonitoredAsset, now) -> None:
        """Rechaza un heartbeat que llega antes del suelo de cadencia;
        es decir, que el tiempo entre el hearthbeat actual y el último registrado es menor que
        el tiempo dado: ``features.hygeia.limits.minIntervalSec``.

        No persiste nada: se comprueba antes de tocar el activo o el
        snapshot, así que un heartbeat rechazado no deja rastro alguno.
        """
        if asset.last_seen_at is None:
            return
        min_interval = CR.hygeia_limits().min_interval_sec
        elapsed = (now - asset.last_seen_at).total_seconds()
        if elapsed < min_interval:
            raise IngestTooFrequentError(min_interval)

    @staticmethod
    def _evaluate_thresholds(uow: UnitOfWork, asset: MonitoredAsset, metrics: dict) -> list[int]:
        """
        Evalúa las métricas del heartbeat contra los umbrales efectivos del
        activo y aplica el resultado: abre anomalías nuevas, resuelve las
        que ya no aplican, y persiste los contadores de histéresis
        actualizados en el propio activo.

        Los umbrales por activo (``MonitoredAsset.thresholds``) sustituyen
        por completo — métrica a métrica — a los globales de
        ``features.hygeia.thresholds``; no se fusionan campo a campo dentro de una
        misma métrica.

        Returns:
            IDs de las anomalías recién abiertas con severidad ``critical``.
            El llamador las usa para encolar la notificación por correo
            **después** de confirmar esta transacción — nunca desde
            aquí, que todavía vive dentro del ``UnitOfWork``.
        """
        thresholds = {**CR.hygeia_config().thresholds, **(asset.thresholds or {})}

        anomaly_repo = AnomalyRepository(uow)
        active_anomalies = {
            (anomaly.kind, anomaly.metric): anomaly for anomaly in anomaly_repo.get_all_active(asset.id)
        }
        outcome = evaluate(
            metrics=metrics,
            breach_counters=asset.breach_counters or {},
            open_kinds=set(active_anomalies.keys()),
            thresholds=thresholds,
        )

        critical_anomaly_ids: list[int] = []
        for change in outcome.to_open:
            saved = anomaly_repo.save(Anomaly(
                asset_id=asset.id,
                kind=change.kind,
                severity=change.severity,
                metric=change.metric,
                value=change.value,
                threshold=change.threshold,
            ))
            if change.severity == "critical":
                critical_anomaly_ids.append(saved.id)

        for key in outcome.to_resolve:
            anomaly = active_anomalies[key]
            anomaly.state = "resolved"
            anomaly.resolved_at = utcnow_naive()
            anomaly_repo.update(anomaly)

        asset.breach_counters = outcome.breach_counters
        MonitoredAssetRepository(uow).update(asset)

        return critical_anomaly_ids


class HygeiaAlertManager:
    """
    Gestiona el ciclo de vida de las anomalías (alertas) de los activos de
    un usuario: listado con filtros, reconocimiento y resolución manual.
    """

    def __init__(self, user: User) -> None:
        self.user = user

    def list_alerts(
        self,
        state: Optional[str] = None,
        severity: Optional[str] = None,
        asset_id: Optional[int] = None,
    ) -> list[dict]:
        """Lista las anomalías de los activos del usuario, con filtros opcionales."""
        repo = build_repository(AnomalyRepository)
        anomalies = repo.get_for_user(
            self.user.id, state=state, severity=severity, asset_id=asset_id,
        )
        return [anomaly.to_dict() for anomaly in anomalies]

    def ack_alert(self, anomaly_id: int) -> dict:
        """
        Reconoce una anomalía: registra que el dueño la ha visto, sin darla
        por resuelta.

        Raises:
            AnomalyNotFoundError: Si la anomalía no existe o pertenece a
                otro usuario (misma excepción en ambos casos).
        """
        with UnitOfWork() as uow:
            repo = AnomalyRepository(uow)
            anomaly = self._get_owned_anomaly(repo, anomaly_id, self.user.id)
            anomaly.state = "acknowledged"
            repo.update(anomaly)

        return anomaly.to_dict()

    def resolve_alert(self, anomaly_id: int) -> dict:
        """
        Resuelve manualmente una anomalía, sea cual sea su estado actual.

        Si la métrica que la disparó sigue por encima del umbral en el
        próximo heartbeat, ``evaluate()`` la reabre de inmediato — resolver
        a mano no reinicia el contador de histéresis, así que una anomalía
        genuina no queda enmascarada por error.

        Raises:
            AnomalyNotFoundError: Si la anomalía no existe o pertenece a
                otro usuario (misma excepción en ambos casos).
        """
        with UnitOfWork() as uow:
            repo = AnomalyRepository(uow)
            anomaly = self._get_owned_anomaly(repo, anomaly_id, self.user.id)
            anomaly.state = "resolved"
            anomaly.resolved_at = utcnow_naive()
            repo.update(anomaly)
            return anomaly.to_dict()

    def delete_alert(self, anomaly_id: int) -> None:
        """
        Borra una anomalía ya reconocida o resuelta.

        Una anomalía ``open`` no se puede borrar (§ver ``AnomalyStillOpenError``):
        primero hay que reconocerla o resolverla, para que el borrado sea
        siempre sobre algo que el dueño ya atendió, nunca un descarte
        silencioso de una condición activa sin ver.

        Raises:
            AnomalyNotFoundError: Si la anomalía no existe o pertenece a
                otro usuario (misma excepción en ambos casos).
            AnomalyStillOpenError: Si la anomalía sigue en estado ``open``.
        """
        with UnitOfWork() as uow:
            repo = AnomalyRepository(uow)
            anomaly = self._get_owned_anomaly(repo, anomaly_id, self.user.id)
            if anomaly.state == "open":
                raise AnomalyStillOpenError(anomaly_id)
            repo.delete(anomaly)

    @staticmethod
    def _get_owned_anomaly(repo: AnomalyRepository, anomaly_id: int, user_id: int) -> Anomaly:
        """Obtiene una anomalía por id y verifica que pertenece a un activo de ``user_id``."""
        anomaly = repo.get_by_id_for_user(anomaly_id, user_id)
        if anomaly is None:
            raise AnomalyNotFoundError(anomaly_id)
        return anomaly


class HygeiaMaintenanceManager:
    """
    Tareas periódicas de mantenimiento de Hygeia: detector de presencia
    (host caído) y poda de snapshots antiguos.

    Se invocan directamente desde ``HygeiaScheduler`` (APScheduler), sin
    pasar por ``TaskQueue`` — igual que ``KbSyncManager.execute_kb_sync`` en
    Themis: son tareas de mantenimiento periódicas, no trabajos de usuario
    que necesiten seguimiento ni cancelación cooperativa.
    """

    @staticmethod
    def execute_presence_check() -> None:
        """
        Detecta activos que llevan demasiado callados y transiciona su
        presencia en dos escalones:

        1. ``online`` → ``stale`` en el primer corte (un heartbeat perdido):
           señal visual en el listado de activos, no abre ninguna incidencia.
        2. ``stale`` → ``offline`` en un segundo corte más permisivo
           (``offlineAfterMissed`` heartbeats perdidos): solo esta segunda
           transición abre ``Anomaly(kind="host_down")``, y solo si el activo
           es persistente y no había ya una abierta (apertura idempotente).

        Un activo no persistente (``is_persistent=False``: un host que se
        apaga a propósito) transiciona igual — su estado es un hecho
        observado y la lista debe mostrarlo — pero no abre anomalía, y al no
        haber anomalía tampoco hay correo.

        Cada activo se compara contra su propio ``heartbeat_interval_sec``
        (el que tiene configurado, tras un posible auto-ajuste), no contra
        el valor global — un activo que reporta más despacio de lo habitual
        no debe declararse caído por comparar contra el intervalo por defecto.

        Los dos escalones se deciden sobre el ``status`` tal como se leyó al
        principio de esta ejecución: un activo que hoy pasa a ``stale`` no
        se reevalúa también contra el corte de ``offline`` en la misma
        pasada — necesita aparecer como ``stale`` durante al menos un ciclo
        del job antes de poder caer a ``offline``.

        Cada ``host_down`` recién abierto encola su notificación por correo,
        y la intención de encolarla se guarda en la misma transacción
        que la anomalía: la anomalía abierta es el guardia que impide
        abrir otra en la pasada siguiente, así que si se confirmaba sola y el
        encolado fallaba después, el correo no llegaba nunca. Este job corre en
        background (nunca en una request), así que ``UnitOfWork`` ya confirma
        la transacción al salir del bloque; no hace falta un
        ``commit_for_handoff()`` explícito para que el worker de notificación
        vea la anomalía.
        """
        notify_dispatch_ids: list[int] = []

        with UnitOfWork() as uow:
            asset_repo = MonitoredAssetRepository(uow)
            anomaly_repo = AnomalyRepository(uow)
            dispatch_repo = TaskDispatchRepository(uow)
            now = utcnow_naive()
            offline_after_missed = CR.hygeia_config().offline_after_missed

            for asset in asset_repo.get_active_for_presence_check():
                interval = asset.heartbeat_interval_sec or CR.hygeia_config().heartbeat_interval_sec

                if asset.status == "online":
                    stale_cutoff = now - timedelta(seconds=interval)
                    asset_repo.transition_status_if_still_silent(
                        asset.id, stale_cutoff, "online", "stale",
                    )
                elif asset.status == "stale":
                    offline_cutoff = now - timedelta(seconds=interval * offline_after_missed)
                    transitioned = asset_repo.transition_status_if_still_silent(
                        asset.id, offline_cutoff, "stale", "offline",
                    )
                    if (
                        transitioned
                        and asset.is_persistent
                        and anomaly_repo.get_active(asset.id, "host_down") is None
                    ):
                        saved = anomaly_repo.save(Anomaly(
                            asset_id=asset.id, kind="host_down", severity="critical",
                        ))
                        notify_dispatch_ids.append(
                            dispatch_repo.save(HygeiaNotifyManager.build_dispatch_for(saved.id)).id
                        )

        # Camino feliz: publicar ya. Si Redis falla, las filas quedan `pending`
        # y las recogen el barrido periódico o la reconciliación de arranque.
        for dispatch_id in notify_dispatch_ids:
            OutboxDispatcher.dispatch(dispatch_id)

    @staticmethod
    def execute_retention() -> int:
        """
        Elimina los ``AssetSnapshot`` anteriores a ``features.hygeia.retentionDays``.

        Returns:
            Número de filas eliminadas.
        """
        cutoff = utcnow_naive() - timedelta(days=CR.hygeia_config().retention_days)
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            rows_affected = repo.delete_older_than(cutoff)

        return rows_affected


class HygeiaNotifyManager:
    """
    Envía la notificación por correo de una anomalía crítica recién abierta.

    Se dispara de forma asíncrona (``TaskQueue``, categoría
    ``hygeia.notify``) a través de la outbox transaccional, cuya fila se
    guarda en la misma transacción que abre la anomalía — nunca de forma
    síncrona en la ingesta ni en el job de presencia, para no bloquear la
    respuesta al agente ni al propio scheduler por la latencia de SMTP.
    """

    TASK_CATEGORY = "hygeia.notify"
    EXTERNAL_ID_PREFIX = "hygeia-notify:"

    @staticmethod
    def build_dispatch_for(anomaly_id: int) -> TaskDispatch:
        """
        Construye, sin guardarla, la intención de encolar el aviso de una
        anomalía crítica recién abierta.

        Los dos llamantes (la ingesta de heartbeats y el detector de
        presencia) la guardan en la misma transacción que abre la anomalía,
        porque la anomalía abierta es el propio guardia anti-duplicado
        (``get_active(asset_id, "host_down") is None``, o ``open_kinds`` en la
        evaluación de umbrales). Cuando se confirmaba sola y el
        encolado fallaba después, el correo no se retrasaba: la pasada
        siguiente veía la anomalía ya abierta y no volvía a avisar nunca.

        Args:
            anomaly_id: Primary key de la ``Anomaly`` con severidad
                ``critical`` recién abierta.

        Returns:
            TaskDispatch: Fila de outbox sin persistir, para el job
                ``HygeiaNotify-{anomaly_id}`` de la categoría ``hygeia.notify``.
        """
        return build_dispatch(
            HygeiaNotifyManager.execute_notify_critical_anomaly,
            name=f"HygeiaNotify-{anomaly_id}",
            category=HygeiaNotifyManager.TASK_CATEGORY,
            args=(anomaly_id,),
            external_id=f"{HygeiaNotifyManager.EXTERNAL_ID_PREFIX}{anomaly_id}",
        )

    @staticmethod
    def execute_notify_critical_anomaly(anomaly_id: int) -> None:
        """Entry point submitted to the TaskQueue for background email sending."""
        with job_context():
            HygeiaNotifyManager._run_notify(anomaly_id)

    @staticmethod
    def _run_notify(anomaly_id: int) -> None:
        """
        Envía el correo de aviso al dueño del activo afectado.

        Un fallo de envío se registra y se descarta — no hay nada que
        reintentar de forma síncrona aquí, y la anomalía ya quedó
        registrada y visible en ``GET /hygeia/alerts`` con independencia de
        si el correo llegó o no.
        """
        from src.modules.users.managers import UserManager

        anomaly_repo = build_repository(AnomalyRepository)
        anomaly = anomaly_repo.get_by_id(anomaly_id)
        if anomaly is None:
            logger.error(f"Anomalía {anomaly_id} no encontrada para notificar")
            return

        asset_repo = build_repository(MonitoredAssetRepository)
        asset = asset_repo.get_by_id(anomaly.asset_id)
        if asset is None:
            logger.error(f"Activo {anomaly.asset_id} no encontrado para notificar anomalía {anomaly_id}")
            return

        user = UserManager().get_user_by_id(asset.user_id)
        if user is None:
            logger.error(f"Usuario {asset.user_id} no encontrado para notificar anomalía {anomaly_id}")
            return

        html_body, text_body = render_email(
            "anomaly",
            hostname=asset.hostname,
            kind=anomaly.kind,
            metric=anomaly.metric,
            value=anomaly.value,
            threshold=anomaly.threshold,
            recipient_name=user.first_name,
        )
        message = EmailMessage(
            to=user.email,
            to_name=user.first_name,
            subject=f"[Hygeia] Anomalía crítica en {asset.hostname}",
            html_body=html_body,
            text_body=text_body,
        )
        try:
            build_mailer("hygeia").send(message)
            logger.info(f"Notificación enviada para anomalía {anomaly_id} ({asset.hostname})")
        except Exception as exc:
            logger.error(f"Fallo enviando notificación de anomalía {anomaly_id}: {exc}")

