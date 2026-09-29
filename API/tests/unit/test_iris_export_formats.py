"""Renderizadores de exportación de Iris: JSON versionado, STIX 2.1 y MISP.

Parten de un documento neutro fijo y comprueban lo que un SOC necesita para no
escribir un parser propio: el bundle STIX lo acepta la librería de referencia
(``stix2``), cada indicador lleva fuente, confianza y validez, y el JSON va
desactivado salvo que se pida lo contrario.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import stix2

from src.modules.features.iris.services.exporters import (
    EXPORT_SCHEMA_VERSION,
    ExportDocument,
    ExportedAnalysis,
    ExportedFinding,
    ExportedIndicator,
    ExportFormat,
    defang_value,
    indicator_confidence,
    render_export,
    worst_verdict,
)
from src.modules.features.iris.services.exporters.stix import build_pattern

pytestmark = pytest.mark.unit

_SEEN = datetime(2026, 9, 1, 10, 0, 0)


def _document(campaign_id=None) -> ExportDocument:
    indicators = tuple(
        ExportedIndicator(kind=kind, value=value, confidence=90, verdict="Phishing", valid_from=_SEEN,
                          valid_until=_SEEN + timedelta(days=30), analysis_ids=(7,))
        for kind, value in (
            ("domain", "evil.example"), ("url", "http://evil.example/it's"), ("ip", "203.0.113.9"),
            ("ip", "2001:db8::1"), ("email", "ceo@evil.example"), ("hash", "ab" * 32),
        )
    )
    return ExportDocument(
        subject_kind="analysis", subject_id=7, title="Factura pendiente", verdict="Phishing", confidence=85,
        first_seen=_SEEN, last_seen=_SEEN, generated_at=_SEEN + timedelta(hours=1),
        detector_version="rules-abc", producer_version="0.5.30",
        analyses=(ExportedAnalysis(analysis_id=7, title="Factura pendiente", verdict="Phishing",
                                   confidence="high", received_at=_SEEN, analyst_label="phishing"),),
        indicators=indicators,
        findings=(ExportedFinding(rule_id="iris.links.body_links", name="Body Links", category="content_analysis",
                                  severity="high", score=-20.0, mitre_techniques=("T1566.002",), analysis_id=7),),
        campaign_id=campaign_id, campaign_label="Facturas" if campaign_id else "",
    )


def test_the_json_is_versioned_and_defanged_by_default():
    document = render_export(_document(), ExportFormat.JSON)

    assert document["schemaVersion"] == EXPORT_SCHEMA_VERSION and document["defanged"] is True
    by_type = {indicator["type"]: indicator["value"] for indicator in document["indicators"]}
    assert by_type["url"] == "hxxp://evil[.]example/it's"
    assert by_type["email"] == "ceo[@]evil[.]example"
    assert by_type["hash"] == "ab" * 32


def test_every_json_indicator_carries_source_confidence_validity_and_analysis():
    document = render_export(_document(), ExportFormat.JSON, is_defanged=False)

    for indicator in document["indicators"]:
        assert indicator["source"] == "Ellysia Iris"
        assert indicator["confidence"] == 90
        assert indicator["validFrom"] == "2026-09-01T10:00:00.000Z"
        assert indicator["validUntil"] == "2026-10-01T10:00:00.000Z"
        assert indicator["analysisIds"] == [7]
    assert document["findings"][0]["ruleId"] == "iris.links.body_links"


@pytest.mark.parametrize("campaign_id", [None, 3])
def test_the_stix_bundle_is_valid_stix_2_1(campaign_id):
    bundle = render_export(_document(campaign_id), ExportFormat.STIX)

    parsed = stix2.parse(bundle, allow_custom=True)

    types = [stix_object.type for stix_object in parsed.objects]
    assert types.count("indicator") == 6
    assert "attack-pattern" in types and "report" in types
    assert ("campaign" in types) is (campaign_id is not None)
    indicator = next(stix_object for stix_object in parsed.objects if stix_object.type == "indicator")
    assert indicator.confidence == 90 and indicator.valid_until > indicator.valid_from


def test_stix_ids_are_stable_across_exports():
    first = render_export(_document(), ExportFormat.STIX)
    second = render_export(_document(), ExportFormat.STIX)

    assert [item["id"] for item in first["objects"]] == [item["id"] for item in second["objects"]]


def test_stix_patterns_escape_quotes_and_pick_the_address_family():
    assert build_pattern("url", "http://x/it's") == "[url:value = 'http://x/it\\'s']"
    assert build_pattern("ip", "2001:db8::1") == "[ipv6-addr:value = '2001:db8::1']"
    assert build_pattern("hash", "ab") == "[file:hashes.'SHA-256' = 'ab']"


def test_the_misp_event_only_sends_phishing_indicators_to_the_ids():
    event = render_export(_document(campaign_id=3), ExportFormat.MISP)["Event"]

    assert event["threat_level_id"] == "1" and event["distribution"] == "0"
    types = {attribute["type"] for attribute in event["Attribute"]}
    assert types == {"domain", "url", "ip-src", "email-src", "sha256"}
    assert all(attribute["to_ids"] for attribute in event["Attribute"])
    assert {'misp-galaxy:mitre-attack-pattern="T1566.002"', 'ellysia:campaign="3"'} <= {tag["name"] for tag in event["Tag"]}


def test_confidence_depends_on_verdict_and_iris_confidence():
    assert indicator_confidence("Phishing", "high") == 90
    assert indicator_confidence("Suspicious", "low") == 30
    assert indicator_confidence("Legitimate", "high") == 10
    assert indicator_confidence(None, None) == 30
    assert worst_verdict(["Legitimate", None, "Suspicious"]) == "Suspicious"
    assert defang_value("hash", "a.b") == "a.b"
