"""La inteligencia pasiva de Lybra, en su capa pura: fuentes falsas y DNS falso.

Nada aquí sale a la red (la suite lo impide de todas formas): las fuentes
llegan por un fetcher falso que devuelve respuestas con la forma real de cada
API, y el DNS por una tabla ``(nombre, tipo) -> valores``. Lo que se comprueba
es lo que el motor hace con esos datos: qué subdominios saca, cómo degrada
cuando falta una fuente, qué procedencia y antigüedad lleva cada hallazgo y
cuándo dispara cada regla de higiene DNS.
"""

import base64
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.modules.features.themis.lybra import (
    DnsCheckStatus,
    FetchedDocument,
    OsintSource,
    QOD_DNS_RECORD,
    QOD_OPEN_PORT,
    QOD_THIRD_PARTY,
    SourceOutcome,
    SourceSetting,
    assess_dns_hygiene,
    collect_host_observations,
    collect_passive_intelligence,
    finding_to_osint_json,
    normalize_domain,
    suggest_cpe_findings,
)
from src.modules.features.themis.lybra.dns_hygiene import evaluate_spf_record
from src.modules.features.themis.lybra.osint import build_exposed_service_finding

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 28, 12, 0, 0)
RETRIEVED_AT = datetime(2026, 9, 28, 11, 0, 0)

#: Respuesta de crt.sh con la forma real: nombres separados por salto de línea,
#: un comodín, un correo y un nombre de otro dominio que hay que descartar.
CRTSH_PAYLOAD = [
    {"id": 1, "issuer_name": "C=US, O=Let's Encrypt, CN=R11", "common_name": "example.com",
     "name_value": "example.com\nwww.example.com", "not_before": "2026-09-20T08:00:00",
     "entry_timestamp": "2026-09-20T09:00:00.123"},
    {"id": 2, "issuer_name": "C=US, O=DigiCert Inc", "common_name": "*.dev.example.com",
     "name_value": "*.dev.example.com\nadmin@example.com", "not_before": "2025-01-10T00:00:00"},
    {"id": 3, "issuer_name": "C=US, O=Let's Encrypt, CN=R10", "common_name": "evil.example.org",
     "name_value": "evil.example.org", "not_before": "2026-09-01T00:00:00"},
    {"id": 1, "issuer_name": "repetido", "name_value": "repeated.example.com",
     "not_before": "2026-09-20T08:00:00"},
]

SHODAN_PAYLOAD = {
    "ip_str": "93.184.216.34",
    "last_update": "2026-08-01T00:00:00.000000",
    "data": [
        {"port": 443, "transport": "tcp", "product": "nginx", "version": "1.18.0",
         "cpe23": ["cpe:2.3:a:f5:nginx:1.18.0"], "timestamp": "2026-08-29T12:00:00.000000"},
        {"port": 8080, "transport": "tcp"},
    ],
}

CENSYS_PAYLOAD = {
    "code": 200,
    "result": {
        "ip": "93.184.216.34",
        "last_updated_at": "2026-09-27T00:00:00.000Z",
        "services": [
            {"port": 443, "transport_protocol": "TCP", "observed_at": "2026-09-26T00:00:00Z",
             "software": [{"vendor": "f5", "product": "nginx", "version": "1.18.0",
                           "uniform_resource_identifier": "cpe:2.3:a:f5:nginx:1.18.0:*:*:*:*:*:*:*"}]},
        ],
    },
}


class _FakeSources:
    """Fetcher falso: responde por fuente y anota cada consulta."""

    def __init__(self, payloads=None, failing=()):
        self.payloads = payloads or {}
        self.failing = set(failing)
        self.calls = []

    def __call__(self, source, query):
        self.calls.append((source, query))
        if source in self.failing:
            raise ConnectionError("la fuente no responde")
        return FetchedDocument(payload=self.payloads.get(source), retrieved_at=RETRIEVED_AT)

    def queried(self, source):
        return [query for called_source, query in self.calls if called_source == source]


class _FakeDns:
    """DNS falso: una tabla ``(nombre, tipo) -> valores``; lo que no está no existe.

    Un valor ``None`` en la tabla simula un resolutor que no da respuesta
    definitiva (tiempo agotado).
    """

    def __init__(self, records=None):
        self.records = records or {}
        self.queries = []

    def __call__(self, name, record_type):
        self.queries.append((name, record_type))
        return self.records.get((name, record_type), [])


def _only_crtsh():
    return {OsintSource.CERTIFICATE_TRANSPARENCY: SourceSetting(is_enabled=True)}


