"""Informes de Themis que pertenecen a un escaneo de dominio y no a un escaneo normal.

Un escaneo de exposición cloud vive en ``OsintScan``, no en ``Scan``, porque no
tiene equipo que sondear. Su informe PDF se guarda igualmente como documento de
Themis, colgado de ``osint_scan_id``. Estos tests fijan que un documento tiene
exactamente uno de los dos padres y que los listados y la descarga lo tratan
bien cuando el padre es un escaneo de dominio.
"""

from __future__ import annotations

from datetime import datetime

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
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _cloud_scan(app, user_id: int, status: str = ScanStatus.FINISHED.value) -> int:
    """Guarda un escaneo cloud terminado de ``example.com`` y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            scan = OsintScan(user_id=user_id, domain="example.com", mode=OsintScanMode.CLOUD.value,
                             status=status, finished_at=utcnow_naive(), findings=[])
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
