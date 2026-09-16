"""
Tests de integración HTTP del patrón horario de carga
(``GET /hygeia/stats/hourly-pattern``).

Lo que el endpoint promete es que un pico que ocurre siempre a la misma hora
aparezca en la posición correcta de un array de 24, y que una hora sin ningún
latido se distinga de una hora tranquila. Los snapshots se siembran por
repositorio con ``received_at`` colocado en horas concretas: por HTTP la hora
de recepción la pone el servidor y no se puede elegir.

Las horas son las del reloj del servidor, y los snapshots se siembran en
naive-UTC como el resto del módulo, así que la hora sembrada es la hora que
devuelve la API.
"""

import secrets
from datetime import timedelta

import pytest

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
    """Da de alta un activo en línea del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, user_id=user_id, status="online",
                last_seen_at=utcnow_naive(),
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _tag_asset(app, user_id: int, asset_id: int, name: str) -> int:
    """Crea una etiqueta personal del usuario, se la pone al activo y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            tag = UserTag(name=name, color="blue", user_id=user_id)
            HygeiaTagRepository(uow).save(tag)
            asset_repo = MonitoredAssetRepository(uow)
            asset = asset_repo.get_by_id(asset_id)
            asset.tags.append(tag)
            asset_repo.update(asset)
            return tag.id


def _seed_at_hours(app, asset_id: int, readings: list) -> None:
    """Guarda un snapshot de CPU por cada ``(hora_del_día, cpu)``.

    Cada lectura se coloca ayer a esa hora en punto, para que caiga dentro de
    una ventana de 24 h sin depender de la hora a la que corra el test.
    """
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            reference = utcnow_naive() - timedelta(hours=12)
            for hour, cpu in readings:
                instant = reference.replace(hour=hour, minute=30, second=0, microsecond=0)
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant,
                    metrics={}, cpu_pct=cpu,
                ))


def _get(client, headers: dict, **query) -> tuple:
    """Hace el GET del patrón horario y devuelve ``(status, cuerpo)``."""
    response = client.get(
        "/hygeia/stats/hourly-pattern", query_string=query, headers=headers,
    )
    return response.status_code, response.get_json()


def _hour(body: dict, hour: int) -> dict:
    """La entrada de una hora concreta del patrón."""
    return body["hours"][hour]


@pytest.fixture()
def asset_with_morning_peak(app, regular_user):
    """Un activo cuyo pico de CPU está siempre a las 9, y devuelve su id.

    A las 9 marca un 90 %; a las 3 y a las 15, un 10 %. El periodo de siete
    días abarca las tres lecturas.
    """
    asset_id = _create_asset(app, regular_user.id, "host-oficina")
    _seed_at_hours(app, asset_id, [(3, 10.0), (9, 90.0), (15, 10.0)])
    return asset_id


def test_the_peak_lands_on_the_hour_it_happened(
    client, asset_with_morning_peak, regular_user, auth_headers,
):
    """El pico conocido de las 9 aparece en la posición 9 del array de 24."""
    status, body = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="asset", assetId=asset_with_morning_peak, period="7d",
    )

    assert status == 200
    assert body["peakHour"] == 9
    assert _hour(body, 9)["value"] == pytest.approx(90.0)
    assert _hour(body, 3)["value"] == pytest.approx(10.0)


def test_the_pattern_always_has_the_twenty_four_hours_in_order(
    client, asset_with_morning_peak, regular_user, auth_headers,
):
    """``hours`` trae las 24 horas, de la 0 a la 23, tengan muestras o no."""
    _, body = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="asset", assetId=asset_with_morning_peak, period="7d",
    )

    assert [entry["hour"] for entry in body["hours"]] == list(range(24))


def test_an_hour_without_heartbeats_is_a_gap_and_not_a_zero(
    client, asset_with_morning_peak, regular_user, auth_headers,
):
    """Una hora sin latidos vale ``None`` con ``sampleCount`` 0, nunca ``0.0``.

    Un parque que se apaga de noche tiene que verse como un hueco; pintarlo
    como un cero lo convertiría en un parque ocioso, que es otra cosa.
    """
    _, body = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="asset", assetId=asset_with_morning_peak, period="7d",
    )

    assert _hour(body, 7)["value"] is None
    assert _hour(body, 7)["sampleCount"] == 0
    assert _hour(body, 9)["sampleCount"] == 1


