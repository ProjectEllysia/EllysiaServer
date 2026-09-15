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
