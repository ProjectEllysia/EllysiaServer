"""
Tests de integración HTTP de las estadísticas por entidad de un activo: las
que leen el detalle del JSONB ``metrics`` en vez de una columna
(``GET /hygeia/assets/<id>/stats/disks``).

Siembra snapshots directamente por repositorio, igual que
``test_hygeia_stats_api.py``: el suelo de cadencia de la ingesta impide
construir por HTTP una serie con valores e instantes elegidos.
"""

import secrets
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.engine import get_session
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int) -> int:
    """Da de alta un activo mínimo del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname="entity-stats", agent_key_id=secrets.token_hex(8),
                agent_key_hash="dummy", heartbeat_interval_sec=15, status="online",
                last_seen_at=utcnow_naive(), user_id=user_id,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _seed(app, asset_id: int, readings: list) -> None:
    """Guarda un snapshot por cada ``(antigüedad, metrics)``."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            now = utcnow_naive()
            for age, metrics in readings:
                instant = now - age
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant, metrics=metrics,
                ))


def _get(client, path: str, headers: dict, **query) -> tuple:
    """Hace la petición y devuelve ``(status, cuerpo)``."""
    response = client.get(path, query_string=query, headers=headers)
    return response.status_code, response.get_json()


def _disks(*usages) -> dict:
    """Payload con un montaje por ``(mount, usagePct)``."""
    return {"disk": [{"mount": mount, "usagePct": usage} for mount, usage in usages]}


# =============================================================================
# DISCO POR PUNTO DE MONTAJE
# =============================================================================

