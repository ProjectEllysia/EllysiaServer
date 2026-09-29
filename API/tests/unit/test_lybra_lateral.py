"""Riesgo de movimiento lateral (``lybra/lateral.py``): cada regla con su escenario mínimo.

Puro: los hosts se construyen a mano, sin base de datos ni red.
"""

import pytest

from src.modules.features.themis.lybra import GroupHost, assess_lateral_risk, propagation_score, segment_of
from src.modules.features.themis.lybra.correlation import compute_dedup_key

pytestmark = pytest.mark.unit


def _finding(**overrides) -> dict:
    return {"title": "problema", "category": "network_config", "severity": "HIGH", "port": 445,
            "service": "microsoft-ds", "cvss_score": None, "in_kev": False, "cve_ids": None,
            "check_id": "lybra:smb-signing-not-required@1", "state": "open", **overrides}


def _host(host_id: int, name: str, address: str, *findings: dict, extra_addresses=()) -> GroupHost:
    return GroupHost(host_id, name, (address, *extra_addresses), tuple(findings))


def _plain(host_id: int, address: str) -> GroupHost:
    return _host(host_id, f"h{host_id}", address)


# ------------------------------------------------------------ servicio expuesto

def test_a_vulnerable_smb_host_reaches_the_others_in_its_segment():
    hosts = [_host(1, "fileserver", "10.0.0.5", _finding(title="SMB sin firma")),
             _plain(2, "10.0.0.6"), _plain(3, "10.0.0.7")]

    [risk] = assess_lateral_risk("group:1", hosts)

    assert risk["category"] == "lateral_risk" and risk["rule"] == "exposed-service"
    # Explicable en una frase que nombra a todos los implicados.
    assert "fileserver expone SMB" in risk["title"] and "h2 y h3" in risk["title"]
    assert [host["name"] for host in risk["hosts"]] == ["fileserver", "h2", "h3"]
    assert risk["host_id"] is None and risk["port"] is None


def test_the_score_grows_with_how_many_hosts_it_reaches():
    finding = _finding(severity="HIGH")
    small = assess_lateral_risk("g", [_host(1, "a", "10.0.0.1", finding), _plain(2, "10.0.0.2")])
    large = assess_lateral_risk("g", [_host(1, "a", "10.0.0.1", finding)]
                                + [_plain(n, f"10.0.0.{n}") for n in range(2, 8)])

    assert small[0]["reach"] == 1 and large[0]["reach"] == 6
    assert large[0]["risk_score"] > small[0]["risk_score"]


def test_a_vulnerable_host_alone_in_its_segment_reaches_nobody():
    hosts = [_host(1, "a", "10.0.0.5", _finding()), _plain(2, "10.0.1.5")]
    assert assess_lateral_risk("g", hosts) == []


def test_a_host_with_a_healthy_remote_service_is_no_risk():
    hosts = [_host(1, "a", "10.0.0.5", _finding(severity="INFO", category="open_port")), _plain(2, "10.0.0.6")]
    assert assess_lateral_risk("g", hosts) == []


def test_a_fixed_finding_is_no_risk():
    hosts = [_host(1, "a", "10.0.0.5", _finding(state="fixed")), _plain(2, "10.0.0.6")]
    assert assess_lateral_risk("g", hosts) == []


def test_a_serious_finding_on_a_non_lateral_port_is_not_a_lateral_risk():
    hosts = [_host(1, "a", "10.0.0.5", _finding(port=8080, service="http")), _plain(2, "10.0.0.6")]
    assert assess_lateral_risk("g", hosts) == []


# ------------------------------------------------------------ misma vulnerabilidad

def test_the_same_serious_cve_on_several_hosts_is_a_shared_vulnerability():
    cve = _finding(port=22, service="ssh", category="vulnerability", cvss_score=9.8,
                   cve_ids=["CVE-2024-0001"], check_id=None)
    hosts = [_host(1, "web1", "10.0.0.1", cve), _host(2, "web2", "10.0.1.1", cve), _plain(3, "10.0.2.1")]

    [risk] = assess_lateral_risk("g", hosts)

    assert risk["rule"] == "shared-vulnerability" and risk["severity"] == "CRITICAL"
    assert "CVE-2024-0001 afecta a 2 hosts" in risk["title"] and "web1 y web2" in risk["title"]


def test_a_cve_on_a_single_host_is_not_shared():
    cve = _finding(port=22, service="ssh", category="vulnerability", cvss_score=9.8, cve_ids=["CVE-2024-0001"])
    assert assess_lateral_risk("g", [_host(1, "a", "10.0.0.1", cve), _plain(2, "10.0.1.1")]) == []


