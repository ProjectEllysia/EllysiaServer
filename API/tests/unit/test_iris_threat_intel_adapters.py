"""Adaptadores de reputación: cada proveedor se traduce al mismo veredicto.

Sustituye la red en ``threat_intel.base.fetch`` con respuestas con la forma
real de cada API y fija la traducción a ``known_malicious``, ``suspicious``,
``unknown`` o ``unavailable``, y que un fallo de red nunca lanza.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.modules.features.iris.model import ThreatIntelVerdict
from src.modules.features.iris.services.enrichment.egress import EgressResponse
from src.modules.features.iris.services.enrichment.threat_intel import adapter_for, worst_verdict

pytestmark = pytest.mark.unit

_FETCH = "src.modules.features.iris.services.enrichment.threat_intel.base.fetch"


def _answer(status, payload):
    body = json.dumps(payload).encode() if payload is not None else b""
    return lambda url, **kwargs: EgressResponse(url=url, status=status, headers={}, body=body,
                                                is_truncated=False, peer_address="93.184.216.34")


def _lookup(provider, kind, value, status, payload):
    with patch(_FETCH, _answer(status, payload)):
        return adapter_for(provider).lookup(kind, value, "key", 1, 10_000)


@pytest.mark.parametrize("stats,expected", [
    ({"malicious": 5, "suspicious": 0, "harmless": 60}, ThreatIntelVerdict.KNOWN_MALICIOUS),
    ({"malicious": 1, "suspicious": 0, "harmless": 60}, ThreatIntelVerdict.SUSPICIOUS),
    ({"malicious": 0, "suspicious": 0, "harmless": 60}, ThreatIntelVerdict.UNKNOWN),
])
def test_virustotal_counts_engines(stats, expected):
    finding = _lookup("virustotal", "domain", "evil.example", 200,
                      {"data": {"attributes": {"last_analysis_stats": stats}}})

    assert finding.verdict == expected and finding.detail["malicious"] == stats["malicious"]


def test_virustotal_does_not_know_it():
    assert _lookup("virustotal", "hash", "ab" * 32, 404, {"error": {}}).verdict == ThreatIntelVerdict.UNKNOWN


def test_urlscan_malicious_scans():
    assert _lookup("urlscan", "url", "http://evil.example/x", 200, {"total": 3}).verdict \
        == ThreatIntelVerdict.KNOWN_MALICIOUS
    assert _lookup("urlscan", "ip", "93.184.216.34", 200, {"total": 0}).verdict == ThreatIntelVerdict.UNKNOWN


@pytest.mark.parametrize("results,expected", [
    ({"in_database": True, "verified": True, "valid": True}, ThreatIntelVerdict.KNOWN_MALICIOUS),
    ({"in_database": True, "verified": False, "valid": True}, ThreatIntelVerdict.SUSPICIOUS),
    ({"in_database": False}, ThreatIntelVerdict.UNKNOWN),
])
def test_phishtank_verification(results, expected):
    assert _lookup("phishtank", "url", "http://evil.example/x", 200, {"results": results}).verdict == expected


def test_urlhaus_listed_or_not():
    assert _lookup("urlhaus", "hash", "ab" * 32, 200, {"query_status": "ok"}).verdict \
        == ThreatIntelVerdict.KNOWN_MALICIOUS
    assert _lookup("urlhaus", "domain", "evil.example", 200, {"query_status": "no_results"}).verdict \
        == ThreatIntelVerdict.UNKNOWN


def test_a_provider_that_fails_is_neutral_and_never_raises():
    def down(url, **kwargs):
        raise TimeoutError("slow")

    with patch(_FETCH, down):
        finding = adapter_for("virustotal").lookup("url", "http://x.example", "key", 1, 10)

    assert finding.verdict == ThreatIntelVerdict.UNAVAILABLE and finding.error == "timeout"
    assert _lookup("urlscan", "domain", "x.example", 500, None).verdict == ThreatIntelVerdict.UNAVAILABLE


def test_an_unsupported_kind_is_not_sent():
    with patch(_FETCH) as fetch:
        finding = adapter_for("phishtank").lookup("hash", "ab", "key", 1, 10)

    fetch.assert_not_called()
    assert finding.error == "unsupported_kind"


def test_the_worst_verdict_wins():
    assert worst_verdict([ThreatIntelVerdict.UNKNOWN, ThreatIntelVerdict.SUSPICIOUS]) == ThreatIntelVerdict.SUSPICIOUS
    assert worst_verdict([]) == ThreatIntelVerdict.UNAVAILABLE