def _findings_with_check(findings, check_prefix):
    return [finding for finding in findings if finding["check_id"].startswith(check_prefix)]


# ───────────────────────── Certificate Transparency

def test_certificate_transparency_produces_the_domain_subdomains():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW)

    names = [record.name for record in report.subdomains]
    # El comodín delata dev.example.com; el correo y el dominio ajeno se descartan,
    # y la entrada repetida (mismo id) no cuenta dos veces.
    assert names == ["dev.example.com", "example.com", "www.example.com"]
    assert fetch.queried(OsintSource.CERTIFICATE_TRANSPARENCY) == ["example.com"]
    www = next(record for record in report.subdomains if record.name == "www.example.com")
    assert www.last_seen_at == datetime(2026, 9, 20, 8, 0, 0)


def test_each_passive_finding_states_its_source_and_its_age():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW)

    [dev] = [finding for finding in _findings_with_check(report.findings, "lybra:osint-subdomain")
             if finding["service"] == "dev.example.com"]
    assert dev["category"] == "passive_exposure"
    provenance = dev["_provenance"]
    assert provenance["source"] == "crtsh"
    assert provenance["observedAt"] == "2025-01-10T00:00:00Z"
    assert provenance["retrievedAt"] == "2026-09-28T11:00:00Z"
    assert provenance["ageDays"] == (NOW - datetime(2025, 1, 10)).days
    # El título lo cuenta en lenguaje llano: de dónde sale y de cuándo es.
    assert "Certificate Transparency" in dev["title"]
    assert f"hace {provenance['ageDays']} días" in dev["title"]
    # La misma procedencia viaja como evidencia para la tabla FindingEvidence.
    assert dev["_evidence"] == {"kind": "osint_record", "payload": provenance}


def test_third_party_data_scores_below_our_own_observations():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW)

    assert report.findings
    assert QOD_THIRD_PARTY < QOD_OPEN_PORT < QOD_DNS_RECORD
    assert all(finding["qod"] == QOD_THIRD_PARTY for finding in report.findings)
    assert not any(finding["confirmed"] for finding in report.findings)


def test_a_recently_issued_certificate_is_reported_and_an_old_one_is_not():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW,
                                          recent_certificate_days=30)

    recent = _findings_with_check(report.findings, "lybra:osint-recent-certificate")
    assert [finding["_provenance"]["record"]["certificateId"] for finding in recent] == [1]
    assert "emitido hace 8 días" in recent[0]["title"]


def test_the_subdomain_findings_are_capped_but_the_list_is_kept_whole():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW,
                                          max_subdomains=1)

    assert len(report.subdomains) == 3
    assert len(_findings_with_check(report.findings, "lybra:osint-subdomain")) == 1


# ───────────────────────── fuentes que faltan o fallan

def test_a_paid_source_without_its_key_is_skipped_without_breaking_the_rest():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})
    settings = {
        OsintSource.CERTIFICATE_TRANSPARENCY: SourceSetting(is_enabled=True),
        OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=False),
        OsintSource.SECURITYTRAILS: SourceSetting(is_enabled=True, has_credentials=False),
    }

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), settings, NOW)

    outcomes = {status.source: (status.outcome, status.detail) for status in report.source_statuses}
    assert outcomes[OsintSource.SHODAN] == (SourceOutcome.SKIPPED, "missing_api_key")
    assert outcomes[OsintSource.SECURITYTRAILS] == (SourceOutcome.SKIPPED, "missing_api_key")
    assert outcomes[OsintSource.CENSYS] == (SourceOutcome.DISABLED, None)
    assert outcomes[OsintSource.CERTIFICATE_TRANSPARENCY] == (SourceOutcome.OK, None)
    assert fetch.queried(OsintSource.SHODAN) == []
    assert fetch.queried(OsintSource.SECURITYTRAILS) == []
    assert report.subdomains


def test_a_failing_source_is_reported_and_the_others_still_answer():
    fetch = _FakeSources({OsintSource.SECURITYTRAILS: {"subdomains": ["api", "mail"]}},
                         failing={OsintSource.CERTIFICATE_TRANSPARENCY})
    settings = {
        OsintSource.CERTIFICATE_TRANSPARENCY: SourceSetting(is_enabled=True),
        OsintSource.SECURITYTRAILS: SourceSetting(is_enabled=True, has_credentials=True),
    }

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), settings, NOW)

    ct_status = report.source_statuses[0]
    assert (ct_status.outcome, ct_status.detail) == (SourceOutcome.FAILED, "ConnectionError")
    assert [record.name for record in report.subdomains] == ["api.example.com", "mail.example.com"]
    # SecurityTrails no fecha sus datos: el hallazgo lo dice en vez de inventar una antigüedad.
    finding = report.findings[0]
    assert finding["_provenance"]["source"] == "securitytrails"
    assert finding["_provenance"]["ageDays"] is None
    assert "sin fecha de observación" in finding["title"]


