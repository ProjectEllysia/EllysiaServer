"""La inteligencia pasiva de Lybra de punta a punta: endpoint, job, caché y privacidad.

La red está sellada en la suite, así que las dos costuras de red del manager
—la descarga de cada fuente y la consulta DNS— se sustituyen por dobles. Todo
lo demás corre de verdad: la fila ``OsintScan``, la outbox, la caché en base
de datos, el job y la persistencia de los hallazgos de un escaneo Lybra.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional
from unittest import mock

import pytest

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.system.taskqueue import Task, TaskStatus
from src.modules.features.themis.lybra import OsintSource, Service
from src.modules.features.themis.managers import LybraEngineManager, OsintManager
from src.modules.features.themis.managers.lybra import osint as osint_module
from src.modules.features.themis.managers.lybra.osint import _fetch_with_cache, _run_osint_scan
from src.modules.features.themis.model import ScanStatus
from src.modules.features.themis.repositories import (
    OsintScanRepository,
    OsintSourceCacheRepository,
    ScanRepository,
)
import src.modules.features.themis.managers as managers_mod

pytestmark = pytest.mark.integration

CRTSH_PAYLOAD = [
    {"id": 7, "issuer_name": "C=US, O=Let's Encrypt, CN=R11", "common_name": "example.com",
     "name_value": "example.com\nwww.example.com\napi.example.com", "not_before": "2026-01-01T00:00:00"},
]

SHODAN_PAYLOAD = {
    "last_update": "2026-08-01T00:00:00.000000",
    "data": [{"port": 8443, "transport": "tcp", "product": "nginx", "version": "1.18.0",
              "cpe23": ["cpe:2.3:a:f5:nginx:1.18.0"], "timestamp": "2026-08-01T00:00:00.000000"}],
}


class _RecordingTaskQueue:
    """Cola que anota lo que se encola sin ejecutarlo."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit(self, func: Callable, *, name: str = "", category: str = "",
               args: tuple = (), kwargs: Optional[dict] = None,
               external_id: Optional[str] = None, timeout: int = 600) -> Task:
        self.submitted.append({"func": func, "name": name, "category": category,
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


class _RecordingSources:
    """Descarga falsa: responde por fuente y anota cada consulta."""

    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.calls: list[tuple] = []

    def __call__(self, source, query):
        self.calls.append((source, query))
        return self.payloads.get(source)


class _RecordingDns:
    """DNS falso: tabla ``(nombre, tipo) -> valores``; anota cada consulta."""

    def __init__(self, records=None):
        self.records = records or {}
        self.queries: list[tuple] = []

    def __call__(self, name, record_type):
        self.queries.append((name, record_type))
        return self.records.get((name, record_type), [])


@pytest.fixture()
def shodan_enabled(monkeypatch):
    """Shodan encendido y con clave; el resto como viene de fábrica."""
    sources = {
        "crtsh": {"enabled": True, "url": "https://crt.sh/"},
        "shodan": {"enabled": True, "url": "https://api.shodan.io"},
        "censys": {"enabled": False, "url": "https://search.censys.io/api/v2"},
        "securitytrails": {"enabled": False, "url": "https://api.securitytrails.com/v1"},
    }
    monkeypatch.setattr(CR, "lybra_osint_config", lambda: CR.LybraOsintConfig(sources=sources))
    monkeypatch.setenv("LYBRA_SHODAN_API_KEY", "clave-de-prueba")


# ───────────────────────── endpoint

def test_launching_requires_authentication(client):
    assert client.post("/themis/osint", json={"domain": "example.com"}).status_code == 401


def test_launching_requires_the_create_attribute(client, stripped_user, auth_headers):
    resp = client.post("/themis/osint", headers=auth_headers(stripped_user), json={"domain": "example.com"})
    assert resp.status_code == 403


@pytest.mark.parametrize("domain", ["93.184.216.34", "https://example.com", "localhost", "no dominio.com"])
def test_a_value_that_is_not_a_domain_is_rejected(client, admin_user, auth_headers, fake_queue, domain):
    resp = client.post("/themis/osint", headers=auth_headers(admin_user), json={"domain": domain})

    assert resp.status_code == 400
    assert "no es un nombre de dominio válido" in resp.get_json()["error_description"]
    assert fake_queue.submitted == []


def test_invalid_or_too_many_dkim_selectors_are_rejected(client, admin_user, auth_headers, fake_queue):
    bad = client.post("/themis/osint", headers=auth_headers(admin_user),
                      json={"domain": "example.com", "dkimSelectors": ["con espacio"]})
    too_many = client.post("/themis/osint", headers=auth_headers(admin_user),
                           json={"domain": "example.com", "dkimSelectors": [f"s{i}" for i in range(11)]})

    assert bad.status_code == 400
    assert too_many.status_code == 400
    assert fake_queue.submitted == []


def test_launching_queues_a_passive_scan_in_its_own_category(client, app, admin_user, auth_headers, fake_queue):
    resp = client.post("/themis/osint", headers=auth_headers(admin_user),
                       json={"domain": "Example.COM.", "dkimSelectors": ["Google", "s1"]})

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["domain"] == "example.com"
    assert body["mode"] == "passive"
    assert body["status"] == "pending"
    [job] = fake_queue.submitted
    assert job["category"] == "themis.osint"
    assert job["external_id"] == f"themis-osint:{body['osintScanId']}"
    assert job["func"] is OsintManager.execute_osint_scan
    assert tuple(job["args"]) == (body["osintScanId"],)
    with app.app_context():
        with UnitOfWork() as uow:
            scan = OsintScanRepository(uow).get_by_id(body["osintScanId"])
            assert scan.parameters == {"dkim_selectors": ["google", "s1"]}


# ───────────────────────── el job

def _create_scan(app, user_id: int, domain: str = "example.com", selectors=None) -> int:
    with app.app_context():
        return OsintManager(task_queue=_RecordingTaskQueue()).create_passive_scan(
            user_id, domain, selectors).id


def test_the_job_stores_what_the_sources_know_and_serves_it(client, app, admin_user, auth_headers):
    scan_id = _create_scan(app, admin_user.id)
    download = _RecordingSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})
    dns = _RecordingDns({("example.com", "TXT"): ["v=spf1 -all"],
                         ("_dmarc.example.com", "TXT"): ["v=DMARC1; p=reject"]})

    with app.app_context():
        _run_osint_scan(scan_id, download=download, lookup_records=dns)

    resp = client.get(f"/themis/osint/{scan_id}", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "finished"
    assert [item["name"] for item in body["subdomains"]] == ["api.example.com", "example.com", "www.example.com"]
    outcomes = {status["source"]: status["outcome"] for status in body["sources"]}
    # De fábrica sólo crt.sh está encendida: las de pago no se consultan.
    assert outcomes == {"crtsh": "ok", "shodan": "disabled", "censys": "disabled",
                        "securitytrails": "disabled"}
    assert {source for source, _ in download.calls} == {OsintSource.CERTIFICATE_TRANSPARENCY}

    passive = [finding for finding in body["findings"] if finding["category"] == "passive_exposure"]
    assert len(passive) == 3
    assert all(finding["qod"] == 25 and finding["confirmed"] is False for finding in passive)
    assert all(finding["provenance"]["source"] == "crtsh" for finding in passive)
    assert all(finding["provenance"]["observedAt"] == "2026-01-01T00:00:00Z" for finding in passive)
    assert all(finding["provenance"]["ageDays"] is not None for finding in passive)

    dns_checks = {check["check"]: check["status"] for check in body["dnsChecks"]}
    assert dns_checks["spf"] == "passed"
    assert dns_checks["dmarc"] == "passed"
    assert dns_checks["caa"] == "failed"
    assert dns_checks["dkim"] == "not_applicable"
    dns_findings = {finding["checkId"] for finding in body["findings"] if finding["category"] == "dns_hygiene"}
    assert dns_findings == {"lybra:dns-caa-missing@1"}


def test_the_job_checks_only_the_dkim_selectors_it_was_given(app, admin_user):
    scan_id = _create_scan(app, admin_user.id, selectors=["s1"])
    dns = _RecordingDns()

    with app.app_context():
        _run_osint_scan(scan_id, download=_RecordingSources(), lookup_records=dns)

    assert [name for name, _ in dns.queries if "_domainkey" in name] == ["s1._domainkey.example.com"]


def test_a_crashing_source_does_not_fail_the_scan(app, admin_user):
    scan_id = _create_scan(app, admin_user.id)

    def failing_download(source, query):
        raise ConnectionError("sin red")

    with app.app_context():
        _run_osint_scan(scan_id, download=failing_download, lookup_records=_RecordingDns())
        scan = OsintManager(task_queue=_RecordingTaskQueue()).get_scan(scan_id, admin_user.id)

    assert scan["status"] == "finished"
    assert scan["sources"][0] == {"source": "crtsh", "label": "Certificate Transparency (crt.sh)",
                                  "outcome": "failed", "retrievedAt": None, "cached": False,
                                  "detail": "ConnectionError"}


def test_another_user_cannot_read_a_passive_scan(client, app, admin_user, regular_user, auth_headers):
    scan_id = _create_scan(app, admin_user.id)

    resp = client.get(f"/themis/osint/{scan_id}", headers=auth_headers(regular_user))

    assert resp.status_code == 404


def test_the_list_shows_the_user_scans_newest_first(client, app, admin_user, auth_headers):
    first = _create_scan(app, admin_user.id, "example.com")
    second = _create_scan(app, admin_user.id, "example.org")

    resp = client.get("/themis/osint", headers=auth_headers(admin_user))

    assert resp.status_code == 200
    results = resp.get_json()["results"]
    assert [item["osintScanId"] for item in results] == [second, first]
    assert "findings" not in results[0]


def test_an_orphaned_passive_scan_is_closed_at_startup(app, admin_user, fake_queue):
    scan_id = _create_scan(app, admin_user.id)

    with app.app_context():
        fixed = OsintManager.reconcile_orphaned_scans()
        with UnitOfWork() as uow:
            scan = OsintScanRepository(uow).get_by_id(scan_id)
            status, reason = scan.status, scan.failure_reason

    assert fixed == 1
    assert (status, reason) == (ScanStatus.FAILED.value, "orphaned")


# ───────────────────────── caché

def test_a_cached_answer_is_reused_within_its_ttl_and_refreshed_after_it(app):
    download = _RecordingSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})

    with app.app_context():
        first = _fetch_with_cache(OsintSource.CERTIFICATE_TRANSPARENCY, "example.com", download)
        second = _fetch_with_cache(OsintSource.CERTIFICATE_TRANSPARENCY, "example.com", download)

        assert len(download.calls) == 1
        assert first.was_cached is False
        assert second.was_cached is True
        assert second.payload == CRTSH_PAYLOAD
        # Desde la caché, la fecha es la de la descarga original: la que dice
        # cuán viejo es el dato.
        assert second.retrieved_at == first.retrieved_at

        ttl_hours = CR.lybra_osint_config().ttl_hours
        with UnitOfWork() as uow:
            entry = OsintSourceCacheRepository(uow).get_entry("crtsh", "example.com")
            entry.fetched_at = entry.fetched_at - timedelta(hours=ttl_hours, minutes=1)

        third = _fetch_with_cache(OsintSource.CERTIFICATE_TRANSPARENCY, "example.com", download)

    assert len(download.calls) == 2
    assert third.was_cached is False
    assert third.retrieved_at > first.retrieved_at


