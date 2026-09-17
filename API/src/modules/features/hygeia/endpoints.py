"""
Endpoints del módulo Hygeia.

Este fichero solo hace autenticación y validación de schema: toda la lógica
vive en ``managers.py``, y el acceso a datos, únicamente vía ``UnitOfWork`` +
repositorio (regla del repo).

Dos superficies separadas:
    - Usuario (``@require_oauth_token``): alta, listado, detalle, baja y
      rotación de clave de los activos monitorizados, más el catálogo de
      etiquetas con el que se agrupan.
    - Agente (``@require_agent_key``): la ruta caliente de ingesta de
      heartbeats (``POST /hygeia/ingest``).
"""

import logging

from flask import request, send_file
from flask_smorest import Blueprint as SmorestBlueprint

from src.modules.shared import handle_exceptions, limiter, current_actor
from src.modules.shared._exceptions import DocumentError
from src.modules.shared.schemas import ErrorSchema
from src.modules.users import (
    require_oauth_token, require_attributes, AttributeType, get_current_user,
)

from .exceptions import (
    AnomalyNotFoundError,
    AssetNotFoundError,
    HygeiaError,
    TagNotFoundError,
)
from .managers import (
    HygeiaAlertManager, HygeiaAssetManager, HygeiaDocumentManager, HygeiaIngestManager,
    HygeiaStatsManager, HygeiaTagManager,
)
from .schemas import (
    AnalyzeInventoryResponseSchema,
    DocumentCreateRequestSchema,
    DocumentListResponseSchema,
    DocumentSchema,
    DocumentsQuerySchema,
    AnomalyListResponseSchema,
    AnomalyQuerySchema,
    AnomalySchema,
    AssetCreateRequestSchema,
    AssetCreatedResponseSchema,
    AssetInventoryResponseSchema,
    AssetLatestResponseSchema,
    AssetListResponseSchema,
    AssetMetricsQuerySchema,
    AssetMetricsResponseSchema,
    AssetRankingQuerySchema,
    AssetRankingResponseSchema,
    AssetSchema,
    AssetStatsSummaryQuerySchema,
    AssetStatsSummaryResponseSchema,
    AssetTagsRequestSchema,
    AssetUpdateRequestSchema,
    BreachRankingQuerySchema,
    BreachRankingResponseSchema,
    CpuCoreStatsQuerySchema,
    CpuCoreStatsResponseSchema,
    DiskStatsQuerySchema,
    DiskStatsResponseSchema,
    DiskTrendQuerySchema,
    DiskTrendResponseSchema,
    FleetDiskQuerySchema,
    FleetDiskResponseSchema,
    FleetOverviewResponseSchema,
    HourlyPatternQuerySchema,
    HourlyPatternResponseSchema,
    IngestRequestSchema,
    IngestResponseSchema,
    InventoryAnalysisSummarySchema,
    MetricHistogramQuerySchema,
    MetricHistogramResponseSchema,
    MetricSeriesQuerySchema,
    MetricSeriesResponseSchema,
    NetworkStatsQuerySchema,
    NetworkStatsResponseSchema,
    PowerStatsQuerySchema,
    PowerStatsResponseSchema,
    PowerSummaryResponseSchema,
    RotateKeyResponseSchema,
    TagCreateRequestSchema,
    TagListResponseSchema,
    TagSchema,
    TagRankingQuerySchema,
    TagRankingResponseSchema,
    TagStatsQuerySchema,
    TagStatsResponseSchema,
)
from .services import agent_key_id_from_request, enforce_ingest_limits, require_agent_key

hygeia_blp = SmorestBlueprint(
    "hygeia", __name__,
    description="Monitorización de activos: ingesta de telemetría, "
                "detección de anomalías y alertado (Hygeia)",
)
logger = logging.getLogger(__name__)


@hygeia_blp.post("/assets")
@hygeia_blp.arguments(AssetCreateRequestSchema)
@hygeia_blp.response(
    201, AssetCreatedResponseSchema, description="Asset created — agent key shown once",
)
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(409, schema=ErrorSchema, description="Asset quota exceeded")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_CREATE])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def create_asset(data):
    """Dar de alta un activo a monitorizar y emitir su clave de agente"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    result = manager.create_asset(
        hostname=data["hostname"],
        os_name=data["os"],
        labels=data["labels"],
        is_persistent=data["isPersistent"],
    )
    logger.info(f"Activo Hygeia creado | user={current_actor()} hostname={data['hostname']}")
    return result


@hygeia_blp.get("/assets")
@hygeia_blp.response(200, AssetListResponseSchema, description="Assets del usuario")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def list_assets():
    """Listar los activos monitorizados del usuario con su estado de presencia"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return {"assets": manager.list_assets()}