def test_a_low_scoring_cve_does_not_propagate_a_risk():
    cve = _finding(port=22, service="ssh", category="vulnerability", cvss_score=3.1, cve_ids=["CVE-2024-0002"])
    hosts = [_host(1, "a", "10.0.0.1", cve), _host(2, "b", "10.0.1.1", cve)]
    assert assess_lateral_risk("g", hosts) == []


# ------------------------------------------------------------ multi-homed

def test_a_host_in_two_segments_that_joins_other_hosts_is_a_bridge():
    hosts = [_host(1, "gateway", "10.0.0.1", extra_addresses=("10.0.1.1",)),
             _plain(2, "10.0.0.2"), _plain(3, "10.0.1.2")]

    [risk] = assess_lateral_risk("g", hosts)

    assert risk["rule"] == "multi-homed" and "gateway tiene direcciones en 2 segmentos" in risk["title"]
    assert risk["reach"] == 2


def test_a_bridge_that_joins_nothing_on_one_side_is_no_risk():
    hosts = [_host(1, "gateway", "10.0.0.1", extra_addresses=("10.0.9.1",)), _plain(2, "10.0.0.2")]
    assert assess_lateral_risk("g", hosts) == []


# ------------------------------------------------------------ credenciales

def test_default_credentials_working_on_several_hosts_are_reused():
    credentials = _finding(category="default_credentials", severity="CRITICAL", port=22, service="ssh",
                           title="SSH con admin/admin", check_id="lybra:default-ssh-admin@1")
    hosts = [_host(1, "a", "10.0.0.1", credentials), _host(2, "b", "10.0.1.1", credentials)]

    [risk] = assess_lateral_risk("g", hosts)

    assert risk["rule"] == "shared-credentials" and "SSH con admin/admin" in risk["title"]


# ------------------------------------------------------------ sin riesgo e identidad

def test_a_group_without_risk_produces_no_finding():
    assert assess_lateral_risk("g", [_plain(1, "10.0.0.1"), _plain(2, "10.0.0.2")]) == []


def test_a_group_of_one_host_has_nowhere_to_move():
    assert assess_lateral_risk("g", [_host(1, "a", "10.0.0.5", _finding())]) == []


def test_the_identity_of_a_risk_is_stable_when_more_hosts_join_the_group():
    smb = _finding()
    before = assess_lateral_risk("group:1", [_host(1, "a", "10.0.0.1", smb), _plain(2, "10.0.0.2")])
    after = assess_lateral_risk("group:1", [_host(1, "a", "10.0.0.1", smb), _plain(2, "10.0.0.2"),
                                           _plain(3, "10.0.0.3")])

    assert before[0]["dedup_key"] == after[0]["dedup_key"]


def test_the_same_risk_in_two_networks_has_two_identities():
    hosts = [_host(1, "a", "10.0.0.1", _finding()), _plain(2, "10.0.0.2")]
    assert (assess_lateral_risk("group:1", hosts)[0]["dedup_key"]
            != assess_lateral_risk("group:2", hosts)[0]["dedup_key"])


def test_two_risks_of_the_same_rule_do_not_collide():
    hosts = [_host(1, "a", "10.0.0.1", _finding()), _host(2, "b", "10.0.0.2", _finding()), _plain(3, "10.0.0.3")]
    risks = assess_lateral_risk("g", hosts)
    assert len({risk["dedup_key"] for risk in risks}) == len(risks) == 2


def test_the_dedup_key_matches_the_shared_correlation_rule():
    [risk] = assess_lateral_risk("g", [_host(1, "a", "10.0.0.1", _finding()), _plain(2, "10.0.0.2")])
    assert risk["dedup_key"] == compute_dedup_key(risk)


# ------------------------------------------------------------ utilidades

@pytest.mark.parametrize("base, reach, expected", [
    (8.0, 0, 8.0), (8.0, 1, 8.8), (8.0, 5, 10.0), (8.0, 50, 10.0), (4.0, 3, 5.2), (5.0, -2, 5.0)])
def test_propagation_score_grows_with_reach_up_to_a_cap(base, reach, expected):
    assert propagation_score(base, reach) == expected


@pytest.mark.parametrize("address, segment", [
    ("10.0.0.77", "10.0.0.0/24"), ("2001:db8::5", "2001:db8::/64"), ("no-es-ip", None)])
def test_segment_of_an_address(address, segment):
    assert segment_of(address) == segment