def test_a_failed_download_is_never_cached(app):
    def failing_download(source, query):
        raise ConnectionError("sin red")

    with app.app_context():
        with pytest.raises(ConnectionError):
            _fetch_with_cache(OsintSource.CERTIFICATE_TRANSPARENCY, "example.com", failing_download)
        with UnitOfWork() as uow:
            assert OsintSourceCacheRepository(uow).get_entry("crtsh", "example.com") is None


# ───────────────────────── enriquecimiento de un escaneo Lybra

def _unidentified_service() -> list:
    # Un puerto abierto del que el motor no sabe el producto: el hueco que el
    # enriquecimiento viene a cubrir.
    return [Service(port=8443, protocol="tcp", name="https-alt")]


def _run_lybra_payload_scan(app, user_id: int, osint_enrichment: bool):
    with app.app_context():
        manager = LybraEngineManager()
        scan = manager._create_scan_record(target="93.184.216.34", user_id=user_id)
        manager._run_lybra(scan.id, services_payload=_unidentified_service(),
                           osint_enrichment=osint_enrichment)
        with UnitOfWork() as uow:
            repo = ScanRepository(uow)
            findings = repo.get_findings_by_scan(scan.id)
            evidence = {finding.id: repo.get_evidence_for_finding(finding.id) for finding in findings}
            status = repo.get_by_id(scan.id).status
    return findings, evidence, status


