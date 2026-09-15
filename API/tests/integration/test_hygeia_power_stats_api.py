"""
Tests de integración HTTP del consumo eléctrico agregado de un conjunto de
activos (``GET /hygeia/stats/power``): todo el parque del usuario o los
activos de una etiqueta.

Siembra snapshots de potencia por repositorio, igual que
``test_hygeia_power_summary.py``: el suelo de cadencia de la ingesta impide
construir por HTTP una serie lo bastante densa. Los kWh esperados se derivan
de la misma regla que el resumen de consumo: la energía solo cuenta sobre el
tiempo observado, y un salto de más de tres veces el intervalo típico es un
hueco que no se imputa.
"""

import secrets
from datetime import timedelta

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
            tag = UserTag(name=name, color="amber", user_id=user_id)
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


def _seed_power(app, asset_id: int, minutes_ago: list, watts, estimated: bool = False) -> None:
    """Guarda un snapshot por cada antigüedad en minutos, con la potencia dada.

    Con ``watts=None`` el snapshot no trae potencia (un host sin sensor), pero
    sí CPU, como cualquier heartbeat.
    """
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            now = utcnow_naive()
            for age in minutes_ago:
                instant = now - timedelta(minutes=age)
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant, metrics={},
                    cpu_pct=10.0, power_watts=watts,
                    power_estimated=None if watts is None else estimated,
                    power_source=None if watts is None else "rapl",
                ))


def _power_stats(client, headers: dict, **query) -> tuple:
    """Pide el consumo agregado y devuelve ``(status, cuerpo)``."""
    response = client.get("/hygeia/stats/power", query_string=query, headers=headers)
    return response.status_code, response.get_json()


def _energy_kwh(watts: float, observed_minutes: int) -> float:
    """Energía de una potencia constante durante unos minutos observados."""
    return watts * observed_minutes / 60 / 1000


#: kWh esperados del activo con cobertura completa: una lectura por minuto
#: durante la última hora son 59 intervalos observados de un minuto.
_FULL_KWH = _energy_kwh(100.0, 59)

#: kWh esperados del activo con un hueco: nueve minutos observados al
#: principio de la hora y nueve al final; los 41 del medio son un hueco.
_GAPPY_KWH = _energy_kwh(200.0, 18)


@pytest.fixture()
def rack(app, regular_user):
    """Etiqueta «rack» con tres activos, más un cuarto activo del usuario sin etiqueta.

    - full: 100 W medidos cada minuto durante la última hora.
    - gappy: 200 W estimados, con un hueco de 41 minutos en medio.
    - no-power: heartbeats sin potencia (host sin sensor).
    - outside: 50 W durante la última media hora; no lleva la etiqueta.
    """
    user_id = regular_user.id
    tag_id = _create_tag(app, user_id, "rack")
    full = _create_asset(app, user_id, "full")
    gappy = _create_asset(app, user_id, "gappy")
    no_power = _create_asset(app, user_id, "no-power")
    outside = _create_asset(app, user_id, "outside")
    _tag_assets(app, tag_id, [full, gappy, no_power])
    _seed_power(app, full, list(range(59, -1, -1)), 100.0)
    _seed_power(app, gappy, list(range(59, 49, -1)) + list(range(9, -1, -1)), 200.0, estimated=True)
    _seed_power(app, no_power, [30, 20, 10], None)
    _seed_power(app, outside, list(range(30, -1, -1)), 50.0)
    return tag_id


def test_a_tag_adds_the_energy_of_its_assets_without_counting_missing_data(
    client, app, rack, regular_user, auth_headers,
):
    """Suma exacta de los dos con datos; el tercero no aporta un cero y el conjunto es parcial."""
    status, body = _power_stats(
        client, auth_headers(regular_user), scope="tag", tagId=rack, period="1h",
    )

    with app.app_context():
        price_per_kwh = CR.hygeia_config().energy_price_per_kwh
        currency = CR.hygeia_config().energy_price_currency
    assert status == 200
    assert body["scope"] == "tag"
    assert body["tag"]["name"] == "rack"
    assert body["assetCount"] == 3
    assert body["assetsWithData"] == 2
    assert body["assetsEstimated"] == 1
    assert body["kwh"] == pytest.approx(_FULL_KWH + _GAPPY_KWH)
    assert body["cost"] == pytest.approx((_FULL_KWH + _GAPPY_KWH) * price_per_kwh)
    assert body["currency"] == currency
    # El completo es "observed"; el del hueco, "observed_partial": el total es tan
    # fiable como su parte menos fiable.
    assert body["classification"] == "observed_partial"

    assets = {asset["hostname"]: asset for asset in body["assets"]}
    assert [asset["hostname"] for asset in body["assets"]] == ["full", "gappy", "no-power"]
    assert assets["full"]["kwh"] == pytest.approx(_FULL_KWH)
    assert assets["full"]["classification"] == "observed"
    assert assets["full"]["isEstimated"] is False
    assert assets["gappy"]["kwh"] == pytest.approx(_GAPPY_KWH)
    assert assets["gappy"]["isEstimated"] is True
    assert assets["no-power"]["kwh"] is None
    assert assets["no-power"]["cost"] is None


def test_the_fleet_covers_every_asset_of_the_user_and_nobody_elses(
    client, app, rack, regular_user, make_user, auth_headers,
):
    """El parque incluye el activo sin etiqueta, pero no el de otro usuario."""
    stranger = make_user()
    foreign = _create_asset(app, stranger.id, "foreign")
    _seed_power(app, foreign, list(range(30, -1, -1)), 5000.0)

    status, body = _power_stats(client, auth_headers(regular_user), scope="fleet", period="1h")

    assert status == 200
    assert body["scope"] == "fleet"
    assert body["tag"] is None
    assert body["assetCount"] == 4
    assert body["kwh"] == pytest.approx(_FULL_KWH + _GAPPY_KWH + _energy_kwh(50.0, 30))
    assert "foreign" not in [asset["hostname"] for asset in body["assets"]]


def test_without_power_data_there_is_no_total(client, app, regular_user, auth_headers):
    """Si ningún activo tiene potencia, no hay cifra: ``null``, no ``0``."""
    tag_id = _create_tag(app, regular_user.id, "sin-sensores")
    asset_id = _create_asset(app, regular_user.id, "no-sensor")
    _tag_assets(app, tag_id, [asset_id])
    _seed_power(app, asset_id, [20, 10], None)

    status, body = _power_stats(client, auth_headers(regular_user), scope="tag", tagId=tag_id)

    assert status == 200
    assert body["assetsWithData"] == 0
    assert body["kwh"] is None
    assert body["cost"] is None
    assert body["classification"] is None


@pytest.mark.parametrize("query", [
    {"scope": "tag"},
    {"scope": "fleet", "tagId": 1},
    {"scope": "planet"},
    {"period": "7w"},
])
def test_a_malformed_query_is_rejected(client, regular_user, auth_headers, query):
    """``tagId`` va solo con ``scope=tag`` y es obligatorio en él; el resto, validación normal."""
    status, _ = _power_stats(client, auth_headers(regular_user), **query)

    assert status == 422


def test_another_users_personal_tag_is_not_found(client, app, regular_user, make_user, auth_headers):
    """La etiqueta personal de otro usuario da el mismo 404 que una inexistente."""
    stranger = make_user()
    foreign_tag = _create_tag(app, stranger.id, "ajena")

    status, _ = _power_stats(client, auth_headers(regular_user), scope="tag", tagId=foreign_tag)

    assert status == 404
