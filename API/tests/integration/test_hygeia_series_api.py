"""
Tests de integración HTTP de la serie temporal multi-activo
(``GET /hygeia/stats/series``).

Siembra activos, etiquetas y snapshots directamente por repositorio. Las
lecturas caen dentro de una hora ya pasada, alineada con un cubo de 3600 s,
para que cada serie tenga un único punto con un valor conocido.
"""

import math
import secrets
from datetime import datetime, timedelta, timezone

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset, UserTag
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    HygeiaTagRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int, hostname: str) -> int:
    """Da de alta un activo mínimo del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, status="online", last_seen_at=utcnow_naive(),
                user_id=user_id,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _create_tag(app, user_id: int, name: str) -> int:
    """Crea una etiqueta personal del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            tag = UserTag(name=name, color="teal", user_id=user_id)
            HygeiaTagRepository(uow).save(tag)
            return tag.id


def _tag_assets(app, tag_id: int, asset_ids: list) -> None:
    """Pone la etiqueta a cada uno de los activos."""
    with app.app_context():
        with UnitOfWork() as uow:
            tag = HygeiaTagRepository(uow).get_by_id(tag_id)
            asset_repo = MonitoredAssetRepository(uow)
            for asset_id in asset_ids:
                asset = asset_repo.get_by_id(asset_id)
                asset.tags.append(tag)
                asset_repo.update(asset)


def _seed_in_hour(app, asset_id: int, hour_start: datetime, readings: list) -> None:
    """Guarda un snapshot por cada ``(minuto dentro de la hora, columnas)``."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            for minute, columns in readings:
                instant = hour_start + timedelta(minutes=minute)
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant,
                    metrics={}, **columns,
                ))


def _series(client, headers: dict, **query) -> tuple:
    """Pide la serie multi-activo y devuelve ``(status, cuerpo)``."""
    response = client.get("/hygeia/stats/series", query_string=query, headers=headers)
    return response.status_code, response.get_json()


def _parse_utc(text: str) -> datetime:
    """Convierte un instante ISO de la API (``Z`` o ``+00:00``) en naive-UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def rack(app, regular_user):
    """Etiqueta con tres activos y una hora ya pasada con lecturas conocidas.

    - alpha: tráfico 100 y 300 en la misma hora (media 200, máximo 300).
    - bravo: tráfico 1000.
    - charlie: tráfico 50.
    """
    hour_start = (utcnow_naive() - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    tag_id = _create_tag(app, regular_user.id, "rack")
    alpha = _create_asset(app, regular_user.id, "alpha")
    bravo = _create_asset(app, regular_user.id, "bravo")
    charlie = _create_asset(app, regular_user.id, "charlie")
    _tag_assets(app, tag_id, [alpha, bravo, charlie])
    _seed_in_hour(app, alpha, hour_start, [(5, {"net_rx_bps": 100}), (20, {"net_rx_bps": 300})])
    _seed_in_hour(app, bravo, hour_start, [(10, {"net_rx_bps": 1000})])
    _seed_in_hour(app, charlie, hour_start, [(15, {"net_rx_bps": 50})])
    return {
        "tag_id": tag_id, "hour_start": hour_start,
        "alpha": alpha, "bravo": bravo, "charlie": charlie,
    }


def test_the_sum_over_a_tag_adds_each_assets_bucket_once(client, rack, regular_user, auth_headers):
    """Una sola serie: 200 (media de alpha en el cubo) + 1000 + 50, con tres activos aportando."""
    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", tagId=rack["tag_id"], agg="sum", bucket=3600,
    )

    assert status == 200
    assert body["unit"] == "bytesPerSecond"
    assert body["agg"] == "sum"
    assert body["bucketAgg"] == "avg"
    assert body["bucket"] == 3600
    assert body["isBucketWidened"] is False
    assert len(body["series"]) == 1
    series = body["series"][0]
    assert series["kind"] == "tag"
    assert series["tagId"] == rack["tag_id"]
    assert series["label"] == "rack"
    assert len(series["points"]) == 1
    point = series["points"][0]
    assert _parse_utc(point["at"]) == rack["hour_start"]
    assert point["value"] == pytest.approx(1250.0)
    assert point["assetCount"] == 3


def test_agg_max_combines_with_the_busiest_asset(client, rack, regular_user, auth_headers):
    """Con ``agg=max`` el punto es el del activo más cargado en el cubo."""
    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", tagId=rack["tag_id"], agg="max", bucket=3600,
    )

    assert status == 200
    assert body["series"][0]["points"][0]["value"] == pytest.approx(1000.0)


def test_without_agg_each_asset_gets_its_own_series(client, rack, regular_user, auth_headers):
    """Una lista de activos sin ``agg``: una serie por activo, por hostname, con ``bucketAgg``."""
    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", assetIds=f"{rack['bravo']},{rack['alpha']}", bucketAgg="max", bucket=3600,
    )

    assert status == 200
    assert body["agg"] is None
    assert [series["label"] for series in body["series"]] == ["alpha", "bravo"]
    alpha = body["series"][0]
    assert alpha["kind"] == "asset"
    assert alpha["assetId"] == rack["alpha"]
    assert alpha["points"][0]["value"] == pytest.approx(300.0)
    assert "assetCount" not in alpha["points"][0]


def test_a_list_of_assets_can_be_combined_too(client, rack, regular_user, auth_headers):
    """Una lista combinada sale como ``kind="assets"``, sin etiqueta."""
    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", assetIds=f"{rack['alpha']},{rack['charlie']}", agg="sum", bucket=3600,
    )

    assert status == 200
    series = body["series"][0]
    assert series["kind"] == "assets"
    assert series["label"] is None
    assert series["points"][0]["value"] == pytest.approx(250.0)
    assert series["points"][0]["assetCount"] == 2