def test_without_the_flag_a_lybra_scan_asks_no_third_party(app, admin_user, monkeypatch, shodan_enabled):
    download, dns = _RecordingSources({OsintSource.SHODAN: SHODAN_PAYLOAD}), _RecordingDns()
    monkeypatch.setattr(osint_module, "_download_from_source", download)
    monkeypatch.setattr(osint_module, "_lookup_dns_records", dns)

    findings, _, status = _run_lybra_payload_scan(app, admin_user.id, osint_enrichment=False)

    assert status == ScanStatus.FINISHED.value
    assert download.calls == []
    assert dns.queries == []
    assert not [finding for finding in findings if finding.category == "passive_exposure"]


def test_with_the_flag_a_lybra_scan_gets_a_suggested_cpe_with_its_provenance(
        app, admin_user, monkeypatch, shodan_enabled):
    download = _RecordingSources({OsintSource.SHODAN: SHODAN_PAYLOAD})
    monkeypatch.setattr(osint_module, "_download_from_source", download)
    monkeypatch.setattr(osint_module, "_lookup_dns_records", _RecordingDns())

    findings, evidence, status = _run_lybra_payload_scan(app, admin_user.id, osint_enrichment=True)

    assert status == ScanStatus.FINISHED.value
    assert download.calls == [(OsintSource.SHODAN, "93.184.216.34")]
    [suggestion] = [finding for finding in findings if finding.category == "passive_exposure"]
    assert suggestion.check_id == "lybra:osint-suggested-cpe@1"
    assert suggestion.cpe == "cpe:2.3:a:f5:nginx:1.18.0:*:*:*:*:*:*:*"
    assert suggestion.cpe_resolved is False
    assert suggestion.confirmed is False
    assert suggestion.qod == 25
    assert "Shodan" in suggestion.title and "sin confirmar por Lybra" in suggestion.title
    [record] = evidence[suggestion.id]
    assert record.kind == "osint_record"
    assert record.payload["source"] == "shodan"
    assert record.payload["observedAt"] == "2026-08-01T00:00:00Z"
    # Una sugerencia de un tercero no es una detección: ningún CVE sale de ella.
    assert not [finding for finding in findings if finding.cve_ids]


def test_a_lybra_scan_of_a_private_target_never_asks_a_third_party(app, admin_user, monkeypatch, shodan_enabled):
    download = _RecordingSources({OsintSource.SHODAN: SHODAN_PAYLOAD})
    monkeypatch.setattr(osint_module, "_download_from_source", download)

    with app.app_context():
        manager = LybraEngineManager()
        scan = manager._create_scan_record(target="10.0.0.5", user_id=admin_user.id)
        manager._run_lybra(scan.id, services_payload=_unidentified_service(), osint_enrichment=True)

    assert download.calls == []


def test_the_lybra_endpoint_threads_the_osint_flag(client, admin_user, auth_headers, monkeypatch):
    captured = []
    monkeypatch.setattr(LybraEngineManager, "run_scan", lambda self, **kwargs: captured.append(kwargs) or 1)

    client.post("/themis/lybra", headers=auth_headers(admin_user), json={"target": "8.8.8.8"})
    client.post("/themis/lybra", headers=auth_headers(admin_user),
                json={"target": "8.8.8.8", "osintEnrichment": True})

    assert [kwargs["osint_enrichment"] for kwargs in captured] == [False, True]

