"""El riesgo de movimiento lateral de punta a punta: grupos, análisis y endpoint.

Los hosts, sus escaneos y sus hallazgos se guardan de verdad en la base de datos
de la suite; sólo la resolución de nombres del multi-homed se sustituye por una
tabla, porque la red está sellada.
"""

from datetime import timedelta

import pytest

from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.features.themis.managers import NetworkRiskManager
from src.modules.features.themis.model import Host, LybraScan, ScanStatus
from src.modules.features.themis.repositories import ScanRepository

pytestmark = pytest.mark.integration

_SMB_UNSIGNED = {
    "title": "SMB no exige firma", "category": "network_config", "severity": "HIGH", "port": 445,
    "service": "microsoft-ds", "protocol": "tcp", "source": "lybra",
    "check_id": "lybra:smb-signing-not-required@1", "qod": 99, "confirmed": True, "state": "open",
}


def _add_host(user_id: int, name: str, address: str, findings=(), parent_scan_id=None, age_minutes=5) -> int:
    """Guarda un host con su último escaneo terminado y esos hallazgos; devuelve el id del host."""
    with UnitOfWork() as uow:
        host = Host(hostname=name, ip_address=address, mac_address="00:00:00:00:00:00")
        uow.session.add(host)
        uow.session.flush()
        scan = LybraScan(target=address, user_id=user_id, host_id=host.id, status=ScanStatus.FINISHED.value,
                         started_at=utcnow_naive() - timedelta(minutes=age_minutes),
                         parent_scan_id=parent_scan_id)
        uow.session.add(scan)
        uow.session.flush()
        ScanRepository(uow).persist_findings(scan, [
            {**finding, "dedup_key": f"{name}-{index}"} for index, finding in enumerate(findings)])
        return host.id


def _add_parent(user_id: int) -> int:
    with UnitOfWork() as uow:
        parent = LybraScan(target="10.0.0.0/28", user_id=user_id, status=ScanStatus.FINISHED.value,
                           started_at=utcnow_naive())
        uow.session.add(parent)
        uow.session.flush()
        return parent.id


def _create_group(client, headers, name="dmz", cidr="10.0.0.0/24") -> int:
    resp = client.post("/themis/asset-groups", headers=headers, json={"name": name, "cidr": cidr})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["groupId"]


# ───────────────────────── grupos

def test_groups_require_authentication(client):
    assert client.post("/themis/asset-groups", json={"name": "a", "cidr": "10.0.0.0/24"}).status_code == 401
    assert client.get("/themis/asset-groups").status_code == 401
    assert client.get("/themis/network-risk?groupId=1").status_code == 401


