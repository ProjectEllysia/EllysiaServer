"""Aplicabilidad por componente: las CVEs del cliente SSH no se atribuyen a un sshd.

La NVD publica con el mismo CPE (``openbsd:openssh``) los fallos del servidor y
los del cliente ``ssh``/``scp``/``sftp``/``ssh-agent``. En el contraste de campo,
8 de las 21 CVEs que Lybra atribuyó a un OpenSSH eran del cliente y otras 8
sólo aplicaban con una opción concreta de ``sshd_config``.
"""

import re
import types

import pytest

from src.modules.features.themis.lybra import score_finding
from src.modules.features.themis.lybra.applicability import (
    classify_cve_applicability,
    load_cve_applicability,
)
from src.modules.features.themis.lybra.correlation import CONDITIONAL_VERSION_CHECK_ID
from src.modules.features.themis.lybra.engine import LybraEngine, Service

pytestmark = pytest.mark.unit


def _cve(cve_id, description="", cvss=6.5):
    return types.SimpleNamespace(cve_id=cve_id, cvss_score=cvss, cvss_vector=None, severity=None,
                                 required_os=None, description=description)


# regreSSHion (servidor, aplica), un fallo sólo de cliente y uno condicionado.
_CVES = [_cve("CVE-2024-6387", cvss=8.1), _cve("CVE-2025-26465"), _cve("CVE-2026-59999")]


def _analyze(origin="network"):
    engine = LybraEngine(cve_lookup=lambda vendor, product, version: list(_CVES))
    service = Service(22, "tcp", "ssh", "OpenSSH", "9.6p1", "cpe:/a:openbsd:openssh:9.6p1",
                      origin=origin)
    return engine.analyze([service])


# ================================================================= clasificación


@pytest.mark.parametrize("cve_id,expected", [
    ("CVE-2025-26465", ("client", None)),                 # VerifyHostKeyDNS del cliente
    ("CVE-2026-73281", ("client", None)),                 # ssh-agent
    ("CVE-2024-6387", None),                              # regreSSHion: sshd, aplica
])
def test_curated_openssh_cves(cve_id, expected):
    assert classify_cve_applicability("openbsd", "openssh", cve_id) == expected


def test_a_config_dependent_cve_carries_its_condition():
    kind, condition = classify_cve_applicability("openbsd", "openssh", "CVE-2026-59999")
    assert kind == "condition"
    assert "PermitTunnel" in condition


@pytest.mark.parametrize("description,expected", [
    ("In ssh-agent in OpenSSH before 9.9, a remote attacker can ...", ("client", None)),
    ("scp in OpenSSH before 9.9 allows a malicious remote host to ...", ("client", None)),
    ("sshd in OpenSSH before 9.9 allows remote attackers to ...", None),
    ("sftp-server in OpenSSH before 9.9 ...", None),     # nombra al servidor: no es de cliente
    ("OpenSSH before 9.9 mishandles ...", None),          # no dice de qué: aplica
])
def test_the_heuristic_reads_the_nvd_description_of_uncurated_cves(description, expected):
    assert classify_cve_applicability("openbsd", "openssh", "CVE-2099-0001", description) == expected


def test_products_outside_the_feed_are_never_filtered():
    assert classify_cve_applicability("apache", "http_server", "CVE-2099-0001",
                                      "The ssh-agent client ...") is None


def test_the_feed_is_well_formed():
    """Mismo papel que el test del feed de checks: un dato mal escrito no puede
    apagar el filtro en silencio."""
    for key, entry in load_cve_applicability().items():
        assert re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_.-]+", key), key
        for cve_id, verdict in entry["cves"].items():
            assert re.fullmatch(r"CVE-\d{4}-\d{4,}", cve_id), cve_id
            assert verdict["component"] in ("client", "server"), cve_id
            if verdict["component"] == "server":
                assert verdict.get("condition"), f"{cve_id}: una CVE de servidor curada necesita su condición"


# ======================================================================= motor


def test_a_network_sshd_drops_client_cves_and_says_so():
    findings = _analyze()
    cves = [f["cve_ids"][0] for f in findings if f["category"] == "outdated_software"]
    port = next(f for f in findings if f["category"] == "open_port")

    assert cves == ["CVE-2024-6387", "CVE-2026-59999"]
    assert "1 CVE(s) sólo de cliente descartadas" in port["title"]


def test_a_config_dependent_cve_is_marked_and_capped_at_low():
    conditional = next(f for f in _analyze() if f.get("cve_ids") == ["CVE-2026-59999"])

    assert conditional["check_id"] == CONDITIONAL_VERSION_CHECK_ID
    assert "sólo si:" in conditional["title"]
    assert score_finding(dict(conditional, cvss_score=9.8), "public") == "LOW"


def test_an_inventory_package_keeps_every_cve():
    """Instalado en la máquina, el cliente sí puede usarse contra un servidor malicioso."""
    findings = _analyze(origin="inventory")
    cves = sorted(f["cve_ids"][0] for f in findings if f["category"] == "outdated_software")

    assert cves == ["CVE-2024-6387", "CVE-2025-26465", "CVE-2026-59999"]
    assert not any(f.get("check_id") == CONDITIONAL_VERSION_CHECK_ID for f in findings)