@hygeia_blp.get("/assets/<int:asset_id>")
@hygeia_blp.response(200, AssetSchema, description="Detalle del activo")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset(asset_id):
    """Obtener el detalle de un activo monitorizado"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_asset(asset_id)


@hygeia_blp.get("/assets/<int:asset_id>/metrics")
@hygeia_blp.arguments(AssetMetricsQuerySchema, location="query")
@hygeia_blp.response(200, AssetMetricsResponseSchema, description="Serie temporal de métricas del activo")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_metrics(args, asset_id):
    """Obtener la serie temporal de métricas escalares de un activo, para el gráfico de la SPA"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_metrics(
        asset_id, since=args["since"], until=args["until"], bucket=args["bucket"],
        aggregation=args["agg"],
    )


@hygeia_blp.get("/assets/<int:asset_id>/metrics/latest")
@hygeia_blp.response(200, AssetLatestResponseSchema, description="Últimas métricas completas del activo")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_latest_metrics(asset_id):
    """Obtener el último heartbeat completo de un activo (disco, red, procesos y núcleos)"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_latest_metrics(asset_id)


@hygeia_blp.get("/assets/<int:asset_id>/power-summary")
@hygeia_blp.response(200, PowerSummaryResponseSchema, description="Resumen de consumo eléctrico del activo")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_power_summary(asset_id):
    """Obtener el resumen de consumo eléctrico de un activo: lectura actual, energía y coste"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_power_summary(asset_id)


@hygeia_blp.get("/assets/<int:asset_id>/stats/summary")
@hygeia_blp.arguments(AssetStatsSummaryQuerySchema, location="query")
@hygeia_blp.response(
    200, AssetStatsSummaryResponseSchema, description="Resumen estadístico del activo",
)
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_stats_summary(args, asset_id):
    """Obtener mínimo, máximo, media, p95 y valor actual de las métricas de un activo"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_stats_summary(
        asset_id,
        metric_names=args["metric_names"],
        requested_duration=args["requested_duration"],
        is_refresh=args["refresh"],
    )


@hygeia_blp.get("/assets/<int:asset_id>/stats/disks")
@hygeia_blp.arguments(DiskStatsQuerySchema, location="query")
@hygeia_blp.response(200, DiskStatsResponseSchema, description="Uso por punto de montaje")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_disk_stats(args, asset_id):
    """Obtener el resumen de uso de cada punto de montaje de un activo"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_disk_stats(
        asset_id, mount=args["mount"], requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/assets/<int:asset_id>/stats/disk-trend")
@hygeia_blp.arguments(DiskTrendQuerySchema, location="query")
@hygeia_blp.response(200, DiskTrendResponseSchema, description="Tendencia de uso de disco")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_disk_trend(args, asset_id):
    """Obtener la tendencia de uso de disco de un activo y cuándo se llenaría"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_disk_trend(
        asset_id, mount=args["mount"], requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/assets/<int:asset_id>/stats/network")
@hygeia_blp.arguments(NetworkStatsQuerySchema, location="query")
@hygeia_blp.response(200, NetworkStatsResponseSchema, description="Tráfico por interfaz")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_network_stats(args, asset_id):
    """Obtener el resumen de tráfico de cada interfaz de red de un activo"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_network_stats(
        asset_id, interface=args["interface"], requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/assets/<int:asset_id>/stats/cpu-cores")
@hygeia_blp.arguments(CpuCoreStatsQuerySchema, location="query")
@hygeia_blp.response(200, CpuCoreStatsResponseSchema, description="Desequilibrio entre núcleos")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_cpu_core_stats(args, asset_id):
    """Obtener el desequilibrio de carga entre los núcleos de CPU de un activo"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_cpu_core_stats(asset_id, requested_duration=args["requested_duration"])


@hygeia_blp.get("/stats/by-tag/<int:tag_id>")
@hygeia_blp.arguments(TagStatsQuerySchema, location="query")
@hygeia_blp.response(200, TagStatsResponseSchema, description="Estadísticas de una etiqueta")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown or non-additive metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Tag not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=TagNotFoundError, logger=logger)
def get_tag_stats(args, tag_id):
    """Obtener las métricas agregadas de los activos que llevan una etiqueta"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_tag_stats(
        tag_id,
        metric_names=args["metric_names"],
        aggregation=args["agg"],
        requested_duration=args["requested_duration"],
        is_refresh=args["refresh"],
    )


