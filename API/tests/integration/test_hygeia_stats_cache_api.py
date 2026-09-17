"""
Tests de integración HTTP de la caché de estadísticas de Hygeia.

Las rutas de estadísticas que usa el panel (resumen de un activo, etiqueta,
ranking y serie) reutilizan un resultado ya calculado mientras no caduque.
Para verlo, estos tests guardan una lectura nueva *después* de la primera
petición: si la segunda no la ve, el resultado salió de la caché.

La suite corta toda conexión a Redis, así que la caché compartida del proceso
se sustituye por una sobre un Redis en memoria (``tests/_redis_doubles.py``).
Sin esa sustitución, todo lo de aquí se calcularía siempre, que es lo que
prueban el resto de tests de estadísticas.
"""

import csv
import io
import secrets
from datetime import timedelta

from unittest import mock

import pytest

from _redis_doubles import InMemoryRedis
from src.modules.features.hygeia.managers import HygeiaDocumentManager
from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset, UserTag
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    HygeiaTagRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import ExpiringCache, UnitOfWork
from src.modules.infrastructure import cache as cache_module
from src.modules.shared import utcnow_naive
from src.modules.system.taskqueue import TaskQueue

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def in_memory_cache(monkeypatch):
    """Sustituye la caché compartida del proceso por una sobre Redis en memoria."""
    fake_redis = InMemoryRedis()
    monkeypatch.setattr(cache_module, "_SHARED_CACHE", ExpiringCache(redis_client=fake_redis))
    return fake_redis


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


def _create_tagged_asset(app, user_id: int, hostname: str) -> tuple:
    """Crea una etiqueta personal con un activo del usuario; devuelve ``(tag_id, asset_id)``."""
    asset_id = _create_asset(app, user_id, hostname)
    with app.app_context():
        with UnitOfWork() as uow:
            tag = UserTag(name=f"tag-{hostname}", color="blue", user_id=user_id)
            HygeiaTagRepository(uow).save(tag)
            asset_repo = MonitoredAssetRepository(uow)
            asset = asset_repo.get_by_id(asset_id)
            asset.tags.append(tag)
            asset_repo.update(asset)
            return tag.id, asset_id


def _seed_cpu(app, asset_id: int, cpu_pct: float, age: timedelta = timedelta(minutes=10)) -> None:
    """Guarda una lectura de CPU del activo con la antigüedad dada."""
    with app.app_context():
        with UnitOfWork() as uow:
            instant = utcnow_naive() - age
            AssetSnapshotRepository(uow).save(AssetSnapshot(
                asset_id=asset_id, collected_at=instant, received_at=instant,
                metrics={}, cpu_pct=cpu_pct,
            ))


