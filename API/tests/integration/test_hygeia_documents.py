"""
Tests del ciclo de vida de los documentos de Hygeia generados en segundo plano.

Pedir un documento lo valida en el acto y lo deja en ``pending`` con su trabajo
encolado; el worker lo genera y lo deja en ``done`` o ``error``. Aquí la cola es
un doble que anota lo encolado, y el trabajo se ejecuta llamando a mano a su
punto de entrada, que es lo mismo que haría el worker.

Los ficheros se escriben en un directorio temporal (``OUTPUT_DIR``), nunca en
el ``data/`` del repositorio.
"""

import csv
import os
import secrets
from datetime import timedelta
from unittest import mock

import pytest

from src.modules.accounts.model import Organization, OrganizationMember
from src.modules.features.hygeia.exceptions import (
    AssetNotFoundError,
    InvalidDocumentRequestError,
    OrganizationScopeNotAllowedError,
    UnknownMetricError,
)
from src.modules.features.hygeia.managers import HygeiaDocumentManager
from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    HygeiaDocumentRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive
from src.modules.shared._exceptions import DocumentNotFoundError, DocumentNotReadyError
from src.modules.system.taskqueue import TaskQueue
from src.modules.users.repositories import UserRepository

pytestmark = pytest.mark.integration

_DAY = timedelta(hours=24)


class _FakeTaskQueue:
    """Doble de la cola: anota lo encolado y dice si un trabajo sigue vivo.

    Attributes:
        submissions: Argumentos de cada ``submit``.
        recoverable_external_ids: ``external_id`` que ``is_recoverable`` da
            por vivos.
    """

    def __init__(self):
        """Empieza sin trabajos encolados ni vivos."""
        self.submissions = []
        self.recoverable_external_ids = set()

    def submit(self, **kwargs):
        """Anota el trabajo sin tocar Redis."""
        self.submissions.append(kwargs)

    def is_recoverable(self, external_id, category=None):
        """Vivo solo si el test lo declaró así."""
        return external_id in self.recoverable_external_ids


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


def _create_asset(app, user_id: int, hostname: str) -> int:
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


def _seed_cpu(app, asset_id: int, cpu_pct: float) -> None:
    """Guarda una lectura de CPU de hace diez minutos."""
    with app.app_context():
        with UnitOfWork() as uow:
            instant = utcnow_naive() - timedelta(minutes=10)
            AssetSnapshotRepository(uow).save(AssetSnapshot(
                asset_id=asset_id, collected_at=instant, received_at=instant,
                metrics={}, cpu_pct=cpu_pct,
            ))


def _manager_for(user_handle) -> HygeiaDocumentManager:
    """El manager con el ``User`` real detrás; llamar dentro de ``app.app_context()``."""
    return HygeiaDocumentManager(build_repository(UserRepository).get_by_id(user_handle.id))


def _stored_document(app, document_id: int):
    """Relee el documento de la base de datos."""
    with app.app_context():
        return build_repository(HygeiaDocumentRepository).get_by_id(document_id)