def test_the_aggregation_changes_what_the_hour_reports(app, client, regular_user, auth_headers):
    """``agg=avg`` da la carga típica de la hora y ``agg=max`` su peor momento."""
    asset_id = _create_asset(app, regular_user.id, "host-variable")
    _seed_at_hours(app, asset_id, [(9, 20.0)])
    with app.app_context():
        with UnitOfWork() as uow:
            instant = (utcnow_naive() - timedelta(hours=12)).replace(
                hour=9, minute=45, second=0, microsecond=0,
            )
            AssetSnapshotRepository(uow).save(AssetSnapshot(
                asset_id=asset_id, collected_at=instant, received_at=instant,
                metrics={}, cpu_pct=80.0,
            ))

    _, averaged = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="asset", assetId=asset_id, agg="avg", period="7d",
    )
    _, peaked = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="asset", assetId=asset_id, agg="max", period="7d",
    )

    assert _hour(averaged, 9)["value"] == pytest.approx(50.0)
    assert _hour(peaked, 9)["value"] == pytest.approx(80.0)
    assert _hour(averaged, 9)["sampleCount"] == 2


def test_the_fleet_scope_pools_every_asset_of_the_user(app, client, regular_user, auth_headers):
    """Con ``scope=fleet`` los latidos de todos los activos caen en el mismo cubo horario."""
    first = _create_asset(app, regular_user.id, "host-uno")
    second = _create_asset(app, regular_user.id, "host-dos")
    _seed_at_hours(app, first, [(9, 30.0)])
    _seed_at_hours(app, second, [(9, 70.0)])

    _, body = _get(client, auth_headers(regular_user), metric="cpuPct", period="7d")

    assert body["scope"] == "fleet"
    assert body["assetCount"] == 2
    assert _hour(body, 9)["value"] == pytest.approx(50.0)
    assert _hour(body, 9)["sampleCount"] == 2


def test_the_tag_scope_only_pools_the_tagged_assets(app, client, regular_user, auth_headers):
    """Con ``scope=tag`` el activo sin la etiqueta no entra en el patrón."""
    tagged = _create_asset(app, regular_user.id, "host-etiquetado")
    untagged = _create_asset(app, regular_user.id, "host-suelto")
    tag_id = _tag_asset(app, regular_user.id, tagged, "produccion")
    _seed_at_hours(app, tagged, [(9, 30.0)])
    _seed_at_hours(app, untagged, [(9, 90.0)])

    _, body = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="tag", tagId=tag_id, period="7d",
    )

    assert body["assetCount"] == 1
    assert body["tag"]["name"] == "produccion"
    assert _hour(body, 9)["value"] == pytest.approx(30.0)


def test_a_fleet_without_any_data_has_no_peak(client, regular_user, auth_headers):
    """Sin ninguna muestra en el periodo, ``peakHour`` es nulo en vez de la hora 0."""
    _, body = _get(client, auth_headers(regular_user), metric="cpuPct", period="24h")

    assert body["peakHour"] is None
    assert all(entry["value"] is None for entry in body["hours"])


def test_another_users_asset_is_not_found(app, client, regular_user, admin_user, auth_headers):
    """Pedir el patrón de un activo ajeno es un 404, como uno que no existe."""
    other_asset = _create_asset(app, admin_user.id, "host-ajeno")

    status, _ = _get(
        client, auth_headers(regular_user),
        metric="cpuPct", scope="asset", assetId=other_asset, period="24h",
    )

    assert status == 404


def test_an_unknown_metric_is_rejected(client, regular_user, auth_headers):
    """Una métrica que no está en el registro es un 400."""
    status, _ = _get(client, auth_headers(regular_user), metric="inventada", period="24h")

    assert status == 400


def test_the_scope_id_must_match_the_scope(client, regular_user, auth_headers):
    """Un id que no corresponde al ámbito se rechaza en vez de ignorarse."""
    status, _ = _get(
        client, auth_headers(regular_user), metric="cpuPct", scope="fleet", tagId=1,
    )

    assert status == 422


def test_the_tag_scope_requires_its_tag(client, regular_user, auth_headers):
    """``scope=tag`` sin ``tagId`` se rechaza."""
    status, _ = _get(client, auth_headers(regular_user), metric="cpuPct", scope="tag")

    assert status == 422


def test_the_pattern_requires_authentication(client):
    """Sin token, 401."""
    response = client.get("/hygeia/stats/hourly-pattern", query_string={"metric": "cpuPct"})

    assert response.status_code == 401
