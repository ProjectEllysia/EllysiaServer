"""Verificación de backports contra la palabra del proveedor.

Un backport es una distribución corrigiendo un fallo sin subir el número de
versión visible: Debian parchea `apache2`, el banner sigue diciendo `2.4.49`, y
el motor emite una CVE que ya no existe. La tasa medida es **0,42**:
cuatro de cada diez CVEs reportados contra un Debian o un Ubuntu ya estaban
corregidos.

Lo que se fija aquí es sobre todo **cuándo no se toca nada**. Bajar un hallazgo
por una suposición cambiaría falsos positivos por falsos negativos, que en un
escáner es el peor negocio posible.
"""

from __future__ import annotations

import pytest

from src.modules.features.themis.lybra.backports import (
    BACKPORT_CHECK_ID, apply_backport_verdicts,
)
from src.modules.features.themis.lybra.distro import infer_distro_release

pytestmark = pytest.mark.unit


def _finding(**overrides) -> dict:
    base = {
        "category": "outdated_software",
        "title": "apache2 2.4.49 — CVE-2021-41773",
        "cve_ids": ["CVE-2021-41773"],
        "confirmed": False,
        "qod": 70,
        "state": "open",
        "check_id": "lybra:version-match@1",
        "_installed_version": "2.4.49-1~deb11u1",
        "_package_name": "apache2",
    }
    base.update(overrides)
    return base


def _says(status, fixed_in=None):
    return lambda *_args: (status, fixed_in)


# ───────────────────────────────── el desmentido

def test_a_backported_package_is_marked_fixed():
    findings = apply_backport_verdicts(
        [_finding()], _says("fixed", "2.4.49-1~deb11u1"))

    assert findings[0]["state"] == "fixed"
    assert findings[0]["fixed_reason"] == "backport", "no es una remediación del cliente"
    assert findings[0]["confirmed"] is False
    assert findings[0]["check_id"] == BACKPORT_CHECK_ID


def test_a_host_behind_the_fix_is_not_absolved():
    """Que Debian lo corrigiera en `-1~deb11u2` no dice nada bueno de un host
    que sigue en `-1~deb11u1`. Sin esta comparación, la verificación
    desmentiría hallazgos legítimos — peor que no tenerla."""
    findings = apply_backport_verdicts(
        [_finding(_installed_version="2.4.49-1~deb11u1")],
        _says("fixed", "2.4.49-1~deb11u2"))

    assert findings[0]["state"] == "open"
    assert findings[0]["check_id"] == "lybra:version-match@1"


# ───────────────────────────────── la confirmación

def test_a_vendor_confirming_the_flaw_promotes_the_finding():
    """Dos fuentes independientes coinciden: la versión y el propio
    empaquetador. Eso es mucho más que una deducción."""
    findings = apply_backport_verdicts([_finding()], _says("vulnerable"))

    assert findings[0]["confirmed"] is True
    assert findings[0]["qod"] == 90
    assert findings[0]["state"] == "open"


# ───────────────────────────────── cuándo no se toca nada

def test_a_package_with_no_distro_is_left_alone():
    """Un binario compilado a mano no pertenece a ninguna distribución, y es
    justo el caso donde la vulnerabilidad sí existe."""
    called = []

    def lookup(*args):
        called.append(args)
        return ("fixed", "2.4.50")

    findings = apply_backport_verdicts(
        [_finding(_installed_version="2.4.49", title="Apache 2.4.49 — CVE-2021-41773")],
        lookup)

    assert called == [], "no había distribución: no había a quién preguntar"
    assert findings[0]["state"] == "open"


def test_a_vendor_that_has_not_spoken_changes_nothing():
    """`None` no significa "está a salvo": significa que no consta."""
    findings = apply_backport_verdicts([_finding()], lambda *_a: None)
    assert findings[0]["state"] == "open"
    assert findings[0]["confirmed"] is False


def test_an_unknown_status_changes_nothing():
    """El proveedor conoce el paquete pero no se pronuncia. Traducirlo a
    cualquiera de los otros dos estados sería inventar."""
    findings = apply_backport_verdicts([_finding()], _says("unknown"))
    assert findings[0]["state"] == "open"


def test_findings_that_are_not_version_matches_are_ignored():
    """Un puerto abierto o una cabecera ausente no nacen de comparar versiones,
    así que ningún backport puede desmentirlos."""
    other = {"category": "open_port", "title": "80/tcp abierto", "state": "open"}
    findings = apply_backport_verdicts([dict(other)], _says("fixed", "9.9.9"))
    assert findings[0] == other


def test_a_version_finding_without_cves_is_ignored():
    findings = apply_backport_verdicts([_finding(cve_ids=[])], _says("fixed", "9.9.9"))
    assert findings[0]["state"] == "open"


# ───────────────────────────── de qué distribución es esto

@pytest.mark.parametrize("version,vendor,release", [
    ("1:2.4.49-1~deb11u1", "debian", "11"),
    ("2.4.49-1ubuntu1", "ubuntu", None),
    ("2.4.37-43.el8", "rhel", "8"),
    ("2.4.49-r0", "alpine", None),
])
def test_the_package_revision_names_its_distribution(version, vendor, release):
    """La señal más fuerte no es el banner sino la revisión: sólo la escribe
    quien empaqueta, así que no admite ambigüedad."""
    inferred = infer_distro_release(version)
    assert inferred is not None
    assert (inferred.vendor, inferred.release) == (vendor, release)