def test_the_status_json_never_carries_the_error_text():
    fetch = _FakeSources(failing={OsintSource.CERTIFICATE_TRANSPARENCY})

    report = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW)

    assert report.source_statuses[0].to_json() == {
        "source": "crtsh", "label": "Certificate Transparency (crt.sh)", "outcome": "failed",
        "retrievedAt": None, "cached": False, "detail": "ConnectionError",
    }


# ───────────────────────── Shodan y Censys

def test_shodan_and_censys_are_asked_about_the_domain_addresses():
    fetch = _FakeSources({
        OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD,
        OsintSource.SHODAN: SHODAN_PAYLOAD,
        OsintSource.CENSYS: CENSYS_PAYLOAD,
    })
    dns = _FakeDns({("example.com", "A"): ["93.184.216.34"], ("www.example.com", "A"): ["93.184.216.34"]})
    settings = {
        OsintSource.CERTIFICATE_TRANSPARENCY: SourceSetting(is_enabled=True),
        OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=True),
        OsintSource.CENSYS: SourceSetting(is_enabled=True, has_credentials=True),
    }

    report = collect_passive_intelligence("example.com", fetch, dns, settings, NOW)

    # La dirección se repite en dos nombres, pero se pregunta una sola vez.
    assert fetch.queried(OsintSource.SHODAN) == ["93.184.216.34"]
    assert fetch.queried(OsintSource.CENSYS) == ["93.184.216.34"]
    exposed = _findings_with_check(report.findings, "lybra:osint-exposed-service")
    shodan_443 = next(finding for finding in exposed
                      if finding["_provenance"]["source"] == "shodan" and finding["port"] == 443)
    assert shodan_443["_provenance"]["observedAt"] == "2026-08-29T12:00:00Z"
    assert shodan_443["_provenance"]["ageDays"] == 30
    assert "Shodan vio el puerto 443/tcp" in shodan_443["title"]
    assert "hace 30 días" in shodan_443["title"]
    assert "CPE sugerido por Shodan" in shodan_443["title"]
    assert shodan_443["cpe"] == "cpe:2.3:a:f5:nginx:1.18.0:*:*:*:*:*:*:*"
    # Una entrada sin fecha propia toma la de la ficha de la dirección.
    shodan_8080 = next(finding for finding in exposed if finding["port"] == 8080)
    assert shodan_8080["_provenance"]["observedAt"] == "2026-08-01T00:00:00Z"
    censys = next(finding for finding in exposed if finding["_provenance"]["source"] == "censys")
    assert censys["_provenance"]["ageDays"] == 2


def test_private_addresses_are_never_sent_to_a_third_party():
    fetch = _FakeSources({OsintSource.SHODAN: SHODAN_PAYLOAD})
    settings = {OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=True)}

    observations, statuses = collect_host_observations(["10.0.0.5", "192.168.1.1"], fetch, settings)

    assert fetch.calls == []
    assert observations == []
    assert statuses[0].outcome == SourceOutcome.OK


# ───────────────────────── CPE sugerido para un servicio sin identificar

def _open_port(port, is_resolved):
    return {"category": "open_port", "port": port, "protocol": "tcp", "cpe_resolved": is_resolved}


def _shodan_observations():
    fetch = _FakeSources({OsintSource.SHODAN: SHODAN_PAYLOAD})
    settings = {OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=True)}
    observations, _ = collect_host_observations(["93.184.216.34"], fetch, settings)
    return observations


def test_an_unresolved_port_gets_a_clearly_flagged_suggested_cpe():
    [suggestion] = suggest_cpe_findings([_open_port(443, False)], _shodan_observations(), NOW)

    assert suggestion["check_id"] == "lybra:osint-suggested-cpe@1"
    assert suggestion["cpe"] == "cpe:2.3:a:f5:nginx:1.18.0:*:*:*:*:*:*:*"
    assert suggestion["cpe_resolved"] is False
    assert suggestion["confirmed"] is False
    assert suggestion["qod"] == QOD_THIRD_PARTY
    assert "sin confirmar por Lybra" in suggestion["title"]
    assert suggestion["_provenance"]["source"] == "shodan"
    # Una sugerencia no es una detección: no trae CVEs.
    assert "cve_ids" not in suggestion


