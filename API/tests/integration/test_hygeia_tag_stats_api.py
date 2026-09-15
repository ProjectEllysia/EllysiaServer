"""
Tests de integración HTTP de las estadísticas por etiqueta
(``GET /hygeia/stats/by-tag/<tagId>``).

Siembra activos, etiquetas y snapshots directamente por repositorio, igual
que el resto de tests de estadísticas de Hygeia: por HTTP no se puede
construir una serie con valores e instantes elegidos.
"""

import secrets
from datetime import timedelta

import pytest

from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset, SystemTag, UserTag
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


def _create_tag(app, name: str, user_id=None) -> int:
    """Crea una etiqueta de sistema (sin ``user_id``) o personal, y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            tag = (
                SystemTag(name=name, color="blue") if user_id is None
                else UserTag(name=name, color="blue", user_id=user_id)
            )
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


def _tag_stats(client, tag_id: int, headers: dict, **query) -> tuple:
    """Pide las estadísticas de la etiqueta y devuelve ``(status, cuerpo)``."""
    response = client.get(f"/hygeia/stats/by-tag/{tag_id}", query_string=query, headers=headers)
    return response.status_code, response.get_json()


@pytest.fixture()
def production_tag(app, regular_user):
    """Etiqueta personal con tres activos del usuario y lecturas conocidas.

    - alpha: tráfico 100 y 300 (media 200, pico 300), memoria 40 %; y una
      lectura de hace dos días que un periodo de 24 h deja fuera.
    - bravo: tráfico 1000, memoria 60 %.
    - charlie: tráfico 50 y 50, memoria 50 %.
    """
    tag_id = _create_tag(app, "produccion", user_id=regular_user.id)
    alpha, bravo, charlie = (
        _create_asset(app, regular_user.id, hostname) for hostname in ("alpha", "bravo", "charlie")
    )
    _tag_assets(app, tag_id, [charlie, alpha, bravo])
    _seed(app, alpha, [
        (timedelta(minutes=30), {"net_rx_bps": 100, "mem_pct": 40.0}),
        (timedelta(minutes=10), {"net_rx_bps": 300, "mem_pct": 40.0}),
        (timedelta(days=2), {"net_rx_bps": 999_999, "mem_pct": 99.0}),
    ])
    _seed(app, bravo, [(timedelta(minutes=20), {"net_rx_bps": 1000, "mem_pct": 60.0})])
    _seed(app, charlie, [
        (timedelta(minutes=25), {"net_rx_bps": 50, "mem_pct": 50.0}),
        (timedelta(minutes=5), {"net_rx_bps": 50, "mem_pct": 50.0}),
    ])
    return tag_id


def test_the_sum_of_an_additive_metric_adds_the_average_of_each_asset(
    client, production_tag, regular_user, auth_headers,
):
    """Tráfico total de la etiqueta: 200 + 1000 + 50, con el desglose por activo."""
    status, body = _tag_stats(
        client, production_tag, auth_headers(regular_user), metrics="netRxBps", agg="sum",
    )

    assert status == 200
    assert body["tag"]["name"] == "produccion"
    assert body["assetCount"] == 3
    assert body["agg"] == "sum"
    traffic = body["metrics"]["netRxBps"]
    assert traffic["unit"] == "bytesPerSecond"
    assert traffic["value"] == pytest.approx(1250.0)
    assert traffic["assetsWithData"] == 3
    assert [asset["hostname"] for asset in traffic["assets"]] == ["alpha", "bravo", "charlie"]
    alpha = traffic["assets"][0]
    assert alpha["average"] == pytest.approx(200.0)
    assert alpha["maximum"] == 300.0
    assert alpha["sampleCount"] == 2


@pytest.mark.parametrize("agg, expected", [("avg", 50.0), ("max", 60.0)])
def test_a_percentage_metric_declares_its_unit(
    client, production_tag, regular_user, auth_headers, agg, expected,
):
    """La memoria se agrega como porcentaje y la respuesta lo dice, sin fingir bytes."""
    status, body = _tag_stats(
        client, production_tag, auth_headers(regular_user), metrics="memPct", agg=agg,
    )

    assert status == 200
    memory = body["metrics"]["memPct"]
    assert memory["unit"] == "percent"
    assert memory["value"] == pytest.approx(expected)


def test_the_sum_of_a_percentage_is_rejected(client, production_tag, regular_user, auth_headers):
    """Sumar porcentajes entre equipos no mide nada: 400 con las métricas que sí se suman."""
    status, body = _tag_stats(
        client, production_tag, auth_headers(regular_user), metrics="netRxBps,cpuPct", agg="sum",
    )

    assert status == 400
    assert body["error"] == "NonAdditiveMetricError"
    assert body["details"]["metric"] == "cpuPct"
    assert body["details"]["additive_metrics"] == ["netRxBps", "netTxBps", "powerWatts"]


def test_the_default_aggregation_is_the_average(client, production_tag, regular_user, auth_headers):
    """Sin ``agg`` se combinan con la media, que vale para cualquier métrica."""
    status, body = _tag_stats(client, production_tag, auth_headers(regular_user), metrics="memPct")

    assert status == 200
    assert body["agg"] == "avg"


def test_a_system_tag_only_counts_the_users_own_assets(
    client, app, regular_user, make_user, auth_headers,
):
    """Una etiqueta de sistema la usa todo el mundo: el activo de otro usuario no entra."""
    tag_id = _create_tag(app, "compartida")
    stranger = make_user()
    mine = _create_asset(app, regular_user.id, "mine")
    theirs = _create_asset(app, stranger.id, "theirs")
    _tag_assets(app, tag_id, [mine, theirs])
    _seed(app, mine, [(timedelta(minutes=10), {"net_rx_bps": 100})])
    _seed(app, theirs, [(timedelta(minutes=10), {"net_rx_bps": 5000})])

    status, body = _tag_stats(
        client, tag_id, auth_headers(regular_user), metrics="netRxBps", agg="sum",
    )

    assert status == 200
    assert body["assetCount"] == 1
    assert body["metrics"]["netRxBps"]["value"] == pytest.approx(100.0)
    assert [asset["hostname"] for asset in body["metrics"]["netRxBps"]["assets"]] == ["mine"]


def test_an_asset_without_data_counts_in_the_tag_but_not_in_the_value(
    client, app, regular_user, auth_headers,
):
    """Un equipo apagado sigue en la etiqueta, pero no suma cero a la cifra."""
    tag_id = _create_tag(app, "mixta", user_id=regular_user.id)
    reporting = _create_asset(app, regular_user.id, "reporting")
    silent = _create_asset(app, regular_user.id, "silent")
    _tag_assets(app, tag_id, [reporting, silent])
    _seed(app, reporting, [(timedelta(minutes=10), {"power_watts": 120.0})])

    status, body = _tag_stats(
        client, tag_id, auth_headers(regular_user), metrics="powerWatts", agg="avg",
    )

    assert status == 200
    power = body["metrics"]["powerWatts"]
    assert body["assetCount"] == 2
    assert power["assetsWithData"] == 1
    assert power["value"] == pytest.approx(120.0)
    silent_entry = next(asset for asset in power["assets"] if asset["hostname"] == "silent")
    assert silent_entry == {
        "assetId": silent, "hostname": "silent", "average": None, "maximum": None, "sampleCount": 0,
    }


def test_a_tag_without_assets_has_no_value(client, app, regular_user, auth_headers):
    """Una etiqueta sin activos del usuario responde con cero activos y sin cifra."""
    tag_id = _create_tag(app, "vacia", user_id=regular_user.id)

    status, body = _tag_stats(client, tag_id, auth_headers(regular_user), metrics="cpuPct")

    assert status == 200
    assert body["assetCount"] == 0
    assert body["metrics"]["cpuPct"]["value"] is None
    assert body["metrics"]["cpuPct"]["assets"] == []


def test_another_users_personal_tag_is_not_found(client, app, make_user, regular_user, auth_headers):
    """La etiqueta personal de otro usuario da el mismo 404 que una inexistente."""
    stranger = make_user()
    foreign_tag = _create_tag(app, "ajena", user_id=stranger.id)

    status, _ = _tag_stats(client, foreign_tag, auth_headers(regular_user), metrics="cpuPct")
    missing_status, _ = _tag_stats(client, 999_999, auth_headers(regular_user), metrics="cpuPct")

    assert status == 404
    assert missing_status == 404