def test_the_banner_answers_when_the_version_does_not():
    assert infer_distro_release("2.4.49", "Apache/2.4.49 (Ubuntu)").vendor == "ubuntu"


def test_nothing_is_inferred_from_a_plain_version():
    assert infer_distro_release("2.4.49", "Apache httpd") is None


# ───────────────────────────────── un OpenSSH visto por la red

# Lo que produce el escaneo de un OpenSSH de Ubuntu 24.04: la versión con la
# revisión que el banner firma (`Ubuntu-3ubuntu13.19`), el servicio `ssh` y el
# CPE de la NVD, que llama al producto `openssh` como el paquete fuente.
_REGRESSHION = {
    "category": "outdated_software",
    "title": "OpenSSH 9.6p1-3ubuntu13.19 — CVE-2024-6387",
    "cve_ids": ["CVE-2024-6387"],
    "confirmed": False,
    "qod": 70,
    "state": "open",
    "check_id": "lybra:version-match@1",
    "service": "ssh",
    "cpe": "cpe:2.3:a:openbsd:openssh:9.6p1-3ubuntu13.19:*:*:*:*:*:*:*",
    "_installed_version": "9.6p1-3ubuntu13.19",
}


def _ubuntu_feed(vendor, release, package, cve_id):
    """El aviso real de Ubuntu 24.04 para regreSSHion, y nada más."""
    if (vendor, release, package, cve_id) == ("ubuntu", "24.04", "openssh", "CVE-2024-6387"):
        return "fixed", "1:9.6p1-3ubuntu13.3"
    return None


def test_the_package_is_asked_by_its_cpe_product_not_by_its_service_name():
    """El servicio de un OpenSSH se llama `ssh`; la distribución lo publica como
    `openssh`. Preguntando por el servicio no se encontraba nunca nada."""
    asked = []

    def lookup(vendor, release, package, cve_id):
        asked.append(package)

    apply_backport_verdicts([dict(_REGRESSHION)], lookup)
    assert asked == ["openssh"]


def test_an_nvd_product_is_translated_to_its_distro_package():
    finding = dict(_REGRESSHION, cpe="cpe:2.3:a:apache:http_server:2.4.49:*:*:*:*:*:*:*",
                   _installed_version="2.4.49-1ubuntu1")
    asked = []
    apply_backport_verdicts([finding], lambda *args: asked.append(args[2]))
    assert asked == ["apache2"]


def test_the_ubuntu_release_is_deduced_when_the_revision_does_not_name_it():
    """`3ubuntu13.19` dice Ubuntu pero no 24.04: la release sale del espejo."""
    findings = apply_backport_verdicts(
        [dict(_REGRESSHION)], _ubuntu_feed,
        release_lookup=lambda vendor, package, version: "24.04")

    assert findings[0]["state"] == "fixed"
    assert findings[0]["check_id"] == BACKPORT_CHECK_ID


def test_without_a_release_the_ubuntu_advisory_is_not_found():
    findings = apply_backport_verdicts([dict(_REGRESSHION)], _ubuntu_feed)
    assert findings[0]["state"] == "open"


# ───────────────────────────────── lo que nadie pudo contrastar

from src.modules.features.themis.lybra.backports import is_unverified_distro_package  # noqa: E402


@pytest.mark.parametrize("overrides,expected", [
    ({}, True),                                                        # Ubuntu, sin pronunciamiento
    ({"cpe": "cpe:2.3:a:openbsd:openssh:9.6p1:*:*:*:*:*:*:*",
      "title": "OpenSSH 9.6p1 — CVE-2024-6387", "_installed_version": ""}, False),  # compilado a mano
    ({"confirmed": True}, False),                                      # el proveedor dijo vulnerable
    ({"state": "fixed"}, False),                                       # el proveedor lo desmintió
    ({"check_id": BACKPORT_CHECK_ID}, False),
    ({"category": "exposed_path"}, False),
    ({"cve_ids": []}, False),
])
def test_a_distro_package_without_a_verdict_is_unverified(overrides, expected):
    assert is_unverified_distro_package(dict(_REGRESSHION, **overrides)) is expected


def test_the_signal_survives_a_round_trip_through_the_database():
    """Leído de la base de datos no hay `_installed_version`: basta el CPE."""
    stored = {k: v for k, v in _REGRESSHION.items() if not k.startswith("_")}
    assert is_unverified_distro_package(stored) is True


def test_a_network_apache_is_asked_as_apache2():
    """El producto de un servicio de red es una etiqueta («Apache httpd»); el
    motor no la pasa como nombre de paquete, y la verificación usa el CPE."""
    from src.modules.features.themis.lybra.engine import LybraEngine, Service
    import types

    engine = LybraEngine(cve_lookup=lambda *a: [types.SimpleNamespace(
        cve_id="CVE-2021-41773", cvss_score=7.5, cvss_vector=None, severity=None, required_os=None)])
    service = Service(80, "tcp", "http", "Apache httpd", "2.4.49-1ubuntu1",
                      "cpe:/a:apache:http_server:2.4.49")
    finding = next(f for f in engine.analyze([service]) if f["category"] == "outdated_software")

    asked = []
    apply_backport_verdicts([finding], lambda *args: asked.append(args[2]))
    assert asked == ["apache2"]