def test_a_port_the_engine_already_identified_gets_no_suggestion():
    assert suggest_cpe_findings([_open_port(443, True)], _shodan_observations(), NOW) == []


def test_a_port_without_a_third_party_cpe_gets_no_suggestion():
    # Shodan vio el 8080 pero sin producto: no hay nada que sugerir.
    assert suggest_cpe_findings([_open_port(8080, False)], _shodan_observations(), NOW) == []


def test_sources_that_disagree_on_the_product_produce_no_suggestion():
    conflicting = dict(CENSYS_PAYLOAD)
    conflicting["result"] = dict(CENSYS_PAYLOAD["result"])
    conflicting["result"]["services"] = [{
        "port": 443, "transport_protocol": "TCP",
        "software": [{"uniform_resource_identifier": "cpe:2.3:a:apache:http_server:2.4.49"}],
    }]
    fetch = _FakeSources({OsintSource.SHODAN: SHODAN_PAYLOAD, OsintSource.CENSYS: conflicting})
    settings = {OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=True),
                OsintSource.CENSYS: SourceSetting(is_enabled=True, has_credentials=True)}
    observations, _ = collect_host_observations(["93.184.216.34"], fetch, settings)

    assert suggest_cpe_findings([_open_port(443, False)], observations, NOW) == []


# ───────────────────────── nombres

@pytest.mark.parametrize("raw, expected", [
    ("Example.COM.", "example.com"),
    ("  sub.example.com ", "sub.example.com"),
    ("bücher.example", "xn--bcher-kva.example"),
    ("93.184.216.34", None),
    ("localhost", None),
    ("https://example.com", None),
    ("example.com/path", None),
    ("-bad.example.com", None),
    ("", None),
])
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_finding_to_osint_json_moves_provenance_out_of_the_working_keys():
    fetch = _FakeSources({OsintSource.CERTIFICATE_TRANSPARENCY: CRTSH_PAYLOAD})
    finding = collect_passive_intelligence("example.com", fetch, _FakeDns(), _only_crtsh(), NOW).findings[0]

    serialized = finding_to_osint_json(finding)

    assert "_evidence" not in serialized and "_provenance" not in serialized
    assert serialized["provenance"] == finding["_provenance"]


# ───────────────────────── higiene DNS

DOMAIN = "example.com"


def _healthy_dns(overrides=None):
    """Un dominio que lo hace todo bien; cada test estropea una sola cosa."""
    records = {
        (DOMAIN, "TXT"): ["v=spf1 include:_spf.google.com -all", "google-site-verification=abc"],
        (f"_dmarc.{DOMAIN}", "TXT"): ["v=DMARC1; p=reject; rua=mailto:dmarc@example.com"],
        (DOMAIN, "MX"): ["10 mail.example.com."],
        (f"_mta-sts.{DOMAIN}", "TXT"): ["v=STSv1; id=20260901"],
        (DOMAIN, "CAA"): ['0 issue "letsencrypt.org"'],
        (DOMAIN, "SOA"): ["ns1.example.com. hostmaster.example.com. 1 7200 3600 1209600 3600"],
        (DOMAIN, "DS"): ["12345 13 2 ABCDEF"],
    }
    records.update(overrides or {})
    return _FakeDns(records)


def _assess(dns, selectors=()):
    findings, results = assess_dns_hygiene(DOMAIN, dns, NOW, selectors)
    return findings, {result.check: result.status for result in results}


def _check_ids(findings):
    return sorted(finding["check_id"] for finding in findings)


def test_a_healthy_domain_triggers_no_dns_rule():
    findings, statuses = _assess(_healthy_dns())

    assert findings == []
    assert statuses == {
        "spf": DnsCheckStatus.PASSED, "dmarc": DnsCheckStatus.PASSED,
        "dkim": DnsCheckStatus.NOT_APPLICABLE, "mta_sts": DnsCheckStatus.PASSED,
        "caa": DnsCheckStatus.PASSED, "dnssec": DnsCheckStatus.PASSED,
    }


