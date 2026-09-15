"""
Tests de integración HTTP del resumen estadístico de un activo
(``GET /hygeia/assets/<id>/stats/summary``).

Siembra snapshots directamente por repositorio, igual que
``test_hygeia_power_summary.py``: el suelo de cadencia de la ingesta impide
construir por HTTP una serie con valores e instantes elegidos.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int) -> int:
    """Da de alta un activo mínimo del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname="stats-test", agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, status="online", last_seen_at=utcnow_naive(),
                user_id=user_id,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _seed(app, asset_id: int, readings: list) -> None:
    """Guarda un snapshot por cada ``(antigüedad, columnas)``."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            now = utcnow_naive()
            for age, columns in readings:
                instant = now - age
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant,
                    metrics={}, **columns,
                ))


def _summary(client, asset_id: int, headers: dict, **query) -> tuple:
    """Pide el resumen y devuelve ``(status, cuerpo)``."""
    response = client.get(f"/hygeia/assets/{asset_id}/stats/summary", query_string=query, headers=headers)
    return response.status_code, response.get_json()


@pytest.fixture()
def seeded_asset(app, regular_user):
    """Un activo con cuatro heartbeats en la última hora y uno de hace dos días."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [
        (timedelta(minutes=40), {"cpu_pct": 10.0, "mem_pct": 60.0, "disk_max_pct": 70.0}),
        (timedelta(minutes=30), {"cpu_pct": 50.0, "mem_pct": 62.0, "disk_max_pct": 70.0}),
        (timedelta(minutes=20), {"cpu_pct": 30.0, "mem_pct": 64.0, "disk_max_pct": 71.0}),
        (timedelta(minutes=10), {"cpu_pct": 20.0, "mem_pct": 66.0, "disk_max_pct": 72.0}),
        (timedelta(days=2), {"cpu_pct": 99.0, "mem_pct": 99.0, "disk_max_pct": 99.0}),
    ])
    return asset_id


def test_three_metrics_in_one_call(client, seeded_asset, regular_user, auth_headers):
    """Tres métricas en una llamada, con sus agregados sobre las últimas 24 h."""
    status, body = _summary(
        client, seeded_asset, auth_headers(regular_user),
        metrics="cpuPct,memPct,diskMaxPct", period="24h",
    )

    assert status == 200
    assert set(body["metrics"]) == {"cpuPct", "memPct", "diskMaxPct"}
    cpu = body["metrics"]["cpuPct"]
    assert cpu["min"] == 10.0
    assert cpu["max"] == 50.0
    assert cpu["avg"] == pytest.approx(27.5)
    assert cpu["p95"] == pytest.approx(47.0)
    assert cpu["current"] == 20.0
    assert cpu["sampleCount"] == 4
    assert body["metrics"]["memPct"]["avg"] == pytest.approx(63.0)
    assert body["metrics"]["diskMaxPct"]["max"] == 72.0
    assert body["isPeriodClipped"] is False


def test_a_longer_period_reaches_older_snapshots(client, seeded_asset, regular_user, auth_headers):
    """Con 7 días entra el heartbeat de hace dos días, que 24 h dejaba fuera."""
    status, body = _summary(
        client, seeded_asset, auth_headers(regular_user), metrics="cpuPct", period="7d",
    )

    assert status == 200
    assert body["metrics"]["cpuPct"]["max"] == 99.0
    assert body["metrics"]["cpuPct"]["sampleCount"] == 5


def test_without_metrics_every_registered_metric_is_summarized(
    client, seeded_asset, regular_user, auth_headers,
):
    """Sin ``metrics`` salen las ocho; las que el activo no reporta, vacías y no a cero."""
    status, body = _summary(client, seeded_asset, auth_headers(regular_user))

    assert status == 200
    assert set(body["metrics"]) == {
        "cpuPct", "memPct", "swapPct", "load1", "diskMaxPct", "netRxBps", "netTxBps", "powerWatts",
    }
    power = body["metrics"]["powerWatts"]
    assert power["sampleCount"] == 0
    assert power["max"] is None
    assert power["avg"] is None