@hygeia_blp.get("/stats/by-tag")
@hygeia_blp.arguments(TagRankingQuerySchema, location="query")
@hygeia_blp.response(200, TagRankingResponseSchema, description="Ranking de etiquetas")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown or non-additive metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_tag_ranking(args):
    """Ordenar las etiquetas del usuario por una métrica agregada de sus activos"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_tag_ranking(
        metric_name=args["metric"],
        aggregation=args["agg"],
        requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/stats/ranking")
@hygeia_blp.arguments(AssetRankingQuerySchema, location="query")
@hygeia_blp.response(200, AssetRankingResponseSchema, description="Ranking de activos")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_asset_ranking(args):
    """Ordenar los activos del usuario por una métrica y devolver los extremos"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_asset_ranking(
        metric_name=args["metric"],
        aggregation=args["agg"],
        order=args["order"],
        limit=args["limit"],
        requested_duration=args["requested_duration"],
        is_refresh=args["refresh"],
    )


@hygeia_blp.get("/stats/disks/fleet")
@hygeia_blp.arguments(FleetDiskQuerySchema, location="query")
@hygeia_blp.response(200, FleetDiskResponseSchema, description="Montajes más llenos del parque")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_fleet_fullest_mounts(args):
    """Listar los activos del usuario con el montaje más lleno según su último latido"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_fullest_mounts(limit=args["limit"])


@hygeia_blp.get("/stats/breach-ranking")
@hygeia_blp.arguments(BreachRankingQuerySchema, location="query")
@hygeia_blp.response(
    200, BreachRankingResponseSchema, description="Ranking de incumplimientos de umbral",
)
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_breach_ranking(args):
    """Ordenar los activos del usuario por cuántas veces cruzaron sus umbrales"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_breach_ranking(
        limit=args["limit"], requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/stats/overview")
@hygeia_blp.response(200, FleetOverviewResponseSchema, description="Panorama del parque")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_fleet_overview():
    """Resumir el estado actual del parque: activos por estado, anomalías y actividad"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_fleet_overview()


@hygeia_blp.get("/stats/histogram")
@hygeia_blp.arguments(MetricHistogramQuerySchema, location="query")
@hygeia_blp.response(200, MetricHistogramResponseSchema, description="Histograma de una métrica")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_metric_histogram(args):
    """Repartir los activos del usuario en franjas según una métrica"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_metric_histogram(
        metric_name=args["metric"],
        aggregation=args["agg"],
        bin_count=args["bins"],
        requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/stats/power")
@hygeia_blp.arguments(PowerStatsQuerySchema, location="query")
@hygeia_blp.response(200, PowerStatsResponseSchema, description="Consumo eléctrico agregado")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Tag not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_power_stats(args):
    """Obtener la energía y el coste agregados de todo el parque o de una etiqueta"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_power_stats(
        scope=args["scope"],
        tag_id=args["tagId"],
        requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/stats/hourly-pattern")
@hygeia_blp.arguments(HourlyPatternQuerySchema, location="query")
@hygeia_blp.response(200, HourlyPatternResponseSchema, description="Patrón horario de carga")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Tag or asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_hourly_pattern(args):
    """Repartir una métrica por hora del día sobre un activo, una etiqueta o el parque"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_hourly_pattern(
        args["metric"],
        scope=args["scope"],
        tag_id=args["tagId"],
        asset_id=args["assetId"],
        aggregation=args["agg"],
        requested_duration=args["requested_duration"],
    )


@hygeia_blp.get("/stats/series")
@hygeia_blp.arguments(MetricSeriesQuerySchema, location="query")
@hygeia_blp.response(200, MetricSeriesResponseSchema, description="Serie temporal multi-activo")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown or non-additive metric")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Tag or asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def get_metric_series(args):
    """Obtener la serie temporal de una métrica sobre los activos de una etiqueta o de una lista"""
    user = get_current_user()
    manager = HygeiaStatsManager(user)
    return manager.get_metric_series(
        args["metric"],
        tag_id=args["tagId"],
        asset_ids=args["asset_ids"],
        aggregation=args["agg"],
        bucket_aggregation=args["bucketAgg"],
        requested_bucket_seconds=args["bucket"],
        requested_duration=args["requested_duration"],
        compare_to=args["compare_to"],
        is_refresh=args["refresh"],
    )


