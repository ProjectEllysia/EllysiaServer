"""
Tests de integración HTTP de ``/hygeia/documents``.

El ciclo de vida en sí (validación, generación, errores, reconciliación) lo
cubre ``test_hygeia_documents.py`` sobre el manager; aquí se comprueba la
superficie HTTP: qué acepta cada ruta, qué códigos devuelve y que un usuario
nunca alcanza los documentos de otro. El trabajo en segundo plano se ejecuta
llamando a su punto de entrada, como haría el worker.
"""

import secrets
from unittest import mock

import pytest

from src.modules.features.hygeia.managers import HygeiaDocumentManager
from src.modules.features.hygeia.model import MonitoredAsset
from src.modules.features.hygeia.repositories import MonitoredAssetRepository
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.system.taskqueue import TaskQueue

pytestmark = pytest.mark.integration


class _FakeTaskQueue:
    """Doble de la cola que anota lo encolado sin tocar Redis."""

    def __init__(self):
        """Empieza sin trabajos encolados."""
        self.submissions = []

    def submit(self, **kwargs):
        """Anota el trabajo."""
        self.submissions.append(kwargs)


@pytest.fixture(autouse=True)
def fake_task_queue():
    """Sustituye la cola compartida por el doble en todo el fichero."""
    fake = _FakeTaskQueue()
    with mock.patch.object(TaskQueue, "get_instance", return_value=fake):
        yield fake


@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    """Dirige los ficheros generados a un directorio temporal."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    return tmp_path


def _create_asset(app, user_id: int, hostname: str = "documented") -> int:
    """Da de alta un activo mínimo del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, status="online", last_seen_at=utcnow_naive(),
                os="linux", user_id=user_id,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _request_inventory(client, headers: dict) -> dict:
    """Pide el PDF del inventario propio y devuelve el documento creado."""
    response = client.post("/hygeia/documents", json={"kind": "inventory-pdf"}, headers=headers)
    assert response.status_code == 202, response.get_json()
    return response.get_json()


class TestCreate:
    def test_a_stats_csv_is_accepted(self, app, client, regular_user, auth_headers, fake_task_queue):
        asset_id = _create_asset(app, regular_user.id)
        response = client.post(
            "/hygeia/documents",
            json={"kind": "stats-csv", "dataset": "summary", "assetId": asset_id,
                  "metrics": ["cpuPct"], "period": "7d"},
            headers=auth_headers(regular_user),
        )

        assert response.status_code == 202
        body = response.get_json()
        assert body["status"] == "pending"
        assert body["parameters"]["durationSeconds"] == 7 * 86400
        assert body["downloadName"] is None
        assert len(fake_task_queue.submissions) == 1

    def test_the_fleet_overview_needs_no_scope(self, client, regular_user, auth_headers):
        response = client.post(
            "/hygeia/documents", json={"kind": "stats-csv", "dataset": "overview"},
            headers=auth_headers(regular_user),
        )
        assert response.status_code == 202

    @pytest.mark.parametrize("payload", [
        {},
        {"kind": "word-document"},
        {"kind": "stats-csv"},
        {"kind": "stats-csv", "dataset": "summary"},
        {"kind": "stats-csv", "dataset": "tag-stats"},
        {"kind": "stats-csv", "dataset": "ranking"},
        {"kind": "stats-csv", "dataset": "ranking", "metric": "netRxBps", "agg": "sum"},
        {"kind": "stats-csv", "dataset": "overview", "period": "forever"},
        {"kind": "inventory-pdf", "scope": "everyone"},
    ])
    def test_an_incomplete_or_invalid_request_is_rejected(
        self, client, regular_user, auth_headers, payload, fake_task_queue,
    ):
        response = client.post("/hygeia/documents", json=payload, headers=auth_headers(regular_user))
        assert response.status_code == 422, response.get_json()
        assert fake_task_queue.submissions == []

    def test_another_users_asset_is_not_found(self, app, client, regular_user, make_user, auth_headers):
        foreign_asset = _create_asset(app, make_user().id)
        response = client.post(
            "/hygeia/documents",
            json={"kind": "stats-csv", "dataset": "summary", "assetId": foreign_asset},
            headers=auth_headers(regular_user),
        )
        assert response.status_code == 404

    def test_the_organization_inventory_without_being_owner_is_forbidden(
        self, client, regular_user, auth_headers,
    ):
        response = client.post(
            "/hygeia/documents", json={"kind": "inventory-pdf", "scope": "organization"},
            headers=auth_headers(regular_user),
        )
        assert response.status_code == 403

    def test_authentication_is_required(self, client):
        assert client.post("/hygeia/documents", json={"kind": "inventory-pdf"}).status_code == 401


class TestReadDownloadDelete:
    def test_the_listing_and_the_detail_show_the_users_documents(
        self, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        document = _request_inventory(client, headers)

        listing = client.get("/hygeia/documents", headers=headers).get_json()
        detail = client.get(f"/hygeia/documents/{document['id']}", headers=headers)

        assert listing["total"] == 1
        assert [item["id"] for item in listing["documents"]] == [document["id"]]
        assert listing["page"] == 1
        assert detail.status_code == 200
        assert detail.get_json()["kind"] == "inventory-pdf"

    def test_the_download_waits_until_the_document_is_done(
        self, client, regular_user, auth_headers,
    ):
        headers = auth_headers(regular_user)
        document = _request_inventory(client, headers)
        path = f"/hygeia/documents/{document['id']}/download"

        assert client.get(path, headers=headers).status_code == 409

        HygeiaDocumentManager.execute_document_generation(document["id"])
        response = client.get(path, headers=headers)

        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        assert "attachment" in response.headers["Content-Disposition"]
        assert "inventario-hygeia-propio-" in response.headers["Content-Disposition"]
        assert response.data.startswith(b"%PDF-")
        assert client.get(f"/hygeia/documents/{document['id']}", headers=headers).get_json()[
            "status"
        ] == "done"

    def test_another_user_cannot_see_download_or_delete_a_document(
        self, client, regular_user, make_user, auth_headers,
    ):
        document = _request_inventory(client, auth_headers(regular_user))
        HygeiaDocumentManager.execute_document_generation(document["id"])
        stranger = auth_headers(make_user())

        assert client.get(f"/hygeia/documents/{document['id']}", headers=stranger).status_code == 404
        assert client.get(
            f"/hygeia/documents/{document['id']}/download", headers=stranger,
        ).status_code == 404
        assert client.delete(f"/hygeia/documents/{document['id']}", headers=stranger).status_code == 404
        assert client.get("/hygeia/documents", headers=stranger).get_json()["total"] == 0

    def test_a_deleted_document_is_gone(self, client, regular_user, auth_headers):
        headers = auth_headers(regular_user)
        document = _request_inventory(client, headers)

        deleted = client.delete(f"/hygeia/documents/{document['id']}", headers=headers)

        assert deleted.status_code == 200
        assert client.get(f"/hygeia/documents/{document['id']}", headers=headers).status_code == 404
