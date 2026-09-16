"""
Tests de integración HTTP de la tendencia de disco
(``GET /hygeia/assets/<id>/stats/disk-trend``).

La cuenta en sí (mínimos cuadrados, R², días hasta llenarse) está probada
sobre listas en ``tests/unit/test_hygeia_trend.py``. Lo que se comprueba aquí
es lo que solo se ve de extremo a extremo: que la serie que llega al ajuste es
la correcta según se pida un montaje concreto o el más lleno de cada latido,
que la estimación aparece o se retira según el dato sembrado, y que la ventana
de cada modo es la suya.
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


def _create_asset(app, user_id: int, hostname: str = "host-disco") -> int:
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


def _seed_daily_usage(app, asset_id: int, usages: list, mounts_by_day: list = None) -> None:
    """Un snapshot por día, del más antiguo al de hace una hora.

    ``usages`` son los valores de ``disk_max_pct``, uno por día. ``mounts_by_day``
    permite sembrar además el detalle por montaje del JSONB: una lista de
    ``{mount: usagePct}`` por día, con la misma longitud.
    """
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            latest = utcnow_naive() - timedelta(hours=1)
            total = len(usages)
            for position, usage in enumerate(usages):
                instant = latest - timedelta(days=total - 1 - position)
                metrics = {}
                if mounts_by_day is not None:
                    metrics = {
                        "disk": [
                            {"mount": mount, "usagePct": value}
                            for mount, value in mounts_by_day[position].items()
                        ],
                    }
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant,
                    metrics=metrics, disk_max_pct=usage,
                ))


def _get(client, asset_id: int, headers: dict, **query) -> tuple:
    """Hace el GET de la tendencia y devuelve ``(status, cuerpo)``."""
    response = client.get(
        f"/hygeia/assets/{asset_id}/stats/disk-trend", query_string=query, headers=headers,
    )
    return response.status_code, response.get_json()


def test_a_disk_filling_steadily_gets_an_estimate(app, client, regular_user, auth_headers):
    """Un disco que sube dos puntos al día y está al 80 % se llena en diez días."""
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(app, asset_id, [72.0, 74.0, 76.0, 78.0, 80.0])

    status, body = _get(client, asset_id, auth_headers(regular_user), period="30d")

    assert status == 200
    assert body["currentPct"] == pytest.approx(80.0)
    assert body["slopePctPerDay"] == pytest.approx(2.0)
    assert body["rSquared"] == pytest.approx(1.0)
    assert body["daysUntilFull"] == pytest.approx(10.0)
    assert body["reason"] is None
    assert body["sampleCount"] == 5


def test_a_flat_disk_gets_no_number_and_says_why(app, client, regular_user, auth_headers):
    """Un disco quieto devuelve ``null`` con la razón, nunca una fecha inventada."""
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(app, asset_id, [70.0, 70.0, 70.0, 70.0])

    _, body = _get(client, asset_id, auth_headers(regular_user), period="30d")

    assert body["daysUntilFull"] is None
    assert body["reason"] == "insufficient_trend"
    assert body["slopePctPerDay"] == pytest.approx(0.0)


def test_an_asset_without_history_gets_no_trend_at_all(app, client, regular_user, auth_headers):
    """Un activo que nunca reportó disco no tiene ni recta que ajustar."""
    asset_id = _create_asset(app, regular_user.id)

    _, body = _get(client, asset_id, auth_headers(regular_user), period="30d")

    assert body["daysUntilFull"] is None
    assert body["reason"] == "insufficient_samples"
    assert body["slopePctPerDay"] is None
    assert body["rSquared"] is None
    assert body["sampleCount"] == 0


def test_a_full_disk_reports_zero_days(app, client, regular_user, auth_headers):
    """Un disco ya al 100 % no tiene días por delante."""
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(app, asset_id, [94.0, 97.0, 100.0])

    _, body = _get(client, asset_id, auth_headers(regular_user), period="30d")

    assert body["daysUntilFull"] == pytest.approx(0.0)
    assert body["reason"] == "already_full"


def test_without_a_mount_the_trend_follows_the_fullest_one(app, client, regular_user, auth_headers):
    """Sin ``mount`` se ajusta sobre ``diskMaxPct``, el montaje más lleno de cada latido."""
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(
        app, asset_id, [80.0, 82.0, 84.0],
        mounts_by_day=[
            {"/": 80.0, "/var": 10.0},
            {"/": 82.0, "/var": 10.0},
            {"/": 84.0, "/var": 10.0},
        ],
    )

    _, body = _get(client, asset_id, auth_headers(regular_user), period="7d")

    assert body["mount"] is None
    assert body["currentPct"] == pytest.approx(84.0)
    assert body["slopePctPerDay"] == pytest.approx(2.0)


def test_a_mount_is_followed_on_its_own_series(app, client, regular_user, auth_headers):
    """Con ``mount`` se ajusta sobre ese montaje, no sobre el más lleno del activo.

    Es el caso que la columna ``diskMaxPct`` esconde: un ``/var`` que se llena
    deprisa mientras ``/``, que es el que marca el máximo, apenas se mueve.
    """
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(
        app, asset_id, [90.0, 90.0, 91.0],
        mounts_by_day=[
            {"/": 90.0, "/var": 50.0},
            {"/": 90.0, "/var": 60.0},
            {"/": 91.0, "/var": 70.0},
        ],
    )

    _, body = _get(client, asset_id, auth_headers(regular_user), mount="/var", period="7d")

    assert body["mount"] == "/var"
    assert body["currentPct"] == pytest.approx(70.0)
    assert body["slopePctPerDay"] == pytest.approx(10.0)
    assert body["daysUntilFull"] == pytest.approx(3.0)


def test_an_unreported_mount_is_empty_and_not_an_error(app, client, regular_user, auth_headers):
    """Un montaje que el activo no reportó da una tendencia vacía, no un 404."""
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(
        app, asset_id, [80.0, 82.0], mounts_by_day=[{"/": 80.0}, {"/": 82.0}],
    )

    status, body = _get(
        client, asset_id, auth_headers(regular_user), mount="/inexistente", period="7d",
    )

    assert status == 200
    assert body["sampleCount"] == 0
    assert body["reason"] == "insufficient_samples"


def test_the_column_mode_can_cover_the_long_window(app, client, regular_user, auth_headers):
    """Sin ``mount`` la ventana es la de estadísticas: 30 días no se recortan."""
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(app, asset_id, [70.0, 75.0])

    _, body = _get(client, asset_id, auth_headers(regular_user), period="30d")

    assert body["isPeriodClipped"] is False


def test_the_mount_mode_clips_to_the_entity_window(app, client, regular_user, auth_headers):
    """Con ``mount`` se lee el JSONB de cada latido, y la ventana se recorta a la corta.

    Leer el detalle por montaje cuesta mucho más que leer una columna, así que
    esas consultas están topadas por ``maxEntityStatsPeriodDays``; pedir 30
    días se recorta y la respuesta lo dice.
    """
    asset_id = _create_asset(app, regular_user.id)
    _seed_daily_usage(app, asset_id, [70.0, 75.0], mounts_by_day=[{"/": 70.0}, {"/": 75.0}])

    _, body = _get(client, asset_id, auth_headers(regular_user), mount="/", period="30d")

    assert body["isPeriodClipped"] is True


def test_another_users_asset_is_not_found(app, client, regular_user, admin_user, auth_headers):
    """La tendencia de un activo ajeno es un 404, como la de uno que no existe."""
    other_asset = _create_asset(app, admin_user.id, "host-ajeno")

    status, _ = _get(client, other_asset, auth_headers(regular_user), period="7d")

    assert status == 404


def test_the_trend_requires_authentication(app, client, regular_user):
    """Sin token, 401."""
    asset_id = _create_asset(app, regular_user.id)

    response = client.get(f"/hygeia/assets/{asset_id}/stats/disk-trend")

    assert response.status_code == 401
