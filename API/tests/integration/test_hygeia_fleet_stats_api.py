"""
Tests de integración HTTP de las estadísticas del parque de un usuario: el
ranking de activos por métrica (``GET /hygeia/stats/ranking``).

Siembra activos y snapshots directamente por repositorio, igual que el resto
de tests de estadísticas de Hygeia: por HTTP no se puede construir una serie
con valores e instantes elegidos.
"""

import secrets
from datetime import timedelta

import pytest

from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int, hostname: str, **columns) -> int:
    """Da de alta un activo del usuario, con las columnas extra dadas, y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, status="online", last_seen_at=utcnow_naive(),
                user_id=user_id, **columns,
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