def test_a_period_beyond_retention_is_clipped_and_says_so(
    client, seeded_asset, regular_user, auth_headers,
):
    """365 días con 30 de retención: se cubren 30 y la respuesta lo declara."""
    status, body = _summary(
        client, seeded_asset, auth_headers(regular_user), metrics="cpuPct", period="365d",
    )

    assert status == 200
    assert body["isPeriodClipped"] is True
    covered_from = datetime.fromisoformat(body["periodCoveredFrom"].rstrip("Z"))
    covered_to = datetime.fromisoformat(body["periodCoveredTo"].rstrip("Z"))
    assert covered_to - covered_from == timedelta(days=30)


def test_an_unknown_metric_is_a_400_with_the_valid_catalogue(
    client, seeded_asset, regular_user, auth_headers,
):
    """Un nombre fuera del registro da 400 y el catálogo de métricas válidas."""
    status, body = _summary(
        client, seeded_asset, auth_headers(regular_user), metrics="cpuPct,cpu_pct",
    )

    assert status == 400
    assert body["error"] == "UnknownMetricError"
    assert body["details"]["metric"] == "cpu_pct"
    assert "cpuPct" in body["details"]["valid_metrics"]


@pytest.mark.parametrize("period", ["abc", "0d", "7w", "-1h"])
def test_a_malformed_period_is_rejected(client, seeded_asset, regular_user, auth_headers, period):
    """``period`` tiene que ser ``<n>h`` o ``<n>d`` con ``n`` positivo."""
    status, _ = _summary(client, seeded_asset, auth_headers(regular_user), period=period)

    assert status == 422


def test_another_users_asset_is_not_found(client, seeded_asset, make_user, auth_headers):
    """El activo de otro usuario da el mismo 404 que uno inexistente."""
    stranger = make_user()

    status, _ = _summary(client, seeded_asset, auth_headers(stranger), metrics="cpuPct")

    assert status == 404


# =============================================================================
# MOMENTO DEL PICO
# =============================================================================

def _parse_utc(text: str) -> datetime:
    """Convierte un instante ISO de la API (``Z`` o ``+00:00``) en naive-UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def test_the_extremes_carry_the_exact_instant_of_their_heartbeat(
    client, app, regular_user, auth_headers,
):
    """``timestampOfMax``/``Min`` son el instante exacto del heartbeat, no el de un cubo."""
    asset_id = _create_asset(app, regular_user.id)
    base = utcnow_naive().replace(microsecond=0) - timedelta(hours=1)
    peak_at = base + timedelta(minutes=17, seconds=23)
    valley_at = base + timedelta(minutes=41, seconds=7)
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            for instant, cpu in [
                (base, 40.0), (peak_at, 97.5), (valley_at, 3.0), (base + timedelta(minutes=50), 40.0),
            ]:
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant,
                    metrics={}, cpu_pct=cpu,
                ))

    status, body = _summary(
        client, asset_id, auth_headers(regular_user), metrics="cpuPct,powerWatts",
    )

    assert status == 200
    cpu = body["metrics"]["cpuPct"]
    assert _parse_utc(cpu["timestampOfMax"]) == peak_at
    assert _parse_utc(cpu["timestampOfMin"]) == valley_at


def test_a_metric_without_samples_has_no_extreme_instants(
    client, seeded_asset, regular_user, auth_headers,
):
    """Sin muestras no hay pico: los dos instantes son ``null``, como los valores."""
    status, body = _summary(client, seeded_asset, auth_headers(regular_user), metrics="powerWatts")

    assert status == 200
    power = body["metrics"]["powerWatts"]
    assert power["timestampOfMax"] is None
    assert power["timestampOfMin"] is None