@pytest.mark.parametrize("txt_records, expected_check", [
    (["google-site-verification=abc"], "lybra:dns-spf-missing@1"),
    (["v=spf1 -all", "v=spf1 mx -all"], "lybra:dns-spf-multiple@1"),
    (["v=spf1 +all"], "lybra:dns-spf-permissive@1"),
    (["v=spf1 mx ?all"], "lybra:dns-spf-permissive@1"),
    (["v=spf1 mx"], "lybra:dns-spf-no-all@1"),
    (["v=spf1 " + " ".join(f"include:spf{i}.example.net" for i in range(11)) + " -all"],
     "lybra:dns-spf-lookups@1"),
])
def test_each_spf_rule_fires(txt_records, expected_check):
    findings, statuses = _assess(_healthy_dns({(DOMAIN, "TXT"): txt_records}))

    assert _check_ids(findings) == [expected_check]
    assert statuses["spf"] is DnsCheckStatus.FAILED
    assert findings[0]["category"] == "dns_hygiene"
    assert findings[0]["qod"] == QOD_DNS_RECORD
    assert findings[0]["_provenance"]["source"] == "dns"
    assert findings[0]["_provenance"]["ageDays"] == 0


@pytest.mark.parametrize("record", [
    "v=spf1 -all", "v=spf1 mx ~all", "v=spf1 redirect=_spf.example.com",
    "v=spf1 " + " ".join(f"include:spf{i}.example.net" for i in range(10)) + " -all",
])
def test_spf_rules_do_not_fire_on_a_sound_policy(record):
    assert evaluate_spf_record(record) == []


def test_plus_all_is_high_and_question_all_is_medium():
    assert evaluate_spf_record("v=spf1 +all")[0][1] == "HIGH"
    assert evaluate_spf_record("v=spf1 all")[0][1] == "HIGH"
    assert evaluate_spf_record("v=spf1 ?all")[0][1] == "MEDIUM"


@pytest.mark.parametrize("dmarc_records, expected_check", [
    ([], "lybra:dns-dmarc-missing@1"),
    (["v=DMARC1; rua=mailto:x@example.com"], "lybra:dns-dmarc-invalid@1"),
    (["v=DMARC1; p=reject", "v=DMARC1; p=none"], "lybra:dns-dmarc-invalid@1"),
    (["v=DMARC1; p=none; rua=mailto:x@example.com"], "lybra:dns-dmarc-monitoring@1"),
    (["v=DMARC1; p=quarantine; pct=25"], "lybra:dns-dmarc-partial@1"),
])
def test_each_dmarc_rule_fires(dmarc_records, expected_check):
    findings, statuses = _assess(_healthy_dns({(f"_dmarc.{DOMAIN}", "TXT"): dmarc_records}))

    assert _check_ids(findings) == [expected_check]
    assert statuses["dmarc"] is DnsCheckStatus.FAILED


def test_dmarc_with_full_enforcement_does_not_fire():
    findings, statuses = _assess(_healthy_dns({(f"_dmarc.{DOMAIN}", "TXT"): ["v=DMARC1; p=quarantine; pct=100"]}))

    assert findings == []
    assert statuses["dmarc"] is DnsCheckStatus.PASSED


def _dkim_record(key_bits):
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_bits)
    der = key.public_key().public_bytes(serialization.Encoding.DER,
                                        serialization.PublicFormat.SubjectPublicKeyInfo)
    return f"v=DKIM1; k=rsa; p={base64.b64encode(der).decode('ascii')}"


def test_dkim_is_not_checked_without_selectors_and_never_guesses_them():
    dns = _healthy_dns()

    findings, statuses = _assess(dns)

    assert statuses["dkim"] is DnsCheckStatus.NOT_APPLICABLE
    assert not any("_domainkey" in name for name, _ in dns.queries)
    assert findings == []


@pytest.mark.parametrize("dkim_records, expected_check", [
    ([], "lybra:dns-dkim-missing@1"),
    (["v=DKIM1; k=rsa; p="], "lybra:dns-dkim-revoked@1"),
    (["v=DKIM1; k=rsa; p=bm8tZXMtdW5hLWNsYXZl"], "lybra:dns-dkim-invalid@1"),
])
def test_each_dkim_rule_fires(dkim_records, expected_check):
    dns = _healthy_dns({(f"s1._domainkey.{DOMAIN}", "TXT"): dkim_records})

    findings, statuses = _assess(dns, selectors=["s1"])

    assert _check_ids(findings) == [expected_check]
    assert statuses["dkim"] is DnsCheckStatus.FAILED


