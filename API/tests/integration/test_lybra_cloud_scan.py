"""La exposición cloud de Lybra de punta a punta: autorización, endpoint, job y consulta.

La red está sellada en la suite, así que las dos costuras de red del job —la
petición HTTP y la resolución de CNAME— se sustituyen por dobles. Todo lo demás
corre de verdad: el registro de objetivos autorizados, la fila ``OsintScan``, la
outbox y la persistencia de los hallazgos.
"""

from __future__ import annotations

from typing import Callable, Optional
from unittest import mock

import pytest

from src.modules.features.themis.lybra import Response
from src.modules.features.themis.managers import AuthorizedTargetManager, CloudScanManager
from src.modules.features.themis.managers.lybra.cloud import _run_cloud_scan
from src.modules.features.themis.model import OsintScanMode, ScanStatus
from src.modules.features.themis.repositories import OsintScanRepository
from src.modules.infrastructure import UnitOfWork
from src.modules.system.taskqueue import Task, TaskStatus
import src.modules.features.themis.managers as managers_mod

pytestmark = pytest.mark.integration

_BUCKET_LISTING = "<ListBucketResult><Name>b</Name></ListBucketResult>"
_GITHUB_404 = "There isn't a GitHub Pages site here"


class _RecordingTaskQueue:
    """Cola que anota lo que se encola sin ejecutarlo."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit(self, func: Callable, *, name: str = "", category: str = "",
               args: tuple = (), kwargs: Optional[dict] = None,
               external_id: Optional[str] = None, timeout: int = 600) -> Task:
        self.submitted.append({"func": func, "category": category,
                               "external_id": external_id, "args": args})
        return Task(id=name, name=name, category=category, external_id=external_id,
                    status=TaskStatus.PENDING)

    def get_task_by_external_id(self, external_id: str, category: Optional[str] = None):
        return None

    def is_recoverable(self, external_id: str, category: Optional[str] = None) -> bool:
        return False

    def cancel(self, task_id: str) -> bool: return True
    def get_task(self, task_id: str): return None
    def update_progress(self, task_id: str, progress: int) -> None: pass
    def is_cancelled(self, task_id: str) -> bool: return False
    def clear_cancel_signal(self, task_id: str) -> None: pass


@pytest.fixture()
def fake_queue():
    queue = _RecordingTaskQueue()
    with mock.patch.object(managers_mod.TaskQueue, "get_instance", return_value=queue):
        yield queue


def _authorize(app, user_id: int, *targets: str) -> None:
    with app.app_context():
        for target in targets:
            AuthorizedTargetManager().add(user_id, target)


class _Network:
    """Red falsa: responde por `(host, ruta)` y por CNAME, y anota lo que se pidió."""

    def __init__(self, responses=None, cnames=None):
        self.responses = responses or {}
        self.cnames = cnames or {}
        self.requested: list[tuple] = []

    def fetch(self, host, port, path):
        self.requested.append((host, path))
        return self.responses.get((host, path))

    def resolve_cname(self, name):
        return self.cnames.get(name)


def _create(app, user_id: int, domain="example.com", resources=None, check_subdomains=True) -> int:
    with app.app_context():
        return CloudScanManager(task_queue=_RecordingTaskQueue()).create_cloud_scan(
            user_id, domain, resources, check_subdomains).id


def _run(app, scan_id: int, network: _Network) -> None:
    with app.app_context():
        _run_cloud_scan(scan_id, fetch=network.fetch, resolve_cname=network.resolve_cname)


# ───────────────────────── endpoint y autorización

def test_launching_requires_authentication(client):
    assert client.post("/themis/cloud", json={"domain": "example.com"}).status_code == 401


def test_launching_requires_the_create_attribute(client, stripped_user, auth_headers):
    resp = client.post("/themis/cloud", headers=auth_headers(stripped_user), json={"domain": "example.com"})
    assert resp.status_code == 403


def test_an_unauthorized_resource_rejects_the_whole_request(client, app, admin_user, auth_headers, fake_queue):
    _authorize(app, admin_user.id, "example.com")

    resp = client.post("/themis/cloud", headers=auth_headers(admin_user), json={
        "domain": "example.com", "cloudResources": ["s3:no-autorizado"]})

    assert resp.status_code == 403
    assert fake_queue.submitted == []


def test_subdomains_of_an_unauthorized_domain_are_not_touched(client, admin_user, auth_headers, fake_queue):
    resp = client.post("/themis/cloud", headers=auth_headers(admin_user), json={"domain": "example.com"})

    assert resp.status_code == 403
    assert fake_queue.submitted == []


def test_a_sibling_domain_is_not_covered_by_an_authorized_one(client, app, admin_user, auth_headers, fake_queue):
    _authorize(app, admin_user.id, "example.com")

    resp = client.post("/themis/cloud", headers=auth_headers(admin_user), json={"domain": "evil-example.com"})

    assert resp.status_code == 403


@pytest.mark.parametrize("payload", [
    {"domain": "example.com", "cloudResources": ["s3:X"], "checkSubdomains": False},          # inválido
    {"domain": "example.com", "cloudResources": [], "checkSubdomains": False},                # nada que hacer
    {"domain": "no es dominio", "cloudResources": ["s3:mi-bucket"]},
])
def test_invalid_requests_are_rejected_before_queuing(client, app, admin_user, auth_headers, fake_queue, payload):
    _authorize(app, admin_user.id, "example.com")

    resp = client.post("/themis/cloud", headers=auth_headers(admin_user), json=payload)

    assert resp.status_code == 400
    assert fake_queue.submitted == []


def test_more_resources_than_the_cap_are_rejected_by_the_schema(client, app, admin_user, auth_headers, fake_queue):
    _authorize(app, admin_user.id, "example.com")

    resp = client.post("/themis/cloud", headers=auth_headers(admin_user), json={
        "domain": "example.com", "cloudResources": [f"s3:bucket-{n:02d}" for n in range(26)]})

    assert resp.status_code == 422
    assert fake_queue.submitted == []


def test_launching_queues_a_cloud_scan_on_the_osint_queue(client, app, admin_user, auth_headers, fake_queue):
    _authorize(app, admin_user.id, "example.com", "s3:mi-bucket")

    resp = client.post("/themis/cloud", headers=auth_headers(admin_user), json={
        "domain": "Example.COM.", "cloudResources": ["S3:Mi-Bucket", "s3:mi-bucket"]})

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["mode"] == OsintScanMode.CLOUD.value and body["status"] == "pending"
    [job] = fake_queue.submitted
    assert job["category"] == "themis.osint"
    assert job["external_id"] == f"themis-osint:{body['osintScanId']}"
    assert job["func"] is CloudScanManager.execute_cloud_scan
    with app.app_context():
        with UnitOfWork() as uow:
            scan = OsintScanRepository(uow).get_by_id(body["osintScanId"])
            # Repetidos y en mayúsculas se canonizan y se funden.
            assert scan.parameters == {"cloud_resources": ["s3:mi-bucket"], "check_subdomains": True}


# ───────────────────────── el job

def test_the_job_reports_a_public_bucket_and_a_dangling_subdomain(client, app, admin_user, auth_headers):
    _authorize(app, admin_user.id, "example.com", "s3:mi-bucket")
    scan_id = _create(app, admin_user.id, resources=["s3:mi-bucket"])
    network = _Network(
        responses={("mi-bucket.s3.amazonaws.com", "/"): Response(200, _BUCKET_LISTING, {}),
                   ("example.com", "/"): Response(404, _GITHUB_404, {})},
        cnames={"example.com": "usuario.github.io."})

    _run(app, scan_id, network)

    body = client.get(f"/themis/osint/{scan_id}", headers=auth_headers(admin_user)).get_json()
    assert body["status"] == "finished" and body["mode"] == "cloud"
    assert {finding["checkId"] for finding in body["findings"]} == {
        "lybra:cloud-s3-public-bucket@1", "lybra:cloud-takeover-github-pages@1"}
    assert all(finding["category"] == "cloud_exposure" for finding in body["findings"])


def test_a_private_bucket_and_a_healthy_domain_produce_no_findings(client, app, admin_user, auth_headers):
    _authorize(app, admin_user.id, "example.com", "s3:mi-bucket")
    scan_id = _create(app, admin_user.id, resources=["s3:mi-bucket"])
    network = _Network(responses={("mi-bucket.s3.amazonaws.com", "/"): Response(403, "AccessDenied", {})})

    _run(app, scan_id, network)

    body = client.get(f"/themis/osint/{scan_id}", headers=auth_headers(admin_user)).get_json()
    assert body["status"] == "finished" and body["findings"] == []


def test_authorization_withdrawn_before_the_job_runs_leaves_the_resource_untouched(app, admin_user):
    _authorize(app, admin_user.id, "example.com", "s3:mi-bucket")
    scan_id = _create(app, admin_user.id, resources=["s3:mi-bucket"])
    with app.app_context():
        for entry in AuthorizedTargetManager().list(admin_user.id):
            AuthorizedTargetManager().remove(entry.id, admin_user.id)
    network = _Network(responses={("mi-bucket.s3.amazonaws.com", "/"): Response(200, _BUCKET_LISTING, {})})

    _run(app, scan_id, network)

    # Ni el bucket ni el dominio se tocaron, y el escaneo terminó limpio.
    assert network.requested == []
    with app.app_context():
        with UnitOfWork() as uow:
            scan = OsintScanRepository(uow).get_by_id(scan_id)
            assert scan.status == ScanStatus.FINISHED.value and scan.findings == []


def test_the_subdomains_of_a_previous_passive_scan_are_checked_and_no_names_are_invented(app, admin_user):
    _authorize(app, admin_user.id, "example.com")
    with app.app_context():
        with UnitOfWork() as uow:
            from src.modules.features.themis.model import OsintScan
            from src.modules.shared import utcnow_naive
            OsintScanRepository(uow).save(OsintScan(
                user_id=admin_user.id, domain="example.com", mode=OsintScanMode.PASSIVE.value,
                status=ScanStatus.FINISHED.value, finished_at=utcnow_naive(),
                subdomains=[{"name": "blog.example.com"}, {"name": "example.com"}]))
    scan_id = _create(app, admin_user.id)
    network = _Network(
        responses={("blog.example.com", "/"): Response(404, _GITHUB_404, {})},
        cnames={"blog.example.com": "usuario.github.io"})

    _run(app, scan_id, network)

    with app.app_context():
        with UnitOfWork() as uow:
            scan = OsintScanRepository(uow).get_by_id(scan_id)
            assert [finding["service"] for finding in scan.findings] == ["blog.example.com"]
            assert [record["name"] for record in scan.subdomains] == ["example.com", "blog.example.com"]


def test_another_user_cannot_read_a_cloud_scan(client, app, admin_user, regular_user, auth_headers):
    _authorize(app, admin_user.id, "example.com")
    scan_id = _create(app, admin_user.id)

    assert client.get(f"/themis/osint/{scan_id}", headers=auth_headers(regular_user)).status_code == 404


# ───────────────────────── lo que necesita la pantalla

def test_the_detail_says_which_resources_were_declared(client, app, admin_user, auth_headers):
    _authorize(app, admin_user.id, "example.com", "s3:my-bucket")
    scan_id = _create(app, admin_user.id, resources=["s3:my-bucket"], check_subdomains=False)

    body = client.get(f"/themis/osint/{scan_id}", headers=auth_headers(admin_user)).get_json()

    assert body["cloudResources"] == ["s3:my-bucket"]
    assert body["checkSubdomains"] is False


def test_the_list_can_be_narrowed_to_cloud_scans(client, app, admin_user, auth_headers):
    _authorize(app, admin_user.id, "example.com")
    cloud_id = _create(app, admin_user.id)
    with app.app_context():
        with UnitOfWork() as uow:
            from src.modules.features.themis.model import OsintScan
            passive = OsintScan(user_id=admin_user.id, domain="example.com",
                                mode=OsintScanMode.PASSIVE.value, status=ScanStatus.FINISHED.value)
            OsintScanRepository(uow).save(passive)
            passive_id = passive.id
    headers = auth_headers(admin_user)

    only_cloud = client.get("/themis/osint?mode=cloud", headers=headers).get_json()["results"]
    everything = client.get("/themis/osint", headers=headers).get_json()["results"]

    assert [scan["osintScanId"] for scan in only_cloud] == [cloud_id]
    assert {scan["osintScanId"] for scan in everything} == {cloud_id, passive_id}
    assert client.get("/themis/osint?mode=otro", headers=headers).status_code in (400, 422)