@hygeia_blp.get("/assets/<int:asset_id>/inventory")
@hygeia_blp.response(200, AssetInventoryResponseSchema, description="Último inventario de software del activo")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_inventory(asset_id):
    """Obtener el último inventario de software conocido de un activo"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_inventory(asset_id)


@hygeia_blp.post("/assets/<int:asset_id>/analyze")
@hygeia_blp.response(202, AnalyzeInventoryResponseSchema, description="Análisis de inventario encolado")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@hygeia_blp.alt_response(409, schema=ErrorSchema, description="Asset has no inventory to analyse")
@limiter.limit("20 per hour; 100 per day")
@require_oauth_token
# Exige AMBOS atributos a propósito: la acción vive en Hygeia pero lo que crea
# es un escaneo de Themis, así que quien no puede lanzar escaneos allí tampoco
# debe poder lanzarlos por esta puerta.
@require_attributes(all_required=[AttributeType.HYGEIA_UPDATE, AttributeType.THEMIS_CREATE])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def analyze_asset_inventory(asset_id):
    """Analizar el inventario de software de un activo con el motor Lybra"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    result = manager.analyze_inventory(asset_id)
    logger.info(f"Análisis de inventario del activo {asset_id} lanzado por {user.username}")
    return result


@hygeia_blp.get("/assets/<int:asset_id>/analysis")
@hygeia_blp.response(200, InventoryAnalysisSummarySchema, description="Resumen del último análisis de inventario")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def get_asset_analysis(asset_id):
    """Obtener el resumen del último análisis de inventario de un activo"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    return manager.get_analysis_summary(asset_id)


@hygeia_blp.patch("/assets/<int:asset_id>")
@hygeia_blp.arguments(AssetUpdateRequestSchema)
@hygeia_blp.response(200, AssetSchema, description="Activo actualizado")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_UPDATE])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def update_asset(data, asset_id):
    """Marcar si un activo debería estar siempre encendido o se apaga a propósito"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    result = manager.set_persistence(asset_id, data["isPersistent"])
    logger.info(
        f"Persistencia del activo {asset_id} = {data['isPersistent']} | user={current_actor()}"
    )
    return result


