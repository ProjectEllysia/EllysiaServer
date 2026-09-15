"""
Tests de integración de las consultas multi-activo de ``AssetSnapshotRepository``.

Son la base de las estadísticas por etiqueta y del parque: una sola consulta
SQL para una lista de activos, en vez de una por activo. Por eso, además del
resultado, se cuenta cuántas sentencias llegan a la base de datos.

Los instantes parten de un inicio de hora, así que los cubos de 10 minutos
empiezan justo en ``_T0``, ``_T0 + 10 min``…
"""

import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.infrastructure.engine import get_session

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 9, 1, 0, 0, 0)
_BUCKET_SECONDS = 600
_WINDOW = (_T0, _T0 + timedelta(hours=1))


def _create_asset(user_id: int, hostname: str) -> int:
    """Da de alta un activo mínimo del usuario y devuelve su id."""
    with UnitOfWork() as uow:
        asset = MonitoredAsset(
            hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
            heartbeat_interval_sec=15, status="online", user_id=user_id,
        )
        MonitoredAssetRepository(uow).save(asset)
        return asset.id


def _seed(asset_id: int, readings: list) -> None:
    """Guarda un heartbeat por cada ``(minutos desde _T0, cpu_pct)``."""
    with UnitOfWork() as uow:
        repo = AssetSnapshotRepository(uow)
        for minutes, cpu_pct in readings:
            instant = _T0 + timedelta(minutes=minutes)
            repo.save(AssetSnapshot(
                asset_id=asset_id, collected_at=instant, received_at=instant,
                metrics={}, cpu_pct=cpu_pct,
            ))


@contextmanager
def _recorded_statements():
    """Recoge las sentencias SQL que llegan al engine mientras dura el bloque."""
    statements = []
    engine = get_session().get_bind()

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.fixture()
def two_assets(app, regular_user):
    """Dos activos con lecturas conocidas y un tercero ajeno a la consulta.

    - A: 10 y 30 en el primer cubo (dos heartbeats en el mismo cubo), 50 en
      el segundo y un heartbeat sin dato de CPU.
    - B: 70 en el primer cubo.
    - Ajeno: 99 en el primer cubo; no se pide y no puede aparecer.
    """
    with app.app_context():
        asset_a = _create_asset(regular_user.id, "asset-a")
        asset_b = _create_asset(regular_user.id, "asset-b")
        outsider = _create_asset(regular_user.id, "outsider")
        _seed(asset_a, [(1, 10.0), (5, 30.0), (12, 50.0), (13, None)])
        _seed(asset_b, [(2, 70.0)])
        _seed(outsider, [(3, 99.0)])
        yield asset_a, asset_b


def test_samples_by_asset_skip_missing_values_and_other_assets(app, two_assets):
    """Muestras crudas por activo: sin la lectura vacía y sin el activo no pedido."""
    asset_a, asset_b = two_assets
    with app.app_context():
        samples = build_repository(AssetSnapshotRepository).get_metric_samples_by_asset(
            [asset_a, asset_b], AssetSnapshot.cpu_pct, *_WINDOW,
        )

    assert set(samples) == {asset_a, asset_b}
    assert [value for _, value in samples[asset_a]] == [10.0, 30.0, 50.0]
    assert samples[asset_b] == [(_T0 + timedelta(minutes=2), 70.0)]


@pytest.mark.parametrize("within_bucket, first_bucket_value", [("max", 30.0), ("avg", 20.0), ("min", 10.0)])
def test_bucketed_by_asset_aggregates_inside_each_bucket(app, two_assets, within_bucket, first_bucket_value):
    """Cada activo tiene su serie por cubos, resumida con la agregación pedida."""
    asset_a, asset_b = two_assets
    with app.app_context():
        series = build_repository(AssetSnapshotRepository).get_bucketed_metric_by_asset(
            [asset_a, asset_b], AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW,
            within_bucket=within_bucket,
        )

    assert series[asset_a] == [
        (_T0, pytest.approx(first_bucket_value)),
        (_T0 + timedelta(minutes=10), 50.0),
    ]
    assert series[asset_b] == [(_T0, 70.0)]


