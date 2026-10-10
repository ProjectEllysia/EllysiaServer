"""La baja borra todo lo de Eunomia y la exportación lo incluye, con los ficheros descifrados."""

import io
import json
import zipfile
from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_PDF = b"%PDF-1.4\nsecreto de la politica\n%%EOF\n"
_TABLES = (
    "EunomiaFrameworkAdoption", "EunomiaControlAssessment", "EunomiaAssessmentEvent",
    "EunomiaEvidence", "EunomiaEvidenceContent", "EunomiaEvidenceLink",
)


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


def _populate(client, headers):
    client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": "nis2"})
    client.put("/eunomia/adoptions/nis2/controls/RE.11.1", headers=headers,
               json={"status": "implemented", "updatedAt": None})
    evidence_id = client.post(
        "/eunomia/evidence", headers=headers, content_type="multipart/form-data",
        data={"file": (io.BytesIO(_PDF), "politica.pdf"), "title": "Política"},
    ).get_json()["id"]
    client.post(f"/eunomia/evidence/{evidence_id}/links", headers=headers,
                json={"frameworkKey": "nis2", "controlIdentifier": "RE.11.1"})


def _counts(app):
    from src.modules.features.eunomia import model
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            return {name: uow.session.query(getattr(model, name)).count() for name in _TABLES}


def test_the_purge_leaves_no_eunomia_row_of_the_owner(app, client, owner, auth_headers):
    from src.modules.features.eunomia.services.user_data import purge_eunomia_data
    from src.modules.infrastructure import unit_of_work

    _populate(client, auth_headers(owner))
    assert all(count >= 1 for count in _counts(app).values())

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            purge_eunomia_data(uow, owner.id)

    assert _counts(app) == {name: 0 for name in _TABLES}


def test_the_export_carries_the_tables_and_the_decrypted_files(app, client, owner, auth_headers, tmp_path):
    from src.modules.infrastructure import unit_of_work
    from src.modules.users.services.data_export import write_export_archive

    _populate(client, auth_headers(owner))
    destination = tmp_path / "export.zip"
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            write_export_archive(uow.session, owner.id, destination, utcnow_naive())

    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        document = json.loads(archive.read("eunomia.json"))
        files = [name for name in names if name.startswith("files/eunomia/evidence/")]
        content = archive.read(files[0])

    assert len(document["framework_adoptions"]) == 1
    assert len(document["control_assessments"]) == 1
    assert len(document["evidence"]) == 1
    assert len(document["evidence_links"]) == 1
    assert len(files) == 1 and files[0].endswith("politica.pdf")
    assert content == _PDF


def test_the_deletion_notice_counts_frameworks_and_evidence(app, client, owner, auth_headers):
    from src.modules.infrastructure import unit_of_work
    from src.modules.users.services.account_deletion import count_deletion_categories

    _populate(client, auth_headers(owner))
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            categories = {item["key"]: item["count"] for item in count_deletion_categories(uow, owner.id)}

    assert categories["complianceFrameworks"] == 1
    assert categories["complianceEvidence"] == 1