@hygeia_blp.delete("/assets/<int:asset_id>")
@hygeia_blp.response(200, description="Asset eliminado")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_DELETE])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def delete_asset(asset_id):
    """Dar de baja un activo monitorizado, revocando su clave de agente"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    manager.delete_asset(asset_id)
    logger.info(f"Activo Hygeia {asset_id} eliminado | user={current_actor()}")


# =============================================================================
# ETIQUETAS — catálogo común + repositorio personal, y su asignación a activos.
#
# No estrenan atributos propios: una etiqueta es una propiedad de los activos
# de Hygeia, no un recurso aparte, así que reutilizan los HYGEIA_* que ya
# gobiernan el módulo.
# =============================================================================


@hygeia_blp.get("/tags")
@hygeia_blp.response(200, TagListResponseSchema, description="Etiquetas visibles para el usuario")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def list_tags():
    """Listar el catálogo de etiquetas del usuario con el recuento de activos de cada una"""
    user = get_current_user()
    manager = HygeiaTagManager(user)
    return {"tags": manager.list_tags()}


@hygeia_blp.post("/tags")
@hygeia_blp.arguments(TagCreateRequestSchema)
@hygeia_blp.response(201, TagSchema, description="Etiqueta personal creada")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(409, schema=ErrorSchema, description="Tag name taken or quota exceeded")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_CREATE])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def create_tag(data):
    """Añadir una etiqueta al repositorio personal del usuario"""
    user = get_current_user()
    manager = HygeiaTagManager(user)
    result = manager.create_tag(name=data["name"], color=data["color"])
    logger.info(f"Etiqueta Hygeia creada | user={current_actor()} name={data['name']}")
    return result


@hygeia_blp.delete("/tags/<int:tag_id>")
@hygeia_blp.response(200, description="Etiqueta eliminada")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="System tags cannot be deleted")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Tag not found")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_DELETE])
@handle_exceptions(default_exception=TagNotFoundError, logger=logger)
def delete_tag(tag_id):
    """Borrar una etiqueta personal, quitándola de todos los activos que la llevaran"""
    user = get_current_user()
    manager = HygeiaTagManager(user)
    manager.delete_tag(tag_id)
    logger.info(f"Etiqueta Hygeia {tag_id} eliminada | user={current_actor()}")


@hygeia_blp.put("/assets/<int:asset_id>/tags")
@hygeia_blp.arguments(AssetTagsRequestSchema)
@hygeia_blp.response(200, AssetSchema, description="Activo con sus etiquetas actualizadas")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset or tag not found")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_UPDATE])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def set_asset_tags(data, asset_id):
    """Fijar el conjunto completo de etiquetas de un activo"""
    user = get_current_user()
    manager = HygeiaTagManager(user)
    result = manager.set_asset_tags(asset_id, data["tagIds"])
    logger.info(
        f"Etiquetas del activo {asset_id} = {data['tagIds']} | user={current_actor()}"
    )
    return result


@hygeia_blp.post("/assets/<int:asset_id>/rotate-key")
@hygeia_blp.response(200, RotateKeyResponseSchema, description="New agent key — shown once")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset not found")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_UPDATE])
@handle_exceptions(default_exception=AssetNotFoundError, logger=logger)
def rotate_key(asset_id):
    """Regenerar la clave de agente de un activo, invalidando la anterior"""
    user = get_current_user()
    manager = HygeiaAssetManager(user)
    result = manager.rotate_key(asset_id)
    logger.info(f"Clave de agente rotada para activo {asset_id} | user={current_actor()}")
    return result


@hygeia_blp.get("/alerts")
@hygeia_blp.arguments(AnomalyQuerySchema, location="query")
@hygeia_blp.response(200, AnomalyListResponseSchema, description="Anomalías de los activos del usuario")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def list_alerts(args):
    """Listar las anomalías de los activos del usuario, con filtros opcionales"""
    user = get_current_user()
    manager = HygeiaAlertManager(user)
    anomalies = manager.list_alerts(
        state=args["state"], severity=args["severity"], asset_id=args["assetId"],
    )
    return {"anomalies": anomalies}


@hygeia_blp.post("/alerts/<int:anomaly_id>/ack")
@hygeia_blp.response(200, AnomalySchema, description="Anomalía reconocida")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Anomaly not found")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_UPDATE])
@handle_exceptions(default_exception=AnomalyNotFoundError, logger=logger)
def ack_alert(anomaly_id):
    """Reconocer una anomalía, sin darla por resuelta"""
    user = get_current_user()
    manager = HygeiaAlertManager(user)
    result = manager.ack_alert(anomaly_id)
    logger.info(f"Anomalía {anomaly_id} reconocida | user={current_actor()}")
    return result


@hygeia_blp.post("/alerts/<int:anomaly_id>/resolve")
@hygeia_blp.response(200, AnomalySchema, description="Anomalía resuelta")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Anomaly not found")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_UPDATE])
@handle_exceptions(default_exception=AnomalyNotFoundError, logger=logger)
def resolve_alert(anomaly_id):
    """Resolver manualmente una anomalía"""
    user = get_current_user()
    manager = HygeiaAlertManager(user)
    result = manager.resolve_alert(anomaly_id)
    logger.info(f"Anomalía {anomaly_id} resuelta manualmente | user={current_actor()}")
    return result


@hygeia_blp.delete("/alerts/<int:anomaly_id>")
@hygeia_blp.response(200, description="Anomalía eliminada")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Anomaly not found")
@hygeia_blp.alt_response(409, schema=ErrorSchema, description="Anomaly still open")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_DELETE])
@handle_exceptions(default_exception=AnomalyNotFoundError, logger=logger)
def delete_alert(anomaly_id):
    """Borrar una anomalía ya reconocida o resuelta"""
    user = get_current_user()
    manager = HygeiaAlertManager(user)
    manager.delete_alert(anomaly_id)
    logger.info(f"Anomalía {anomaly_id} eliminada | user={current_actor()}")
    return {"message": "Anomalía eliminada correctamente"}


# =============================================================================
# DOCUMENTOS — se piden, se generan en segundo plano y se descargan después
# =============================================================================

@hygeia_blp.post("/documents")
@hygeia_blp.arguments(DocumentCreateRequestSchema)
@hygeia_blp.response(202, DocumentSchema, description="Documento en cola")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Unknown or non-additive metric")
@hygeia_blp.alt_response(422, schema=ErrorSchema, description="Invalid or incomplete request")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(
    403, schema=ErrorSchema, description="Organization scope requires ownership",
)
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Asset or tag not found")
# Pedir es barato (una fila y un encolado); lo caro lo hace el worker, y un
# usuario no necesita más de un documento por minuto de media.
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def create_document(data):
    """Pedir un CSV o un PDF de estadísticas, o el PDF del inventario, en segundo plano"""
    manager = HygeiaDocumentManager(get_current_user())
    if data["kind"] == "inventory-pdf":
        document = manager.create_inventory_pdf_document(data["scope"], data["includeSoftware"])
    else:
        create_stats_document = (
            manager.create_stats_pdf_document if data["kind"] == "stats-pdf"
            else manager.create_stats_csv_document
        )
        document = create_stats_document(
            data["dataset"], asset_id=data["assetId"], tag_id=data["tagId"],
            metric_names=data["metrics"], metric_name=data["metric"], aggregation=data["agg"],
            order=data["order"], limit=data["limit"],
            requested_duration=data["requested_duration"], period=data["period"],
        )
    logger.info(
        f"Documento Hygeia {document['id']} pedido ({data['kind']}) | user={current_actor()}"
    )
    return document


@hygeia_blp.get("/documents")
@hygeia_blp.arguments(DocumentsQuerySchema, location="query")
@hygeia_blp.response(200, DocumentListResponseSchema, description="Documentos del usuario")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def list_documents(args):
    """Listar los documentos del usuario, más recientes primero"""
    manager = HygeiaDocumentManager(get_current_user())
    documents, total = manager.list_documents(args["page"], args["perPage"])
    return {
        "documents": documents, "total": total,
        "page": args["page"], "perPage": args["perPage"],
    }


@hygeia_blp.get("/documents/<int:document_id>")
@hygeia_blp.response(200, DocumentSchema, description="Documento")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Document not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=DocumentError, logger=logger)
def get_document(document_id):
    """Consultar un documento y su estado"""
    return HygeiaDocumentManager(get_current_user()).get_document(document_id)


@hygeia_blp.get("/documents/<int:document_id>/download")
@hygeia_blp.response(200, description="Fichero del documento")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Document not found")
@hygeia_blp.alt_response(409, schema=ErrorSchema, description="Document not ready")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_READ])
@handle_exceptions(default_exception=DocumentError, logger=logger)
def download_document(document_id):
    """Descargar el fichero de un documento ya generado"""
    path, download_name, mimetype = HygeiaDocumentManager(get_current_user()).get_document_file(
        document_id,
    )
    return send_file(path, mimetype=mimetype, as_attachment=True, download_name=download_name)


@hygeia_blp.delete("/documents/<int:document_id>")
@hygeia_blp.response(200, description="Documento eliminado")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@hygeia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@hygeia_blp.alt_response(404, schema=ErrorSchema, description="Document not found")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.HYGEIA_DELETE])
@handle_exceptions(default_exception=DocumentError, logger=logger)
def delete_document(document_id):
    """Borrar un documento y su fichero"""
    HygeiaDocumentManager(get_current_user()).delete_user_document(document_id)
    logger.info(f"Documento Hygeia {document_id} eliminado | user={current_actor()}")
    return {"message": "Documento eliminado correctamente", "documentId": document_id}


# ============================================================================
# SUPERFICIE DE AGENTE — autenticada por clave de agente, no por OAuth
# ============================================================================

@hygeia_blp.post("/ingest")
@enforce_ingest_limits
@hygeia_blp.arguments(IngestRequestSchema)
@hygeia_blp.response(200, IngestResponseSchema, description="Heartbeat procesado")
@hygeia_blp.alt_response(401, schema=ErrorSchema, description="Invalid or missing agent key")
@hygeia_blp.alt_response(400, schema=ErrorSchema, description="Validation error or clock skew")
@hygeia_blp.alt_response(413, schema=ErrorSchema, description="Payload too large")
@hygeia_blp.alt_response(429, schema=ErrorSchema, description="Heartbeat too frequent")
@limiter.limit("20 per minute", key_func=agent_key_id_from_request)
@require_agent_key
@handle_exceptions(default_exception=HygeiaError, logger=logger)
def ingest(data):
    """Recibir un heartbeat de un agente Hygeia y actualizar la presencia del activo"""
    # Esta superficie se autentica por clave de agente (@require_agent_key
    # inyecta request.current_asset_id), no por OAuth de usuario — no hay
    # request.current_user_id aquí, así que get_current_user() no aplica.
    manager = HygeiaIngestManager(request.current_asset_id)
    return manager.ingest_heartbeat(data)
