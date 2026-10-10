"""Themis aporta a Eunomia el estado de la gestión de vulnerabilidades, sin que Eunomia lo conozca."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/adoptions/nis2/automatic-evidence/RE.6.10"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def adopted(client, owner, auth_headers):
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "nis2"})
    return owner


def _scan(app, user_id, *, days_ago=2, findings=(), status="finished"):
    from src.modules.features.themis.model import Finding, Scan, ScanType
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            scan = Scan(target="10.0.0.1", user_id=user_id, status=status, scan_type=ScanType.LYBRA,
                        finished_at=utcnow_naive() - timedelta(days=days_ago))
            uow.session.add(scan)
            uow.session.flush()
            for state, severity in findings:
                uow.session.add(Finding(scan_id=scan.id, title="x", state=state, severity=severity))
            uow.session.flush()


def _evidence(client, headers, url=_URL):
    return {item["title"]: item for item in client.get(url, headers=headers).get_json()["evidence"]
            if item["providerKey"] == "themis.vulnerability_management"}


def test_without_scans_the_control_says_there_is_no_data(client, adopted, auth_headers):
    found = _evidence(client, auth_headers(adopted))

    assert [item["status"] for item in found.values()] == ["missing"]


def test_a_recent_scan_without_open_criticals_is_fine(app, client, adopted, auth_headers):
    _scan(app, adopted.id, days_ago=3, findings=[("open", "low")])

    found = _evidence(client, auth_headers(adopted))

    assert found["Último escaneo"]["status"] == "ok"
    assert found["Hallazgos críticos abiertos"]["status"] == "ok"
    assert found["Último escaneo"]["link"] == "/themis/escaneos"


def test_open_critical_findings_raise_a_warning(app, client, adopted, auth_headers):
    _scan(app, adopted.id, findings=[("open", "critical"), ("open", "low")])

    found = _evidence(client, auth_headers(adopted))

    assert found["Hallazgos críticos abiertos"]["status"] == "warning"
    assert "1 crítico" in found["Hallazgos críticos abiertos"]["summary"]


def test_false_positives_and_fixed_findings_do_not_count(app, client, adopted, auth_headers):
    _scan(app, adopted.id, findings=[("false_positive", "critical"), ("fixed", "critical"), ("accepted", "critical")])

    found = _evidence(client, auth_headers(adopted))

    assert found["Hallazgos críticos abiertos"]["status"] == "ok"


def test_a_scan_older_than_thirty_days_is_a_warning(app, client, adopted, auth_headers):
    _scan(app, adopted.id, days_ago=45)

    assert _evidence(client, auth_headers(adopted))["Último escaneo"]["status"] == "warning"


def test_only_the_scans_of_the_effective_owner_are_seen(app, client, adopted, make_user, auth_headers):
    _scan(app, make_user().id, findings=[("open", "critical")])

    found = _evidence(client, auth_headers(adopted))

    assert [item["status"] for item in found.values()] == ["missing"]


def test_the_provider_also_serves_the_equivalent_controls_of_other_frameworks(client, adopted, auth_headers):
    headers = auth_headers(adopted)
    client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": "ens"})

    found = _evidence(client, headers, "/eunomia/adoptions/ens/automatic-evidence/op.exp.4")

    assert found