class TestCreation:
    def test_a_stats_csv_is_stored_pending_and_submitted(self, app, regular_user, fake_task_queue):
        asset_id = _create_asset(app, regular_user.id, "Web Producción")
        with app.app_context():
            document = _manager_for(regular_user).create_stats_csv_document(
                "summary", asset_id=asset_id, metric_names=["cpuPct"],
                requested_duration=_DAY, period="24h",
            )

        assert document["status"] == "pending"
        assert document["kind"] == "stats-csv"
        assert document["format"] == "csv"
        assert document["parameters"] == {
            "dataset": "summary", "assetId": asset_id, "scopeLabel": "Web Producción",
            "metrics": ["cpuPct"], "durationSeconds": 86400, "period": "24h",
        }
        [submission] = fake_task_queue.submissions
        assert submission["category"] == "hygeia.report"
        assert submission["external_id"] == f"hygeia-doc:{document['id']}"
        assert submission["args"] == (document["id"],)

    def test_a_stats_pdf_is_stored_pending_and_submitted(self, app, regular_user, fake_task_queue):
        """Misma consulta que el CSV; solo cambian ``kind`` y ``format``."""
        asset_id = _create_asset(app, regular_user.id, "Web Producción")
        with app.app_context():
            document = _manager_for(regular_user).create_stats_pdf_document(
                "summary", asset_id=asset_id, metric_names=["cpuPct"],
                requested_duration=_DAY, period="24h",
            )

        assert document["status"] == "pending"
        assert document["kind"] == "stats-pdf"
        assert document["format"] == "pdf"
        assert document["parameters"] == {
            "dataset": "summary", "assetId": asset_id, "scopeLabel": "Web Producción",
            "metrics": ["cpuPct"], "durationSeconds": 86400, "period": "24h",
        }
        [submission] = fake_task_queue.submissions
        assert submission["category"] == "hygeia.report"

    # Los errores de la petición salen al pedir, no como un documento fallido.
    def test_another_users_asset_is_rejected_before_anything_is_stored(
        self, app, regular_user, make_user, fake_task_queue,
    ):
        foreign_asset = _create_asset(app, make_user().id, "foreign")
        with app.app_context(), pytest.raises(AssetNotFoundError):
            _manager_for(regular_user).create_stats_csv_document(
                "summary", asset_id=foreign_asset, requested_duration=_DAY, period="24h",
            )
        assert fake_task_queue.submissions == []

    def test_an_unknown_metric_is_rejected(self, app, regular_user):
        with app.app_context(), pytest.raises(UnknownMetricError):
            _manager_for(regular_user).create_stats_csv_document(
                "ranking", metric_name="temperature", requested_duration=_DAY, period="24h",
            )

    def test_a_missing_scope_is_a_clear_error(self, app, regular_user):
        with app.app_context(), pytest.raises(InvalidDocumentRequestError):
            _manager_for(regular_user).create_stats_csv_document(
                "summary", requested_duration=_DAY, period="24h",
            )

    def test_the_organization_inventory_requires_being_its_owner(self, app, regular_user):
        with app.app_context(), pytest.raises(OrganizationScopeNotAllowedError):
            _manager_for(regular_user).create_inventory_pdf_document("organization", False)

    def test_a_failed_submission_leaves_the_document_in_error(
        self, app, regular_user, fake_task_queue,
    ):
        fake_task_queue.submit = mock.Mock(side_effect=RuntimeError("Redis caído"))
        with app.app_context(), pytest.raises(RuntimeError):
            _manager_for(regular_user).create_inventory_pdf_document("user", False)
        with app.app_context():
            [document] = build_repository(HygeiaDocumentRepository).get_documents_by_user(
                regular_user.id,
            )
        assert document.status == "error"


class TestGeneration:
    def test_the_stats_csv_is_generated_from_the_summary(
        self, app, regular_user, output_dir,
    ):
        asset_id = _create_asset(app, regular_user.id, "Web Producción")
        _seed_cpu(app, asset_id, 42.0)
        with app.app_context():
            document = _manager_for(regular_user).create_stats_csv_document(
                "summary", asset_id=asset_id, metric_names=["cpuPct"],
                requested_duration=_DAY, period="24h",
            )

        HygeiaDocumentManager.execute_document_generation(document["id"])

        stored = _stored_document(app, document["id"])
        assert stored.status == "done"
        assert stored.generated_at is not None
        assert stored.download_name == "hygeia-summary-web-produccion-24h.csv"
        assert stored.filename.startswith(str(output_dir))
        with open(stored.filename, encoding="utf-8-sig", newline="") as exported:
            [row] = list(csv.DictReader(exported))
        assert row["metric"] == "cpuPct"
        assert float(row["max"]) == 42.0

    def test_the_stats_pdf_is_generated_from_the_summary(self, app, regular_user, output_dir):
        asset_id = _create_asset(app, regular_user.id, "Web Producción")
        _seed_cpu(app, asset_id, 42.0)
        with app.app_context():
            document = _manager_for(regular_user).create_stats_pdf_document(
                "summary", asset_id=asset_id, metric_names=["cpuPct"],
                requested_duration=_DAY, period="24h",
            )

        HygeiaDocumentManager.execute_document_generation(document["id"])

        stored = _stored_document(app, document["id"])
        assert stored.status == "done"
        assert stored.generated_at is not None
        assert stored.download_name == "hygeia-summary-web-produccion-24h.pdf"
        assert stored.filename.startswith(str(output_dir))
        with open(stored.filename, "rb") as generated:
            assert generated.read(5) == b"%PDF-"

    def test_the_inventory_pdf_is_generated(self, app, regular_user):
        _create_asset(app, regular_user.id, "inventoried")
        with app.app_context():
            document = _manager_for(regular_user).create_inventory_pdf_document("user", True)

        HygeiaDocumentManager.execute_document_generation(document["id"])

        stored = _stored_document(app, document["id"])
        assert stored.status == "done"
        assert stored.download_name.startswith("inventario-hygeia-propio-")
        with open(stored.filename, "rb") as generated:
            assert generated.read(5) == b"%PDF-"

    # El activo desaparece entre la petición y la generación.
    def test_a_generation_failure_leaves_the_document_in_error(self, app, regular_user):
        asset_id = _create_asset(app, regular_user.id, "vanishing")
        with app.app_context():
            document = _manager_for(regular_user).create_stats_csv_document(
                "summary", asset_id=asset_id, requested_duration=_DAY, period="24h",
            )
        with app.app_context():
            with UnitOfWork() as uow:
                repo = MonitoredAssetRepository(uow)
                repo.delete(repo.get_by_id(asset_id))

        with pytest.raises(AssetNotFoundError):
            HygeiaDocumentManager.execute_document_generation(document["id"])

        assert _stored_document(app, document["id"]).status == "error"

    def test_a_document_deleted_before_its_job_runs_is_skipped(self, app, regular_user):
        with app.app_context():
            manager = _manager_for(regular_user)
            document = manager.create_inventory_pdf_document("user", False)
            manager.delete_user_document(document["id"])

        HygeiaDocumentManager.execute_document_generation(document["id"])

        assert _stored_document(app, document["id"]) is None