@pytest.fixture()
def disk_asset(app, regular_user):
    """Un activo con ``/`` estable y ``/var`` llenándose, más un heartbeat de hace diez días."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [
        (timedelta(minutes=30), _disks(("/", 40.0), ("/var", 60.0))),
        (timedelta(minutes=20), _disks(("/", 41.0), ("/var", 75.0))),
        (timedelta(minutes=10), _disks(("/", 40.0), ("/var", 90.0))),
        (timedelta(days=10), _disks(("/", 99.0), ("/var", 99.0))),
    ])
    return asset_id


def test_each_mount_has_its_own_history(client, disk_asset, regular_user, auth_headers):
    """Dos montajes de evolución distinta se resumen por separado, ordenados por nombre."""
    status, body = _get(
        client, f"/hygeia/assets/{disk_asset}/stats/disks", auth_headers(regular_user),
    )

    assert status == 200
    assert [entry["mount"] for entry in body["mounts"]] == ["/", "/var"]
    root, var = (entry["usagePct"] for entry in body["mounts"])
    assert (root["min"], root["max"], root["current"]) == (40.0, 41.0, 40.0)
    assert (var["min"], var["max"], var["current"]) == (60.0, 90.0, 90.0)
    assert var["avg"] == pytest.approx(75.0)
    assert var["sampleCount"] == 3


def test_mount_limits_the_response_to_one_mount(client, disk_asset, regular_user, auth_headers):
    """Con ``mount`` sale solo ese montaje; uno que no existe da una lista vacía."""
    headers = auth_headers(regular_user)
    path = f"/hygeia/assets/{disk_asset}/stats/disks"

    _, body = _get(client, path, headers, mount="/var")
    _, missing = _get(client, path, headers, mount="/mnt/usb")

    assert [entry["mount"] for entry in body["mounts"]] == ["/var"]
    assert missing["mounts"] == []


def test_the_period_is_clipped_to_the_entity_stats_limit(
    client, disk_asset, regular_user, auth_headers,
):
    """30 días se recortan a los 7 de ``maxEntityStatsPeriodDays``: el heartbeat de hace diez no entra."""
    status, body = _get(
        client, f"/hygeia/assets/{disk_asset}/stats/disks", auth_headers(regular_user),
        period="30d",
    )

    assert status == 200
    assert body["isPeriodClipped"] is True
    covered_from = datetime.fromisoformat(body["periodCoveredFrom"].rstrip("Z"))
    covered_to = datetime.fromisoformat(body["periodCoveredTo"].rstrip("Z"))
    assert covered_to - covered_from == timedelta(days=7)
    assert body["mounts"][0]["usagePct"]["max"] == 41.0


def test_disk_stats_of_another_users_asset_are_not_found(
    client, disk_asset, make_user, auth_headers,
):
    """El activo de otro usuario da el mismo 404 que uno inexistente."""
    status, _ = _get(
        client, f"/hygeia/assets/{disk_asset}/stats/disks", auth_headers(make_user()),
    )

    assert status == 404


# =============================================================================
# MONTAJES MÁS LLENOS DEL PARQUE
# =============================================================================

def _seed_columns(app, asset_id: int, readings: list) -> None:
    """Guarda un snapshot por cada ``(antigüedad, columnas)``, con el JSONB vacío."""
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


@pytest.fixture()
def fleet_disks(app, regular_user, make_user):
    """Tres activos del usuario y uno ajeno, cada uno con su último heartbeat distinto."""
    filling = _create_asset(app, regular_user.id)
    steady = _create_asset(app, regular_user.id)
    silent = _create_asset(app, regular_user.id)
    theirs = _create_asset(app, make_user().id)
    _seed_columns(app, filling, [
        (timedelta(hours=2), {"disk_max_pct": 99.0, "disk_max_mount": "/"}),
        (timedelta(minutes=5), {"disk_max_pct": 80.0, "disk_max_mount": "/var"}),
    ])
    _seed_columns(app, steady, [(timedelta(minutes=5), {"disk_max_pct": 50.0, "disk_max_mount": "/"})])
    _seed_columns(app, silent, [(timedelta(minutes=5), {"cpu_pct": 10.0})])
    _seed_columns(app, theirs, [(timedelta(minutes=5), {"disk_max_pct": 99.0, "disk_max_mount": "/"})])
    return filling, steady


def test_the_fullest_mounts_come_from_each_assets_latest_heartbeat(
    client, fleet_disks, regular_user, auth_headers,
):
    """Cuenta el último heartbeat, no el pico histórico; sin dato de disco o ajeno, no entra."""
    filling, steady = fleet_disks

    status, body = _get(client, "/hygeia/stats/disks/fleet", auth_headers(regular_user))

    assert status == 200
    assert body["assetCount"] == 3
    assert body["assetsWithData"] == 2
    assert [(entry["assetId"], entry["mount"], entry["usagePct"]) for entry in body["mounts"]] == [
        (filling, "/var", 80.0), (steady, "/", 50.0),
    ]
    assert body["mounts"][0]["receivedAt"]


def test_the_fullest_mounts_are_cut_to_the_limit(client, fleet_disks, regular_user, auth_headers):
    """``limit`` recorta la lista y deja intacto el recuento de activos con dato."""
    status, body = _get(client, "/hygeia/stats/disks/fleet", auth_headers(regular_user), limit=1)

    assert status == 200
    assert len(body["mounts"]) == 1
    assert body["assetsWithData"] == 2


@pytest.mark.parametrize("limit", [0, 101, "x"])
def test_a_malformed_fleet_disk_limit_is_rejected(client, regular_user, auth_headers, limit):
    """``limit`` va de 1 a 100."""
    status, _ = _get(client, "/hygeia/stats/disks/fleet", auth_headers(regular_user), limit=limit)

    assert status == 422


def test_the_fullest_mounts_never_read_the_jsonb(
    app, client, fleet_disks, regular_user, auth_headers,
):
    """Una sola consulta sobre ``AssetSnapshot``, y sin tocar la columna ``metrics``."""
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    with app.app_context():
        engine = get_session().get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        status, _ = _get(client, "/hygeia/stats/disks/fleet", auth_headers(regular_user))
    finally:
        event.remove(engine, "before_cursor_execute", record)

    snapshot_statements = [statement for statement in statements if "AssetSnapshot" in statement]
    assert status == 200
    assert len(snapshot_statements) == 1
    assert "metrics" not in snapshot_statements[0]


# =============================================================================
# RED POR INTERFAZ
# =============================================================================

def _interfaces(*traffic) -> dict:
    """Payload con una interfaz por ``(iface, rxBytesPerSec, txBytesPerSec)``."""
    return {"network": [
        {"iface": iface, "rxBytesPerSec": received, "txBytesPerSec": sent}
        for iface, received, sent in traffic
    ]}


@pytest.fixture()
def network_asset(app, regular_user):
    """Un activo con ``eth0`` recibiendo mucho, ``wlan0`` enviando y la loopback."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [
        (timedelta(minutes=30), _interfaces(("eth0", 100, 10), ("wlan0", 5, 50), ("lo", 9, 9))),
        (timedelta(minutes=20), _interfaces(("eth0", 200, 10), ("wlan0", 5, 70), ("lo", 9, 9))),
        (timedelta(minutes=10), _interfaces(("eth0", 300, 10), ("lo", 9, 9))),
    ])
    return asset_id


