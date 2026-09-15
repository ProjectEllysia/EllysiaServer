"""
Helpers internos del módulo Hygeia.

La mayoría son funciones puras sin conocimiento de Flask ni de
repositorios. Las excepciones son los decoradores de autenticación/guarda
de request (``require_agent_key``, ``enforce_ingest_limits``), que sí
necesitan tocar ``flask.request`` — mismo precedente que
``users/services/permissions.py`` con ``require_oauth_token``.
"""

from .aggregation import denormalize
from .agent_freshness import is_agent_outdated
from .detection import AnomalyChange, DetectionOutcome, evaluate
from .enrollment import agent_key_id_from_request, generate_agent_key, require_agent_key
from .ingest_guard import (
    check_clock_skew,
    decompress_gzip_capped,
    enforce_body_size,
    enforce_ingest_limits,
)
from .inventory_adapter import services_from_inventory
from .metric_registry import METRIC_REGISTRY, MetricDefinition, assert_metric_definition
from .reports import build_inventory_report
from .stats import (
    EnergyCost,
    PeriodClassification,
    PowerAverage,
    StatSummary,
    StatsWindow,
    calculate_percentile,
    classify_period,
    energy_and_cost,
    project_month,
    resolve_stats_window,
    summarize_power_period,
    summarize_series_by_asset,
    summarize_values,
    weighted_average_with_observed_time,
)

__all__ = [
    "services_from_inventory",
    "build_inventory_report",
    "agent_key_id_from_request",
    "generate_agent_key",
    "require_agent_key",
    "check_clock_skew",
    "decompress_gzip_capped",
    "enforce_body_size",
    "enforce_ingest_limits",
    "evaluate",
    "AnomalyChange",
    "DetectionOutcome",
    "denormalize",
    "is_agent_outdated",
    "PowerAverage",
    "EnergyCost",
    "PeriodClassification",
    "weighted_average_with_observed_time",
    "energy_and_cost",
    "classify_period",
    "summarize_power_period",
    "project_month",
    "StatSummary",
    "calculate_percentile",
    "summarize_values",
    "summarize_series_by_asset",
    "StatsWindow",
    "resolve_stats_window",
    "METRIC_REGISTRY",
    "MetricDefinition",
    "assert_metric_definition",
]