class TestReadingAndDeleting:
    def test_the_file_is_not_served_until_it_is_done(self, app, regular_user):
        with app.app_context():
            manager = _manager_for(regular_user)
            document = manager.create_inventory_pdf_document("user", False)
            with pytest.raises(DocumentNotReadyError):
                manager.get_document_file(document["id"])

        HygeiaDocumentManager.execute_document_generation(document["id"])

        with app.app_context():
            path, download_name, mimetype = _manager_for(regular_user).get_document_file(
                document["id"],
            )
        assert mimetype == "application/pdf"
        assert download_name.endswith(".pdf")
        assert path == _stored_document(app, document["id"]).filename

    def test_another_users_document_is_not_found(self, app, regular_user, make_user):
        with app.app_context():
            document = _manager_for(regular_user).create_inventory_pdf_document("user", False)
            stranger = _manager_for(make_user())
            with pytest.raises(DocumentNotFoundError):
                stranger.get_document(document["id"])
            with pytest.raises(DocumentNotFoundError):
                stranger.delete_user_document(document["id"])

    def test_the_listing_only_has_the_users_documents_newest_first(
        self, app, regular_user, make_user,
    ):
        with app.app_context():
            manager = _manager_for(regular_user)
            first = manager.create_inventory_pdf_document("user", False)
            second = manager.create_inventory_pdf_document("user", True)
            _manager_for(make_user()).create_inventory_pdf_document("user", False)
            documents, total = manager.list_documents(page=1, per_page=10)

        assert total == 2
        assert {document["id"] for document in documents} == {first["id"], second["id"]}

    def test_deleting_removes_the_file(self, app, regular_user):
        with app.app_context():
            document = _manager_for(regular_user).create_inventory_pdf_document("user", False)
        HygeiaDocumentManager.execute_document_generation(document["id"])
        path = _stored_document(app, document["id"]).filename

        with app.app_context():
            _manager_for(regular_user).delete_user_document(document["id"])

        assert _stored_document(app, document["id"]) is None
        assert not os.path.exists(path)


class TestReconciliation:
    def test_unfinished_documents_without_a_live_job_are_marked_as_error(
        self, app, regular_user, fake_task_queue,
    ):
        with app.app_context():
            manager = _manager_for(regular_user)
            orphan = manager.create_inventory_pdf_document("user", False)
            alive = manager.create_inventory_pdf_document("user", False)
        fake_task_queue.recoverable_external_ids.add(f"hygeia-doc:{alive['id']}")

        with app.app_context():
            fixed = HygeiaDocumentManager.reconcile_orphaned_documents()

        assert fixed == 1
        assert _stored_document(app, orphan["id"]).status == "error"
        assert _stored_document(app, alive["id"]).status == "pending"


def _create_organization(app, owner_id: int) -> None:
    """Crea una organización de la que el usuario es dueño, sin pasar por la facturación."""
    with app.app_context():
        with UnitOfWork() as uow:
            organization = Organization(
                name="Acme", slug=f"acme-{secrets.token_hex(3)}", owner_user_id=owner_id,
            )
            uow.session.add(organization)
            uow.session.flush()
            uow.session.add(OrganizationMember(
                organization_id=organization.id, user_id=owner_id, member_role="owner",
            ))


def test_the_owner_can_request_the_organization_inventory(app, regular_user, fake_task_queue):
    _create_organization(app, regular_user.id)
    with app.app_context():
        document = _manager_for(regular_user).create_inventory_pdf_document("organization", True)
    assert document["parameters"] == {"scope": "organization", "includeSoftware": True}
    assert len(fake_task_queue.submissions) == 1
