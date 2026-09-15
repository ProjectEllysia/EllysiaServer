"""
Tests de integración HTTP de las estadísticas del parque de un usuario: el
ranking de activos por métrica (``GET /hygeia/stats/ranking``) y el panorama
del estado actual (``GET /hygeia/stats/overview``).

Siembra activos y snapshots directamente por repositorio, igual que el resto
de tests de estadísticas de Hygeia: por HTTP no se puede construir una serie
con valores e instantes elegidos.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from src.modules.features.hygeia.model import Anomaly, AssetSnapshot, MonitoredAsset
from src.modules.features.hygeia.repositories import (
    AnomalyRepository,
    AssetSnapshotRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int, hostname: str, **columns) -> int:
    """Da de alta un activo del usuario y devuelve su id.

    Por defecto está en línea y acaba de reportar; ``columns`` pisa esos
    valores o añade otros (``status``, ``last_seen_at``, ``uptime_sec``…).
    """
    asset_columns = {"status": "online", "last_seen_at": utcnow_naive(), **columns}
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, user_id=user_id, **asset_columns,
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


def _get(client, path: str, headers: dict, **query) -> tuple:
    """Hace un GET con query y devuelve ``(status, cuerpo)``."""
    response = client.get(path, query_string=query, headers=headers)
    return response.status_code, response.get_json()


# =============================================================================
# RANKING DE ACTIVOS
# =============================================================================

@pytest.fixture()
def ten_assets(app, regular_user):
    """Diez activos del usuario con CPU media conocida (10, 20, … 100) y un pico cada uno.

    El activo ``host-NN`` tiene dos lecturas: ``NN − 5`` y ``NN + 5``, así que
    su media es ``NN`` y su máximo ``NN + 5``.
    """
    for position in range(1, 11):
        cpu = float(position * 10)
        asset_id = _create_asset(app, regular_user.id, f"host-{position:02d}")
        _seed(app, asset_id, [
            (timedelta(minutes=20), {"cpu_pct": cpu - 5}),
            (timedelta(minutes=10), {"cpu_pct": cpu + 5}),
        ])


def test_the_top_three_are_the_three_highest_in_order(client, ten_assets, regular_user, auth_headers):
    """``limit=3&order=desc`` devuelve exactamente los tres de mayor media, en orden."""
    status, body = _get(
        client, "/hygeia/stats/ranking", auth_headers(regular_user),
        metric="cpuPct", limit=3, order="desc",
    )

    assert status == 200
    assert body["metric"] == "cpuPct"
    assert body["unit"] == "percent"
    assert body["agg"] == "avg"
    assert body["order"] == "desc"
    assert [asset["hostname"] for asset in body["assets"]] == ["host-10", "host-09", "host-08"]
    assert [asset["value"] for asset in body["assets"]] == [
        pytest.approx(100.0), pytest.approx(90.0), pytest.approx(80.0),
    ]
    assert body["assets"][0]["sampleCount"] == 2
    assert body["assetCount"] == 10
    assert body["assetsWithData"] == 10


def test_ascending_order_returns_the_lowest(client, ten_assets, regular_user, auth_headers):
    """``order=asc`` da los de menor valor primero."""
    status, body = _get(
        client, "/hygeia/stats/ranking", auth_headers(regular_user),
        metric="cpuPct", limit=2, order="asc",
    )

    assert status == 200
    assert [asset["hostname"] for asset in body["assets"]] == ["host-01", "host-02"]


def test_agg_max_ranks_by_the_peak(client, ten_assets, regular_user, auth_headers):
    """Con ``agg=max`` el valor comparado es el máximo de cada activo, no su media."""
    status, body = _get(
        client, "/hygeia/stats/ranking", auth_headers(regular_user),
        metric="cpuPct", agg="max", limit=1,
    )

    assert status == 200
    assert body["assets"][0]["hostname"] == "host-10"
    assert body["assets"][0]["value"] == pytest.approx(105.0)


def test_assets_without_data_and_other_users_assets_stay_out(
    client, app, regular_user, make_user, auth_headers,
):
    """Un activo sin muestras no entra como si valiera cero, y el de otro usuario no entra nunca."""
    stranger = make_user()
    reporting = _create_asset(app, regular_user.id, "reporting")
    _create_asset(app, regular_user.id, "silent")
    foreign = _create_asset(app, stranger.id, "foreign")
    _seed(app, reporting, [(timedelta(minutes=10), {"cpu_pct": 50.0})])
    _seed(app, foreign, [(timedelta(minutes=10), {"cpu_pct": 99.0})])

    status, body = _get(
        client, "/hygeia/stats/ranking", auth_headers(regular_user), metric="cpuPct", order="asc",
    )

    assert status == 200
    assert body["assetCount"] == 2
    assert body["assetsWithData"] == 1
    assert [asset["hostname"] for asset in body["assets"]] == ["reporting"]


@pytest.mark.parametrize("query, expected_status", [
    ({}, 422),
    ({"metric": "cpuPct", "limit": 0}, 422),
    ({"metric": "cpuPct", "limit": 101}, 422),
    ({"metric": "cpuPct", "agg": "sum"}, 422),
    ({"metric": "cpuPct", "order": "sideways"}, 422),
    ({"metric": "cpu_pct"}, 400),
])
def test_the_ranking_rejects_a_bad_query(client, regular_user, auth_headers, query, expected_status):
    """Parámetros mal formados son 422; una métrica desconocida, el 400 del registro."""
    status, _ = _get(client, "/hygeia/stats/ranking", auth_headers(regular_user), **query)

    assert status == expected_status


# =============================================================================
# PANORAMA DEL PARQUE
# =============================================================================

def _save_anomaly(app, asset_id: int, severity: str, state: str = "open") -> None:
    """Guarda una anomalía del activo con la severidad y el estado dados."""
    with app.app_context():
        with UnitOfWork() as uow:
            AnomalyRepository(uow).save(Anomaly(
                asset_id=asset_id, kind="cpu_spike", severity=severity, state=state,
            ))


def _parse_utc(text: str) -> datetime:
    """Convierte un instante ISO de la API (``Z`` o ``+00:00``) en naive-UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def test_the_overview_summarizes_the_users_fleet(
    client, app, regular_user, make_user, auth_headers,
):
    """Estados, anomalías activas, uptime de los activos en línea y última actividad, solo del usuario."""
    user_id = regular_user.id
    online_first = _create_asset(
        app, user_id, "online-a", uptime_sec=3600, last_seen_at=datetime(2026, 9, 10, 12, 0),
    )
    _create_asset(
        app, user_id, "online-b", uptime_sec=7200, last_seen_at=datetime(2026, 9, 10, 13, 0),
    )
    stale = _create_asset(
        app, user_id, "stale", status="stale", uptime_sec=99_999,
        last_seen_at=datetime(2026, 9, 10, 11, 0),
    )
    offline = _create_asset(app, user_id, "offline", status="offline", last_seen_at=None)
    _create_asset(app, user_id, "pending", status="pending", last_seen_at=None)
    _save_anomaly(app, online_first, "critical")
    _save_anomaly(app, online_first, "warning")
    _save_anomaly(app, stale, "warning", state="acknowledged")
    _save_anomaly(app, offline, "info", state="resolved")

    stranger = make_user()
    foreign = _create_asset(
        app, stranger.id, "foreign", uptime_sec=1, last_seen_at=datetime(2026, 9, 11, 0, 0),
    )
    _save_anomaly(app, foreign, "critical")

    status, body = _get(client, "/hygeia/stats/overview", auth_headers(regular_user))

    assert status == 200
    assert body["assetCount"] == 5
    assert body["assetsByStatus"] == {"pending": 1, "online": 2, "stale": 1, "offline": 1}
    assert body["openAnomaliesBySeverity"] == {"info": 0, "warning": 1, "critical": 1}
    assert body["acknowledgedAnomalyCount"] == 1
    # Media de los dos en línea (3600 y 7200); el stale no entra aunque tenga uptime.
    assert body["averageUptimeSec"] == pytest.approx(5400.0)
    assert _parse_utc(body["lastActivityAt"]) == datetime(2026, 9, 10, 13, 0)


def test_an_empty_fleet_has_zeros_and_no_averages(client, regular_user, auth_headers):
    """Sin activos: todos los recuentos a cero y ni uptime ni actividad."""
    status, body = _get(client, "/hygeia/stats/overview", auth_headers(regular_user))

    assert status == 200
    assert body["assetCount"] == 0
    assert body["assetsByStatus"] == {"pending": 0, "online": 0, "stale": 0, "offline": 0}
    assert body["openAnomaliesBySeverity"] == {"info": 0, "warning": 0, "critical": 0}
    assert body["acknowledgedAnomalyCount"] == 0
    assert body["averageUptimeSec"] is None
    assert body["lastActivityAt"] is None