def test_a_short_dkim_key_fires_and_a_long_one_does_not():
    weak = _healthy_dns({(f"s1._domainkey.{DOMAIN}", "TXT"): [_dkim_record(1024)]})
    strong = _healthy_dns({(f"s1._domainkey.{DOMAIN}", "TXT"): [_dkim_record(2048)]})

    weak_findings, _ = _assess(weak, selectors=["s1"])
    strong_findings, strong_statuses = _assess(strong, selectors=["s1"])

    assert _check_ids(weak_findings) == ["lybra:dns-dkim-weak-key@1"]
    assert "1024 bits" in weak_findings[0]["title"]
    assert strong_findings == []
    assert strong_statuses["dkim"] is DnsCheckStatus.PASSED


def test_mta_sts_rules():
    missing, missing_statuses = _assess(_healthy_dns({(f"_mta-sts.{DOMAIN}", "TXT"): []}))
    invalid, _ = _assess(_healthy_dns({(f"_mta-sts.{DOMAIN}", "TXT"): ["v=STSv1;"]}))
    no_mail, no_mail_statuses = _assess(_healthy_dns({(DOMAIN, "MX"): [], (f"_mta-sts.{DOMAIN}", "TXT"): []}))

    assert _check_ids(missing) == ["lybra:dns-mta-sts-missing@1"]
    assert missing_statuses["mta_sts"] is DnsCheckStatus.FAILED
    assert _check_ids(invalid) == ["lybra:dns-mta-sts-invalid@1"]
    # Un dominio que no recibe correo no necesita MTA-STS.
    assert no_mail == []
    assert no_mail_statuses["mta_sts"] is DnsCheckStatus.NOT_APPLICABLE


def test_caa_rule_fires_without_records_and_accepts_the_parent_zone_ones():
    missing, _ = _assess(_healthy_dns({(DOMAIN, "CAA"): []}))
    subdomain_findings, statuses = assess_dns_hygiene(
        "shop.example.com", _FakeDns({("example.com", "CAA"): ['0 issue "letsencrypt.org"']}), NOW)

    assert _check_ids(missing) == ["lybra:dns-caa-missing@1"]
    assert "lybra:dns-caa-missing@1" not in _check_ids(subdomain_findings)
    assert {result.check: result.status for result in statuses}["caa"] is DnsCheckStatus.PASSED


def test_dnssec_rule_fires_only_on_an_unsigned_zone_apex():
    unsigned, _ = _assess(_healthy_dns({(DOMAIN, "DS"): []}))
    not_an_apex, statuses = _assess(_healthy_dns({(DOMAIN, "SOA"): [], (DOMAIN, "DS"): []}))

    assert _check_ids(unsigned) == ["lybra:dns-dnssec-missing@1"]
    assert not_an_apex == []
    assert statuses["dnssec"] is DnsCheckStatus.NOT_APPLICABLE


def test_an_inconclusive_dns_answer_never_becomes_a_finding():
    dns = _FakeDns({key: None for key in _healthy_dns().records})
    dns.records[(f"s1._domainkey.{DOMAIN}", "TXT")] = None

    findings, statuses = _assess(dns, selectors=["s1"])

    assert findings == []
    assert set(statuses.values()) == {DnsCheckStatus.NOT_EVALUATED}


def test_dns_findings_are_our_own_confirmed_observation():
    findings, _ = _assess(_healthy_dns({(DOMAIN, "CAA"): []}))

    assert findings[0]["confirmed"] is True
    assert findings[0]["service"] == DOMAIN
    assert findings[0]["_provenance"]["retrievedAt"] == "2026-09-28T12:00:00Z"


def test_a_shodan_404_is_an_empty_answer_not_a_failure():
    fetch = _FakeSources({OsintSource.SHODAN: None})
    settings = {OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=True)}

    observations, statuses = collect_host_observations(["93.184.216.34"], fetch, settings)

    assert observations == []
    assert statuses[0].outcome is SourceOutcome.OK
    assert statuses[0].retrieved_at == RETRIEVED_AT


def test_the_age_is_never_negative_for_future_dated_data():
    future = dict(SHODAN_PAYLOAD)
    future["data"] = [{"port": 22, "transport": "tcp", "timestamp": (NOW + timedelta(days=3)).isoformat()}]
    fetch = _FakeSources({OsintSource.SHODAN: future})
    settings = {OsintSource.SHODAN: SourceSetting(is_enabled=True, has_credentials=True)}
    observations, _ = collect_host_observations(["93.184.216.34"], fetch, settings)

    assert build_exposed_service_finding(observations[0], NOW)["_provenance"]["ageDays"] == 0