def test_across_assets_does_not_count_an_asset_twice_within_a_bucket(app, two_assets):
    """La suma del primer cubo es 30 + 70: A cuenta una vez aunque mandara dos heartbeats."""
    asset_a, asset_b = two_assets
    with app.app_context():
        series = build_repository(AssetSnapshotRepository).get_bucketed_metric_across_assets(
            [asset_a, asset_b], AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW,
            within_bucket="max", across_assets="sum",
        )

    assert series == [
        (_T0, 100.0, 2),
        (_T0 + timedelta(minutes=10), 50.0, 1),
    ]


@pytest.mark.parametrize("across_assets, first_bucket_value", [("avg", 50.0), ("max", 70.0)])
def test_across_assets_supports_average_and_maximum(app, two_assets, across_assets, first_bucket_value):
    """Media y máximo entre activos sobre los valores ya resumidos por cubo."""
    asset_a, asset_b = two_assets
    with app.app_context():
        series = build_repository(AssetSnapshotRepository).get_bucketed_metric_across_assets(
            [asset_a, asset_b], AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW,
            across_assets=across_assets,
        )

    assert series[0] == (_T0, pytest.approx(first_bucket_value), 2)


def test_twenty_assets_are_one_query_per_method(app, regular_user):
    """Veinte activos se resuelven en una sentencia SQL por consulta, no en veinte."""
    with app.app_context():
        asset_ids = [_create_asset(regular_user.id, f"fleet-{i}") for i in range(20)]
        for position, asset_id in enumerate(asset_ids):
            _seed(asset_id, [(1, float(position)), (11, float(position) + 1)])

        repo = build_repository(AssetSnapshotRepository)
        calls = {
            "samples": lambda: repo.get_metric_samples_by_asset(
                asset_ids, AssetSnapshot.cpu_pct, *_WINDOW),
            "by_asset": lambda: repo.get_bucketed_metric_by_asset(
                asset_ids, AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW),
            "across_assets": lambda: repo.get_bucketed_metric_across_assets(
                asset_ids, AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW),
        }
        for method_name, call in calls.items():
            with _recorded_statements() as statements:
                result = call()
            snapshot_queries = [s for s in statements if "AssetSnapshot" in s]
            assert len(snapshot_queries) == 1, f"{method_name}: {len(snapshot_queries)} consultas"
            assert result

        across = repo.get_bucketed_metric_across_assets(
            asset_ids, AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW)
    assert across[0] == (_T0, float(sum(range(20))), 20)


def test_an_empty_asset_list_returns_nothing_without_querying(app):
    """Sin activos no se consulta: un ``IN ()`` vacío nunca llega a la base de datos."""
    with app.app_context():
        repo = build_repository(AssetSnapshotRepository)
        with _recorded_statements() as statements:
            assert repo.get_metric_samples_by_asset([], AssetSnapshot.cpu_pct, *_WINDOW) == {}
            assert repo.get_bucketed_metric_by_asset(
                [], AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW) == {}
            assert repo.get_bucketed_metric_across_assets(
                [], AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW) == []

    assert statements == []


def test_a_bucket_too_fine_for_the_window_is_rejected_instead_of_truncated(app):
    """Treinta días en cubos de un segundo no se recortan en silencio: lanza."""
    with app.app_context():
        repo = build_repository(AssetSnapshotRepository)
        with pytest.raises(ValueError):
            repo.get_bucketed_metric_across_assets(
                [1], AssetSnapshot.cpu_pct, 1, _T0, _T0 + timedelta(days=30))


def test_an_unknown_aggregation_is_rejected(app):
    """Una agregación que no está en la tabla lanza en vez de caer en otra por defecto."""
    with app.app_context():
        repo = build_repository(AssetSnapshotRepository)
        with pytest.raises(ValueError):
            repo.get_bucketed_metric_by_asset(
                [1], AssetSnapshot.cpu_pct, _BUCKET_SECONDS, *_WINDOW, within_bucket="sum")
