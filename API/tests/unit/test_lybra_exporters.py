"""Tests unitarios de los exportadores de Lybra (SARIF, STIX, OCSF).

Las tres funciones son puras sobre el dict de ``format_scan``, así que estos
tests construyen ese dict a mano en vez de levantar un escaneo real.
"""

import pytest

from src.modules.features.themis.lybra.exporters import to_sarif, to_stix, to_ocsf

pytestmark = pytest.mark.unit


def _scan(findings=None, target="10.0.0.5"):
    return {"id": 1, "target": target, "findings": findings or []}


def _finding(**overrides):
    base = {
        "id": 42,
        "title": "OpenSSH 7.2 desactualizado",
        "category": "outdated_software",
        "port": 22,
        "cveIds": ["CVE-2021-1111"],
        "cvssScore": 9.8,
        "priority": "CRITICAL",
        "state": "open",
        "checkId": None,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------- SARIF

def test_sarif_empty_scan_has_no_results():
    doc = to_sarif(_scan())
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["results"] == []
    assert doc["runs"][0]["tool"]["driver"]["rules"] == []


def test_sarif_result_uses_check_id_as_rule_id_and_maps_severity():
    finding = _finding(checkId="ssh-outdated-version", priority="HIGH")
    doc = to_sarif(_scan(findings=[finding]))

    result = doc["runs"][0]["results"][0]
    assert result["ruleId"] == "ssh-outdated-version"
    assert result["level"] == "error"
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "10.0.0.5:22"


def test_sarif_falls_back_to_category_when_there_is_no_check_id():
    # Una detección por versión no pasa por ningún check activo, así que no
    # tiene check_id — el ruleId no puede quedarse vacío por eso.
    finding = _finding(checkId=None, category="outdated_software")
    doc = to_sarif(_scan(findings=[finding]))
    assert doc["runs"][0]["results"][0]["ruleId"] == "outdated_software"


def test_sarif_declares_each_rule_only_once():
    findings = [_finding(checkId="ssh-outdated-version") for _ in range(3)]
    doc = to_sarif(_scan(findings=findings))
    assert len(doc["runs"][0]["tool"]["driver"]["rules"]) == 1
    assert len(doc["runs"][0]["results"]) == 3


@pytest.mark.parametrize("priority,level", [
    ("INFO", "note"), ("LOW", "note"),
    ("MEDIUM", "warning"),
    ("HIGH", "error"), ("CRITICAL", "error"),
])
def test_sarif_level_mapping_covers_every_priority(priority, level):
    finding = _finding(priority=priority)
    doc = to_sarif(_scan(findings=[finding]))
    assert doc["runs"][0]["results"][0]["level"] == level


# -------------------------------------------------------------------- STIX

def test_stix_empty_scan_has_no_objects():
    bundle = to_stix(_scan())
    assert bundle["type"] == "bundle"
    assert bundle["objects"] == []


def test_stix_bundle_relates_infrastructure_to_vulnerability():
    bundle = to_stix(_scan(findings=[_finding()]))

    by_type = {}
    for obj in bundle["objects"]:
        by_type.setdefault(obj["type"], []).append(obj)

    assert len(by_type["infrastructure"]) == 1
    assert len(by_type["vulnerability"]) == 1
    assert len(by_type["relationship"]) == 1

    infra = by_type["infrastructure"][0]
    vuln = by_type["vulnerability"][0]
    rel = by_type["relationship"][0]
    assert rel["source_ref"] == infra["id"]
    assert rel["target_ref"] == vuln["id"]
    assert vuln["external_references"] == [{"source_name": "cve", "external_id": "CVE-2021-1111"}]


def test_stix_ids_are_deterministic_across_exports():
    scan = _scan(findings=[_finding()])
    first = to_stix(scan)
    second = to_stix(scan)
    assert [o["id"] for o in first["objects"]] == [o["id"] for o in second["objects"]]


# -------------------------------------------------------------------- OCSF

def test_ocsf_empty_scan_yields_no_events():
    assert to_ocsf(_scan()) == []


def test_ocsf_event_maps_class_severity_and_status():
    finding = _finding(priority="CRITICAL", state="fixed")
    events = to_ocsf(_scan(findings=[finding]))

    assert len(events) == 1
    event = events[0]
    assert event["class_uid"] == 2002
    assert event["severity_id"] == 5          # CRITICAL
    assert event["status_id"] == 4            # fixed -> Resolved
    assert event["vulnerabilities"][0]["cve"]["uid"] == "CVE-2021-1111"
    assert event["vulnerabilities"][0]["cvss"] == [{"base_score": 9.8}]


def test_ocsf_finding_without_cves_has_no_vulnerability_entries():
    finding = _finding(cveIds=[], cvssScore=None)
    events = to_ocsf(_scan(findings=[finding]))
    assert events[0]["vulnerabilities"] == []


@pytest.mark.parametrize("state,status_id", [
    ("open", 1), ("regressed", 1),
    ("accepted", 3), ("false_positive", 3),
    ("fixed", 4),
])
def test_ocsf_status_mapping_covers_every_state(state, status_id):
    finding = _finding(state=state)
    events = to_ocsf(_scan(findings=[finding]))
    assert events[0]["status_id"] == status_id