def _delete_asset_bypassing_the_manager(app, asset_id: int) -> None:
    """Borra el activo por repositorio, sin la invalidación que haría el manager."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = MonitoredAssetRepository(uow)
            repo.delete(repo.get_by_id(asset_id))


def _get(client, path: str, headers: dict, **query) -> tuple:
    """Hace un GET y devuelve ``(status, cuerpo JSON)``."""
    response = client.get(path, query_string=query, headers=headers)
    return response.status_code, response.get_json()


def _summary_max(client, asset_id: int, headers: dict, **query) -> float:
    """Máximo de CPU del resumen del activo en las últimas 24 h."""
    status, body = _get(
        client, f"/hygeia/assets/{asset_id}/stats/summary", headers,
        metrics="cpuPct", period="24h", **query,
    )
    assert status == 200, body
    return body["metrics"]["cpuPct"]["max"]


class TestSummary:
    def test_the_second_request_does_not_see_a_new_reading(
        self, app, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "cached")
        _seed_cpu(app, asset_id, 10.0)

        assert _summary_max(client, asset_id, headers) == 10.0
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))
        assert _summary_max(client, asset_id, headers) == 10.0

    def test_refresh_recomputes_and_keeps_the_new_result(
        self, app, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "refreshed")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, headers)
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        assert _summary_max(client, asset_id, headers, refresh="true") == 90.0
        assert _summary_max(client, asset_id, headers) == 90.0

    def test_a_different_period_is_a_different_result(
        self, app, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "periods")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, headers)
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        status, body = _get(
            client, f"/hygeia/assets/{asset_id}/stats/summary", headers,
            metrics="cpuPct", period="7d",
        )
        assert status == 200
        assert body["metrics"]["cpuPct"]["max"] == 90.0

    # La comprobación de propiedad va antes de la caché.
    def test_a_deleted_asset_is_not_found_even_with_its_summary_stored(
        self, app, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "deleted")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, headers)
        _delete_asset_bypassing_the_manager(app, asset_id)

        status, _ = _get(
            client, f"/hygeia/assets/{asset_id}/stats/summary", headers,
            metrics="cpuPct", period="24h",
        )
        assert status == 404

    def test_another_user_cannot_read_a_stored_summary(
        self, app, client, regular_user, make_user, auth_headers,
    ):
        asset_id = _create_asset(app, regular_user.id, "private")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, auth_headers(regular_user))

        status, _ = _get(
            client, f"/hygeia/assets/{asset_id}/stats/summary",
            auth_headers(make_user(role="role_user")), metrics="cpuPct", period="24h",
        )
        assert status == 404

    # El CSV se genera en segundo plano con el mismo método del manager, así
    # que aprovecha lo guardado.
    def test_the_csv_export_reuses_the_stored_result(
        self, app, client, regular_user, auth_headers, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "exported")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, headers)
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        with mock.patch.object(TaskQueue, "get_instance", return_value=mock.Mock()):
            created = client.post(
                "/hygeia/documents", headers=headers,
                json={"kind": "stats-csv", "dataset": "summary", "assetId": asset_id,
                      "metrics": ["cpuPct"], "period": "24h"},
            )
        document_id = created.get_json()["id"]
        HygeiaDocumentManager.execute_document_generation(document_id)
        response = client.get(f"/hygeia/documents/{document_id}/download", headers=headers)

        assert response.status_code == 200
        [row] = csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip("﻿")))
        assert float(row["max"]) == 10.0


class TestOtherStats:
    def test_the_ranking_is_stored_per_user(
        self, app, client, regular_user, make_user, auth_headers,
    ):
        other_user = make_user(role="role_user")
        _seed_cpu(app, _create_asset(app, regular_user.id, "mine"), 10.0)
        _seed_cpu(app, _create_asset(app, other_user.id, "theirs"), 20.0)
        query = {"metric": "cpuPct", "period": "24h"}

        _, own = _get(client, "/hygeia/stats/ranking", auth_headers(regular_user), **query)
        _, other = _get(client, "/hygeia/stats/ranking", auth_headers(other_user), **query)

        assert [entry["hostname"] for entry in own["assets"]] == ["mine"]
        assert [entry["hostname"] for entry in other["assets"]] == ["theirs"]

    def test_the_ranking_is_reused(self, app, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        _seed_cpu(app, _create_asset(app, regular_user.id, "first"), 10.0)
        _get(client, "/hygeia/stats/ranking", headers, metric="cpuPct", period="24h")
        _seed_cpu(app, _create_asset(app, regular_user.id, "second"), 20.0)

        _, body = _get(client, "/hygeia/stats/ranking", headers, metric="cpuPct", period="24h")
        assert body["assetsWithData"] == 1

    def test_the_tag_stats_are_reused(self, app, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        tag_id, asset_id = _create_tagged_asset(app, regular_user.id, "tagged")
        _seed_cpu(app, asset_id, 10.0)
        path = f"/hygeia/stats/by-tag/{tag_id}"
        _, first = _get(client, path, headers, metrics="cpuPct", agg="max", period="24h")
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        _, second = _get(client, path, headers, metrics="cpuPct", agg="max", period="24h")
        assert second["metrics"]["cpuPct"] == first["metrics"]["cpuPct"]

    def test_the_series_is_reused_and_refreshable(self, app, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "series")
        _seed_cpu(app, asset_id, 10.0, age=timedelta(minutes=50))
        query = {
            "metric": "cpuPct", "assetIds": str(asset_id), "agg": "avg",
            "bucket": 300, "period": "24h",
        }
        _, first = _get(client, "/hygeia/stats/series", headers, **query)
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        _, reused = _get(client, "/hygeia/stats/series", headers, **query)
        _, refreshed = _get(client, "/hygeia/stats/series", headers, refresh="true", **query)

        assert reused["series"] == first["series"]
        assert len(refreshed["series"][0]["points"]) == len(first["series"][0]["points"]) + 1


class TestInvalidation:
    """Cambiar activos o etiquetas deja sin efecto lo guardado de ese usuario."""

    def test_creating_an_asset_updates_the_ranking(self, app, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        _seed_cpu(app, _create_asset(app, regular_user.id, "existing"), 10.0)
        _get(client, "/hygeia/stats/ranking", headers, metric="cpuPct", period="24h")

        created = client.post("/hygeia/assets", json={"hostname": "brand-new"}, headers=headers)
        assert created.status_code == 201

        _, body = _get(client, "/hygeia/stats/ranking", headers, metric="cpuPct", period="24h")
        assert body["assetCount"] == 2

    def test_deleting_an_asset_updates_the_ranking(self, app, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        _seed_cpu(app, _create_asset(app, regular_user.id, "kept"), 10.0)
        removed_id = _create_asset(app, regular_user.id, "removed")
        _seed_cpu(app, removed_id, 20.0)
        _get(client, "/hygeia/stats/ranking", headers, metric="cpuPct", period="24h")

        assert client.delete(f"/hygeia/assets/{removed_id}", headers=headers).status_code == 200

        _, body = _get(client, "/hygeia/stats/ranking", headers, metric="cpuPct", period="24h")
        assert [entry["hostname"] for entry in body["assets"]] == ["kept"]

    def test_tagging_an_asset_updates_the_tag_stats(self, app, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        tag_id, _ = _create_tagged_asset(app, regular_user.id, "first")
        second_id = _create_asset(app, regular_user.id, "second")
        path = f"/hygeia/stats/by-tag/{tag_id}"
        _, before = _get(client, path, headers, metrics="cpuPct", period="24h")

        tagged = client.put(
            f"/hygeia/assets/{second_id}/tags", json={"tagIds": [tag_id]}, headers=headers,
        )
        assert tagged.status_code == 200

        _, after = _get(client, path, headers, metrics="cpuPct", period="24h")
        assert (before["assetCount"], after["assetCount"]) == (1, 2)

    def test_deleting_a_tag_discards_the_users_stored_stats(
        self, app, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        tag_id, asset_id = _create_tagged_asset(app, regular_user.id, "untagged")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, headers)
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        assert client.delete(f"/hygeia/tags/{tag_id}", headers=headers).status_code == 200

        assert _summary_max(client, asset_id, headers) == 90.0

    def test_another_users_changes_do_not_discard_my_stats(
        self, app, client, regular_user, make_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        asset_id = _create_asset(app, regular_user.id, "stable")
        _seed_cpu(app, asset_id, 10.0)
        _summary_max(client, asset_id, headers)
        _seed_cpu(app, asset_id, 90.0, age=timedelta(minutes=5))

        other_user = make_user(role="role_user")
        client.post("/hygeia/assets", json={"hostname": "elsewhere"}, headers=auth_headers(other_user))

        assert _summary_max(client, asset_id, headers) == 10.0