def test_a_bucket_too_fine_is_widened_and_says_so(app, client, rack, regular_user, auth_headers):
    """Un cubo de un minuto sobre 24 h daría más de ``maxSeriesPoints``: se ensancha y se avisa."""
    with app.app_context():
        max_points = CR.hygeia_limits().max_series_points
    expected_bucket = math.ceil(24 * 3600 / (max_points - 1))

    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", tagId=rack["tag_id"], bucket=60, period="24h",
    )
    _, default_body = _series(
        client, auth_headers(regular_user), metric="netRxBps", tagId=rack["tag_id"], period="24h",
    )

    assert status == 200
    assert body["bucket"] == expected_bucket
    assert body["isBucketWidened"] is True
    # Sin cubo pedido se usa ese mismo mínimo, y no hay nada que avisar.
    assert default_body["bucket"] == expected_bucket
    assert default_body["isBucketWidened"] is False


def test_the_sum_of_a_percentage_is_rejected(client, rack, regular_user, auth_headers):
    """Sumar porcentajes entre activos no mide nada: el 400 de la métrica no aditiva."""
    status, body = _series(
        client, auth_headers(regular_user), metric="cpuPct", tagId=rack["tag_id"], agg="sum",
    )

    assert status == 400
    assert body["error"] == "NonAdditiveMetricError"


def test_an_asset_of_another_user_is_not_found(client, app, rack, regular_user, make_user, auth_headers):
    """Colar el activo de otro usuario en la lista da el mismo 404 que un id inexistente."""
    stranger = make_user()
    foreign = _create_asset(app, stranger.id, "foreign")

    status, _ = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", assetIds=f"{rack['alpha']},{foreign}",
    )
    missing_status, _ = _series(
        client, auth_headers(regular_user), metric="netRxBps", assetIds="999999",
    )

    assert status == 404
    assert missing_status == 404


@pytest.mark.parametrize("query", [
    {"metric": "netRxBps"},
    {"metric": "netRxBps", "tagId": 1, "assetIds": "1"},
    {"metric": "netRxBps", "assetIds": "1,,2"},
    {"metric": "netRxBps", "assetIds": "1", "bucketAgg": "p95"},
    {"tagId": 1},
])
def test_a_malformed_query_is_rejected(client, regular_user, auth_headers, query):
    """Exactamente uno de ``tagId``/``assetIds``, ids bien formados y ``metric`` obligatoria."""
    status, _ = _series(client, auth_headers(regular_user), **query)

    assert status == 422


# =============================================================================
# SERIES COMPARATIVAS
# =============================================================================

def test_a_tag_compared_with_one_of_its_assets_shares_the_buckets(
    client, rack, regular_user, auth_headers,
):
    """La media de la etiqueta frente a uno de sus activos, con los cubos en los mismos instantes."""
    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", tagId=rack["tag_id"], agg="avg", bucket=3600,
        compareTo=f"asset:{rack['alpha']}",
    )

    assert status == 200
    main, comparison = body["series"]
    assert main["kind"] == "tag"
    assert main["isComparison"] is False
    assert main["points"][0]["value"] == pytest.approx((200.0 + 1000.0 + 50.0) / 3)
    assert comparison["kind"] == "asset"
    assert comparison["label"] == "alpha"
    assert comparison["isComparison"] is True
    assert comparison["points"][0]["value"] == pytest.approx(200.0)
    assert [point["at"] for point in main["points"]] == [point["at"] for point in comparison["points"]]


def test_two_tags_can_be_compared(client, app, rack, regular_user, auth_headers):
    """Una etiqueta frente a otra, las dos combinadas con el mismo ``agg``."""
    other_tag = _create_tag(app, regular_user.id, "otra")
    delta = _create_asset(app, regular_user.id, "delta")
    _tag_assets(app, other_tag, [delta])
    _seed_in_hour(app, delta, rack["hour_start"], [(30, {"net_rx_bps": 400})])

    status, body = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", tagId=rack["tag_id"], agg="sum", bucket=3600,
        compareTo=f"tag:{other_tag}",
    )

    assert status == 200
    main, comparison = body["series"]
    assert main["points"][0]["value"] == pytest.approx(1250.0)
    assert comparison["kind"] == "tag"
    assert comparison["label"] == "otra"
    assert comparison["isComparison"] is True
    assert comparison["points"][0]["value"] == pytest.approx(400.0)
    assert comparison["points"][0]["at"] == main["points"][0]["at"]


def test_comparing_with_another_users_asset_is_not_found(
    client, app, rack, regular_user, make_user, auth_headers,
):
    """La fuente de comparación pasa por el mismo control de dueño que la principal."""
    stranger = make_user()
    foreign = _create_asset(app, stranger.id, "foreign")

    status, _ = _series(
        client, auth_headers(regular_user),
        metric="netRxBps", tagId=rack["tag_id"], agg="avg", compareTo=f"asset:{foreign}",
    )

    assert status == 404


@pytest.mark.parametrize("compare_to, agg", [("tag:1", None), ("host:1", "avg"), ("asset:x", "avg")])
def test_a_malformed_comparison_is_rejected(client, rack, regular_user, auth_headers, compare_to, agg):
    """``compareTo`` es ``asset:<id>`` o ``tag:<id>``, y con una etiqueta hace falta ``agg``."""
    query = {"metric": "netRxBps", "tagId": rack["tag_id"], "compareTo": compare_to}
    if agg:
        query["agg"] = agg

    status, _ = _series(client, auth_headers(regular_user), **query)

    assert status == 422
