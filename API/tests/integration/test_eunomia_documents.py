"""Documentos de Eunomia: se piden, se generan en el worker y los descarga todo el equipo."""

import io
from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_KEY = "security-policy"
_COMPLETE = {"values": {
    "scope": "Toda la empresa.", "objectives": "Proteger los datos\nGarantizar la continuidad",
    "security_officer": "Ana Pérez", "approver": "La dirección",
}}


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def completed(client, owner, auth_headers):
    headers = auth_headers(owner)
    client.put("/organizations/company-profile", headers=headers, json={"legalName": "Acme S.L.", "taxId": "B12345674",
                                                                       "country": "ES"})
    assert client.put(f"/eunomia/templates/{_KEY}/draft", headers=headers, json=_COMPLETE).status_code == 200
    return owner


@pytest.fixture()
def submitted(monkeypatch):
    """Recoge lo que se encola en vez de mandarlo a Redis."""
    calls = []

    class FakeQueue:
        def submit(self, **kwargs):
            calls.append(kwargs)

        def is_recoverable(self, *args, **kwargs):
            return False

    from src.modules.system.taskqueue import TaskQueue
    monkeypatch.setattr(TaskQueue, "get_instance", classmethod(lambda cls: FakeQueue()))
    return calls


def _run_worker(document_id):
    from src.modules.features.eunomia.managers.documents import _run_document_generation

    _run_document_generation(document_id)


def test_requesting_a_document_queues_a_task_in_its_own_category(client, completed, auth_headers, submitted):
    response = client.post(f"/eunomia/templates/{_KEY}/documents", headers=auth_headers(completed), json={"format": "pdf"})

    assert response.status_code == 202, response.get_json()
    assert response.get_json()["status"] == "pending"
    assert [(call["category"], call["external_id"]) for call in submitted] == [
        ("eunomia.report", f"eunomia-doc:{response.get_json()['id']}")]


def test_the_worker_generates_a_pdf_that_can_be_downloaded(app, client, completed, auth_headers, submitted, tmp_path,
                                                           monkeypatch):
    import src.modules.system.config_reading as CR
    monkeypatch.setattr(CR, "verify_directory", lambda directory: tmp_path)
    headers = auth_headers(completed)
    document_id = client.post(f"/eunomia/templates/{_KEY}/documents", headers=headers,
                              json={"format": "pdf"}).get_json()["id"]

    with app.app_context():
        _run_worker(document_id)

    status = client.get(f"/eunomia/documents/{document_id}", headers=headers).get_json()
    assert status["status"] == "done" and status["downloadName"].endswith(".pdf")
    download = client.get(f"/eunomia/documents/{document_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF")


def test_the_same_request_in_word_produces_a_docx(app, client, completed, auth_headers, submitted, tmp_path, monkeypatch):
    import src.modules.system.config_reading as CR
    from docx import Document

    monkeypatch.setattr(CR, "verify_directory", lambda directory: tmp_path)
    headers = auth_headers(completed)
    document_id = client.post(f"/eunomia/templates/{_KEY}/documents", headers=headers,
                              json={"format": "docx"}).get_json()["id"]

    with app.app_context():
        _run_worker(document_id)

    download = client.get(f"/eunomia/documents/{document_id}/download", headers=headers)
    text = "\n".join(p.text for p in Document(io.BytesIO(download.data)).paragraphs)
    assert "Acme S.L." in text and "Ana Pérez" in text


def test_a_document_that_is_not_ready_answers_409(client, completed, auth_headers, submitted):
    headers = auth_headers(completed)
    document_id = client.post(f"/eunomia/templates/{_KEY}/documents", headers=headers,
                              json={"format": "pdf"}).get_json()["id"]

    response = client.get(f"/eunomia/documents/{document_id}/download", headers=headers)

    assert response.status_code == 409


def test_missing_required_fields_block_the_document(client, owner, auth_headers, submitted):
    response = client.post(f"/eunomia/templates/{_KEY}/documents", headers=auth_headers(owner), json={"format": "pdf"})

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "templateIncomplete"
    assert submitted == []


def test_exceeding_the_quota_is_rejected_before_queueing(client, completed, auth_headers, submitted, monkeypatch):
    from src.modules.accounts import QuotaManager
    from src.modules.accounts.exceptions import PlanLimitError

    def refuse(self, *args, **kwargs):
        raise PlanLimitError("eunomia.documents")

    monkeypatch.setattr(QuotaManager, "consume", refuse)

    response = client.post(f"/eunomia/templates/{_KEY}/documents", headers=auth_headers(completed), json={"format": "pdf"})

    assert response.status_code >= 400
    assert submitted == []


def test_a_member_downloads_the_documents_of_the_owner(app, client, completed, regular_user, auth_headers, submitted,
                                                       tmp_path, monkeypatch):
    import src.modules.system.config_reading as CR
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    monkeypatch.setattr(CR, "verify_directory", lambda directory: tmp_path)
    org = client.post("/organizations", headers=auth_headers(completed), json={"name": "Acme"}).get_json()
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=org["id"], user_id=regular_user.id, member_role="member"))
            uow.session.flush()
    document_id = client.post(f"/eunomia/templates/{_KEY}/documents", headers=auth_headers(completed),
                              json={"format": "pdf"}).get_json()["id"]
    with app.app_context():
        _run_worker(document_id)

    listed = client.get("/eunomia/documents", headers=auth_headers(regular_user)).get_json()
    download = client.get(f"/eunomia/documents/{document_id}/download", headers=auth_headers(regular_user))

    assert [item["id"] for item in listed["documents"]] == [document_id]
    assert download.status_code == 200


def test_a_stranger_cannot_see_the_document(client, completed, make_user, auth_headers, submitted):
    document_id = client.post(f"/eunomia/templates/{_KEY}/documents", headers=auth_headers(completed),
                              json={"format": "pdf"}).get_json()["id"]

    response = client.get(f"/eunomia/documents/{document_id}", headers=auth_headers(make_user()))

    assert response.status_code == 404