def test_a_group_is_created_with_a_canonical_range_and_listed(client, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    resp = client.post("/themis/asset-groups", headers=headers, json={"name": "  dmz ", "cidr": "10.0.0.7/24"})

    assert resp.status_code == 201 and resp.get_json()["cidr"] == "10.0.0.0/24"
    listing = client.get("/themis/asset-groups", headers=headers).get_json()
    assert [group["name"] for group in listing["results"]] == ["dmz"]


@pytest.mark.parametrize("payload", [
    {"name": "x", "cidr": "no-es-un-rango"}, {"name": "x", "cidr": "10.0.0.0/99"},
    {"name": "   ", "cidr": "10.0.0.0/24"}])
def test_an_invalid_group_is_rejected(client, admin_user, auth_headers, payload):
    assert client.post("/themis/asset-groups", headers=auth_headers(admin_user), json=payload).status_code == 400


def test_a_duplicate_group_name_is_a_conflict(client, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    _create_group(client, headers)

    assert client.post("/themis/asset-groups", headers=headers,
                       json={"name": "dmz", "cidr": "10.9.0.0/24"}).status_code == 409


def test_a_group_can_be_deleted_only_by_its_owner(client, admin_user, regular_user, auth_headers):
    group_id = _create_group(client, auth_headers(admin_user))

    assert client.delete(f"/themis/asset-groups/{group_id}", headers=auth_headers(regular_user)).status_code == 404
    assert client.delete(f"/themis/asset-groups/{group_id}", headers=auth_headers(admin_user)).status_code == 200
    assert client.get("/themis/asset-groups", headers=auth_headers(admin_user)).get_json()["count"] == 0


# ───────────────────────── análisis de un grupo

def test_a_vulnerable_host_and_its_neighbours_produce_an_explained_risk(client, app, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    group_id = _create_group(client, headers)
    with app.app_context():
        _add_host(admin_user.id, "fileserver", "10.0.0.5", [_SMB_UNSIGNED])
        _add_host(admin_user.id, "pc-ana", "10.0.0.20")
        _add_host(admin_user.id, "pc-luis", "10.0.0.21")

    body = client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()

    assert body["hostCount"] == 3 and body["scope"]["type"] == "group"
    [risk] = body["risks"]
    assert risk["rule"] == "exposed-service" and risk["reach"] == 2
    assert "fileserver expone SMB" in risk["title"] and "pc-ana y pc-luis" in risk["title"]
    assert [host["name"] for host in risk["hosts"]] == ["fileserver", "pc-ana", "pc-luis"]
    # El score refleja a cuántos hosts alcanza: 8.0 × (1 + 0,1 × 2).
    assert risk["riskScore"] == 9.6 and risk["severity"] == "CRITICAL"


def test_hosts_outside_the_range_are_not_part_of_the_group(client, app, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    group_id = _create_group(client, headers)
    with app.app_context():
        _add_host(admin_user.id, "fileserver", "10.0.0.5", [_SMB_UNSIGNED])
        _add_host(admin_user.id, "lejano", "192.168.1.9")

    body = client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()

    assert body["hostCount"] == 1 and body["risks"] == []


def test_a_group_without_risk_produces_none(client, app, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    group_id = _create_group(client, headers)
    with app.app_context():
        _add_host(admin_user.id, "a", "10.0.0.5")
        _add_host(admin_user.id, "b", "10.0.0.6")

    assert client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()["risks"] == []


def test_a_fixed_finding_no_longer_counts(client, app, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    group_id = _create_group(client, headers)
    with app.app_context():
        _add_host(admin_user.id, "fileserver", "10.0.0.5", [{**_SMB_UNSIGNED, "state": "fixed"}])
        _add_host(admin_user.id, "pc", "10.0.0.20")

    assert client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()["risks"] == []


def test_only_the_latest_scan_of_a_host_counts(client, app, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    group_id = _create_group(client, headers)
    with app.app_context():
        host_id = _add_host(admin_user.id, "fileserver", "10.0.0.5", [_SMB_UNSIGNED], age_minutes=60)
        _add_host(admin_user.id, "pc", "10.0.0.20")
        # Un escaneo más reciente del mismo host, ya sin el problema.
        with UnitOfWork() as uow:
            uow.session.add(LybraScan(target="10.0.0.5", user_id=admin_user.id, host_id=host_id,
                                      status=ScanStatus.FINISHED.value, started_at=utcnow_naive()))

    assert client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()["risks"] == []


def test_the_risk_identity_is_stable_when_a_host_joins(client, app, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    group_id = _create_group(client, headers)
    with app.app_context():
        _add_host(admin_user.id, "fileserver", "10.0.0.5", [_SMB_UNSIGNED])
        _add_host(admin_user.id, "pc", "10.0.0.20")
    first = client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()["risks"][0]
    with app.app_context():
        _add_host(admin_user.id, "otro", "10.0.0.21")

    second = client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).get_json()["risks"][0]

    assert first["dedupKey"] == second["dedupKey"] and second["reach"] == 2 > first["reach"]


def test_a_host_resolving_to_two_segments_is_reported_as_a_bridge(app, admin_user):
    with app.app_context():
        _add_host(admin_user.id, "gateway.lan", "10.0.0.1")
        _add_host(admin_user.id, "pc-a", "10.0.0.20")
        _add_host(admin_user.id, "pc-b", "10.0.1.20")
        manager = NetworkRiskManager(resolve_addresses=lambda name: (
            ("10.0.0.1", "10.0.1.1") if name == "gateway.lan" else ()))
        from src.modules.features.themis.model import AssetGroup
        from src.modules.features.themis.repositories import AssetGroupRepository
        with UnitOfWork() as uow:
            group_id = AssetGroupRepository(uow).save(
                AssetGroup(user_id=admin_user.id, name="lan", cidr="10.0.0.0/16")).id

        result = manager.assess_group(admin_user.id, group_id)

    [risk] = result["risks"]
    assert risk["rule"] == "multi-homed" and "gateway.lan tiene direcciones en 2 segmentos" in risk["title"]


# ───────────────────────── análisis de un escaneo de red

def test_a_network_scan_is_analysed_through_its_children(client, app, admin_user, auth_headers):
    with app.app_context():
        parent_id = _add_parent(admin_user.id)
        _add_host(admin_user.id, "fileserver", "10.0.0.5", [_SMB_UNSIGNED], parent_scan_id=parent_id)
        _add_host(admin_user.id, "pc", "10.0.0.6", parent_scan_id=parent_id)

    body = client.get(f"/themis/network-risk?scanId={parent_id}", headers=auth_headers(admin_user)).get_json()

    assert body["scope"]["type"] == "scan" and body["hostCount"] == 2
    assert [risk["rule"] for risk in body["risks"]] == ["exposed-service"]


# ───────────────────────── contrato del endpoint

def test_exactly_one_scope_is_required(client, admin_user, auth_headers):
    headers = auth_headers(admin_user)
    assert client.get("/themis/network-risk", headers=headers).status_code == 400
    assert client.get("/themis/network-risk?groupId=1&scanId=1", headers=headers).status_code == 400


def test_a_foreign_group_or_scan_is_not_found(client, app, admin_user, regular_user, auth_headers):
    group_id = _create_group(client, auth_headers(admin_user))
    with app.app_context():
        parent_id = _add_parent(admin_user.id)
    headers = auth_headers(regular_user)

    assert client.get(f"/themis/network-risk?groupId={group_id}", headers=headers).status_code == 404
    assert client.get(f"/themis/network-risk?scanId={parent_id}", headers=headers).status_code == 404
