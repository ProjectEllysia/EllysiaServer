"""Informes de Themis que pertenecen a un escaneo de dominio y no a un escaneo normal.

Un escaneo de exposición cloud vive en ``OsintScan``, no en ``Scan``, porque no
tiene equipo que sondear. Su informe PDF se guarda igualmente como documento de
Themis, colgado de ``osint_scan_id``. Estos tests fijan que un documento tiene
exactamente uno de los dos padres y que los listados y la descarga lo tratan
bien cuando el padre es un escaneo de dominio.
"""

from __future__ import annotations

from datetime import datetime
from unittest import mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.modules.features.themis.model import (
    NmapScan,
    OsintScan,
    OsintScanMode,
    ScanStatus,
    ThemisDocument,
)
from src.modules.features.themis.repositories import (
    OsintScanRepository,
    ScanRepository,
    ThemisReportRepository,
)
from src.modules.features.themis.managers import ThemisReportManager
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.system.taskqueue import TaskQueue

pytestmark = pytest.mark.integration


class _FakeTaskQueue:
    """Doble de la cola que anota el trabajo sin tocar Redis: el test lo ejecuta a mano."""

    def __init__(self) -> None:
        self.submitted: list = []

    def submit(self, **kwargs):
        """Anota el trabajo encolado."""
        self.submitted.append(kwargs)


@pytest.fixture()
def fake_queue():
    """Sustituye la cola compartida por el doble."""
    queue = _FakeTaskQueue()
    with mock.patch.object(TaskQueue, "get_instance", return_value=queue):
        yield queue


@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    """Dirige los PDF generados a un directorio temporal."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))


_OPEN_BUCKET = {"title": "Bucket S3 público: cualquiera puede listar su contenido (datos)",
                "category": "cloud_exposure", "severity": "HIGH", "port": None, "service": "s3:datos",
                "check_id": "lybra:cloud-s3-public-bucket@1", "confirmed": True, "state": "open"}


def _cloud_scan(app, user_id: int, status: str = ScanStatus.FINISHED.value,
                mode: str = OsintScanMode.CLOUD.value) -> int:
    """Guarda un escaneo de dominio de ``example.com`` y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            scan = OsintScan(user_id=user_id, domain="example.com", mode=mode, status=status,
                             finished_at=utcnow_naive(), findings=[_OPEN_BUCKET],
                             parameters={"cloud_resources": ["s3:datos"], "check_subdomains": False})
            OsintScanRepository(uow).save(scan)
            return scan.id


def _document(**parents) -> ThemisDocument:
    """Un documento de Themis sin guardar, con los padres que se le pasen."""
    return ThemisDocument(scan_type="cloud", document_type="themis", filename="", format="pdf",
                          status="running", is_ai_generated=0, **parents)


def test_a_document_can_belong_to_a_domain_scan(app, admin_user):
    osint_scan_id = _cloud_scan(app, admin_user.id)
    with app.app_context():
        with UnitOfWork() as uow:
            ThemisReportRepository(uow).save(_document(osint_scan_id=osint_scan_id, user_id=admin_user.id))
        documents = build_repository(ThemisReportRepository).get_documents_by_osint_scan(osint_scan_id)
        assert [document.osint_scan_id for document in documents] == [osint_scan_id]
        assert documents[0].scan_id is None


def test_a_document_without_any_parent_is_rejected(app, admin_user):
    # El repositorio envuelve el IntegrityError de la restricción en un
    # SQLAlchemyError con el nombre del modelo; lo que importa es que no se guarda.
    with app.app_context():
        with pytest.raises(SQLAlchemyError, match="ck_themisdocument_one_parent"):
            with UnitOfWork() as uow:
                ThemisReportRepository(uow).save(_document(user_id=admin_user.id))


def test_a_document_with_both_parents_is_rejected(app, admin_user):
    osint_scan_id = _cloud_scan(app, admin_user.id)
    with app.app_context():
        with pytest.raises(SQLAlchemyError, match="ck_themisdocument_one_parent"):
            with UnitOfWork() as uow:
                scan = NmapScan(target="10.0.0.9", user_id=admin_user.id, started_at=datetime.now())
                scan.status = ScanStatus.FINISHED.value
                ScanRepository(uow).save(scan)
                ThemisReportRepository(uow).save(_document(
                    scan_id=scan.id, osint_scan_id=osint_scan_id, user_id=admin_user.id))


def test_the_documents_listing_names_the_domain_scan(client, app, admin_user, auth_headers):
    osint_scan_id = _cloud_scan(app, admin_user.id)
    with app.app_context():
        with UnitOfWork() as uow:
            ThemisReportRepository(uow).save(_document(osint_scan_id=osint_scan_id, user_id=admin_user.id))

    response = client.get("/themis/documents?scan_type=cloud", headers=auth_headers(admin_user))

    assert response.status_code == 200
    [listed] = response.get_json()["documents"]
    assert listed["osintScanId"] == osint_scan_id
    assert listed["scanId"] is None
    assert listed["scanType"] == "cloud"


# ------------------------------------------------------ el informe de un escaneo cloud


def test_a_cloud_report_is_generated_in_the_background_and_downloaded(
        client, app, admin_user, auth_headers, fake_queue):
    osint_scan_id = _cloud_scan(app, admin_user.id)
    headers = auth_headers(admin_user)

    response = client.post(f"/themis/osint/{osint_scan_id}/report", headers=headers)
    assert response.status_code == 202, response.get_json()
    document_id = response.get_json()["documentId"]
    [job] = fake_queue.submitted
    assert job["category"] == "themis.report"
    assert job["args"] == (document_id, osint_scan_id)

    # Mientras espera en la cola, el documento se ve en su escaneo sin terminar.
    listed = client.get(f"/themis/osint/{osint_scan_id}/documents", headers=headers).get_json()
    assert [(item["documentId"], item["status"]) for item in listed["documents"]] == [(document_id, "running")]

    # El worker lo genera.
    with app.app_context():
        ThemisReportManager.execute_domain_report_generation(document_id, osint_scan_id)

    listed = client.get(f"/themis/osint/{osint_scan_id}/documents", headers=headers).get_json()
    assert listed["documents"][0]["status"] == "done"
    download = client.get(f"/themis/document/{document_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF")
    assert f"cloud_domain_{osint_scan_id}.pdf" in download.headers["Content-Disposition"]


def test_a_passive_scan_has_no_report(client, app, admin_user, auth_headers, fake_queue):
    osint_scan_id = _cloud_scan(app, admin_user.id, mode=OsintScanMode.PASSIVE.value)

    response = client.post(f"/themis/osint/{osint_scan_id}/report", headers=auth_headers(admin_user))

    assert response.status_code == 400
    assert not fake_queue.submitted


def test_an_unfinished_cloud_scan_has_no_report_yet(client, app, admin_user, auth_headers, fake_queue):
    osint_scan_id = _cloud_scan(app, admin_user.id, status=ScanStatus.RUNNING.value)

    response = client.post(f"/themis/osint/{osint_scan_id}/report", headers=auth_headers(admin_user))

    assert response.status_code == 400
    assert not fake_queue.submitted


def test_another_user_can_neither_ask_for_nor_list_the_report(
        client, app, admin_user, regular_user, auth_headers, fake_queue):
    osint_scan_id = _cloud_scan(app, admin_user.id)
    headers = auth_headers(regular_user)

    assert client.post(f"/themis/osint/{osint_scan_id}/report", headers=headers).status_code in (403, 404)
    assert client.get(f"/themis/osint/{osint_scan_id}/documents", headers=headers).status_code == 404
    assert not fake_queue.submitted