def test_each_interface_has_its_own_history(client, network_asset, regular_user, auth_headers):
    """Dos interfaces se resumen por separado, ordenadas por nombre y sin la loopback."""
    status, body = _get(
        client, f"/hygeia/assets/{network_asset}/stats/network", auth_headers(regular_user),
    )

    assert status == 200
    assert [entry["interface"] for entry in body["interfaces"]] == ["eth0", "wlan0"]
    eth0, wlan0 = body["interfaces"]
    assert (eth0["rxBytesPerSec"]["max"], eth0["rxBytesPerSec"]["avg"]) == (300.0, 200.0)
    assert eth0["txBytesPerSec"]["max"] == 10.0
    assert (wlan0["txBytesPerSec"]["max"], wlan0["txBytesPerSec"]["current"]) == (70.0, 70.0)
    assert wlan0["rxBytesPerSec"]["sampleCount"] == 2


def test_interface_limits_the_response_to_one_interface(
    client, network_asset, regular_user, auth_headers,
):
    """Con ``interface`` sale solo esa; la loopback o una inexistente dan una lista vacía."""
    headers = auth_headers(regular_user)
    path = f"/hygeia/assets/{network_asset}/stats/network"

    _, body = _get(client, path, headers, interface="wlan0")
    _, loopback = _get(client, path, headers, interface="lo")
    _, missing = _get(client, path, headers, interface="eth9")

    assert [entry["interface"] for entry in body["interfaces"]] == ["wlan0"]
    assert loopback["interfaces"] == []
    assert missing["interfaces"] == []


def test_network_stats_of_another_users_asset_are_not_found(
    client, network_asset, make_user, auth_headers,
):
    """El activo de otro usuario da el mismo 404 que uno inexistente."""
    status, _ = _get(
        client, f"/hygeia/assets/{network_asset}/stats/network", auth_headers(make_user()),
    )

    assert status == 404


# =============================================================================
# DESEQUILIBRIO ENTRE NÚCLEOS
# =============================================================================

def _cores(*usages) -> dict:
    """Payload de CPU con el uso de cada núcleo y su media."""
    return {"cpu": {"usagePct": sum(usages) / len(usages), "perCorePct": list(usages)}}


def test_the_core_spread_is_summarized_over_the_period(client, app, regular_user, auth_headers):
    """La distancia entre núcleos de cada heartbeat se resume; un solo núcleo no cuenta."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [
        (timedelta(minutes=40), _cores(10.0, 90.0)),
        (timedelta(minutes=30), _cores(50.0, 50.0, 40.0, 60.0)),
        (timedelta(minutes=20), _cores(30.0)),
        (timedelta(minutes=10), _cores(20.0, 25.0)),
    ])

    status, body = _get(
        client, f"/hygeia/assets/{asset_id}/stats/cpu-cores", auth_headers(regular_user),
    )

    assert status == 200
    spread = body["coreSpreadPct"]
    assert (spread["max"], spread["min"], spread["current"]) == (80.0, 5.0, 5.0)
    assert spread["avg"] == pytest.approx(35.0)
    assert spread["sampleCount"] == 3
    assert body["latestPerCorePct"] == [20.0, 25.0]
    assert body["latestAt"]


def test_without_per_core_data_the_spread_is_empty(client, app, regular_user, auth_headers):
    """Un agente que no manda el uso por núcleo da un resumen vacío, no ceros."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [(timedelta(minutes=10), {"cpu": {"usagePct": 20.0}})])

    status, body = _get(
        client, f"/hygeia/assets/{asset_id}/stats/cpu-cores", auth_headers(regular_user),
    )

    assert status == 200
    assert body["coreSpreadPct"]["sampleCount"] == 0
    assert body["coreSpreadPct"]["max"] is None
    assert body["latestPerCorePct"] == []
    assert body["latestAt"] is None


def test_core_stats_of_another_users_asset_are_not_found(
    client, app, regular_user, make_user, auth_headers,
):
    """El activo de otro usuario da el mismo 404 que uno inexistente."""
    asset_id = _create_asset(app, regular_user.id)

    status, _ = _get(
        client, f"/hygeia/assets/{asset_id}/stats/cpu-cores", auth_headers(make_user()),
    )

    assert status == 404
