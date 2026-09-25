"""El panel de administración de la base de conocimiento: búsqueda y sincronización manual.

La sincronización manual va a la TaskQueue, así que aquí la cola se sustituye
por una que sólo anota lo que se encola: lo que se comprueba es qué se pide y
a quién se le permite, no la sincronización en sí, que ya cubren los tests de
``KbSyncManager``.
"""

from __future__ import annotations

from typing import Callable, Optional
from unittest import mock

import pytest

from src.modules.infrastructure import UnitOfWork
from src.modules.system.taskqueue import Task, TaskStatus
from src.modules.features.themis.repositories import KbRepository

import src.modules.features.themis.managers as managers_mod

pytestmark = pytest.mark.integration


class _RecordingTaskQueue:
    """Cola que anota los envíos sin ejecutarlos, con tareas «en marcha» a medida."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.tasks: dict[str, Task] = {}

    def submit(self, func: Callable, *, name: str = "", category: str = "",
               args: tuple = (), kwargs: Optional[dict] = None,
               external_id: Optional[str] = None, timeout: int = 600) -> Task:
        self.submitted.append({"func": func, "name": name, "category": category,
                               "external_id": external_id, "args": args})
        return Task(id=name, name=name, category=category, external_id=external_id,
                    status=TaskStatus.PENDING)

    def get_task_by_external_id(self, external_id: str,
                                category: Optional[str] = None) -> Optional[Task]:
        return self.tasks.get(external_id)

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


# ─────────── sincronización manual


def test_an_admin_queues_a_single_source(client, admin_user, auth_headers, fake_queue):
    resp = client.post("/themis/kb/sync", json={"source": "oval"}, headers=auth_headers(admin_user))

    assert resp.status_code == 202
    assert resp.get_json() == {"target": "oval", "queued": True, "runningTarget": None}
    [job] = fake_queue.submitted
    assert job["category"] == "themis.kbsync"
    assert job["external_id"] == "themis-kbsync:oval"
    assert job["args"] == ("oval",)
    assert job["func"] is managers_mod.KbSyncTaskManager.execute_sync


def test_a_second_sync_is_not_queued_while_one_is_running(client, admin_user, auth_headers, fake_queue):
    """«Todo» y «NVD» escribirían las mismas filas a la vez: se dice cuál está
    en marcha y no se encola nada."""
    fake_queue.tasks["themis-kbsync:all"] = Task(
        id="KbSync-all", name="KbSync-all", category="themis.kbsync",
        external_id="themis-kbsync:all", status=TaskStatus.RUNNING)

    resp = client.post("/themis/kb/sync", json={"source": "nvd"}, headers=auth_headers(admin_user))

    assert resp.status_code == 202
    assert resp.get_json() == {"target": "nvd", "queued": False, "runningTarget": "all"}
    assert fake_queue.submitted == []


def test_the_full_nvd_history_cannot_be_requested(client, admin_user, auth_headers, fake_queue):
    resp = client.post("/themis/kb/sync", json={"source": "nvd-backfill"},
                       headers=auth_headers(admin_user))

    assert resp.status_code == 422
    assert fake_queue.submitted == []


def test_a_regular_user_cannot_sync(client, regular_user, auth_headers, fake_queue):
    resp = client.post("/themis/kb/sync", json={"source": "all"}, headers=auth_headers(regular_user))

    assert resp.status_code == 403
    assert fake_queue.submitted == []


def test_the_panel_reads_the_state_of_every_target(client, admin_user, auth_headers, fake_queue):
    fake_queue.tasks["themis-kbsync:kev"] = Task(
        id="KbSync-kev", name="KbSync-kev", category="themis.kbsync",
        external_id="themis-kbsync:kev", status=TaskStatus.RUNNING, progress=0)

    tasks = client.get("/themis/kb/sync", headers=auth_headers(admin_user)).get_json()["tasks"]

    assert set(tasks) == {"all", "nvd", "kev", "epss", "oval"}
    assert tasks["kev"] == {"status": "running", "progress": 0}
    assert tasks["nvd"] == {"status": None, "progress": None}


# ─────────── búsqueda


def test_a_cve_search_brings_every_source(client, app, admin_user, auth_headers):
    with app.app_context():
        with UnitOfWork() as uow:
            repo = KbRepository(uow)
            repo.upsert_cve({"cve_id": "CVE-2024-6387", "cvss_score": 8.1, "severity": "HIGH",
                             "description": "regreSSHion", "source": "nvd"},
                            [{"vendor": "openbsd", "product": "openssh", "exact_version": None,
                              "version_start_including": "8.5", "version_start_excluding": None,
                              "version_end_including": None, "version_end_excluding": "9.8"}])
            repo.upsert_distro_pkg_status({
                "vendor": "ubuntu", "release": "24.04", "package": "openssh",
                "cve_id": "CVE-2024-6387", "fixed_in": "1:9.6p1-3ubuntu13.3", "status": "fixed"})

    body = client.get("/themis/kb/search?query=cve-2024-6387", headers=auth_headers(admin_user)).get_json()

    assert body["kind"] == "cve"
    cve = body["cve"]
    assert cve["cveId"] == "CVE-2024-6387"
    assert cve["cvssScore"] == 8.1
    assert cve["products"] == [{"vendor": "openbsd", "product": "openssh"}]
    assert cve["inKev"] is False
    assert cve["distroStatuses"] == [{"vendor": "ubuntu", "release": "24.04", "package": "openssh",
                                      "status": "fixed", "fixedIn": "1:9.6p1-3ubuntu13.3"}]


def test_an_unknown_cve_says_so(client, admin_user, auth_headers):
    body = client.get("/themis/kb/search?query=CVE-2099-0001", headers=auth_headers(admin_user)).get_json()

    assert body["kind"] == "cve" and body["cve"] is None


def test_any_other_text_searches_products(client, admin_user, auth_headers):
    body = client.get("/themis/kb/search?query=openssh", headers=auth_headers(admin_user)).get_json()

    assert body["kind"] == "product"
    assert isinstance(body["products"], list)
