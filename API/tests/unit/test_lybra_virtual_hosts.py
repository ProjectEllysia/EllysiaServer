"""Los sitios con nombre de una misma IP: descubrirlos, auditarlos y reportarlos.

Un servidor compartido sirve varias webs detrás de la misma IP y decide cuál
responde por el nombre que dice el cliente. Escanear la IP a secas audita sólo
el sitio por defecto; los nombres de los demás los delatan los certificados
que sirve la propia IP y su DNS inverso.
"""

import socket

import pytest

from src.modules.features.themis.lybra import (
    Service,
    compute_dedup_key,
    has_own_named_sites,
    is_alias_of_default_site,
    mark_default_site_findings,
    score_finding,
    select_site_names,
    site_finding,
)
from src.modules.features.themis.lybra.correlation import DEFAULT_SITE_VHOST
from src.modules.features.themis.lybra.fingerprinting.tls import TlsInfo
from src.modules.features.themis.managers.lybra import engine as engine_module
from src.modules.features.themis.managers.lybra.virtual_hosts import discover_sites

pytestmark = pytest.mark.unit

ADDRESS = "203.0.113.10"


def _tls(*names):
    return TlsInfo(protocol="TLSv1.3", cipher=None, subject_cn=None, issuer_cn=None,
                   self_signed=False, expired=False, days_until_expiry=90, names=names)


# =================================================================== selección


def test_only_concrete_names_that_resolve_back_to_the_ip_are_kept():
    candidates = [
        ("*.ejemplo.test", "cert"),       # comodín: no nombra un sitio
        ("Ejemplo.test.", "cert"),        # se normaliza
        ("ejemplo.test", "ptr"),          # repetido
        ("otra-maquina.test", "cert"),    # resuelve a otra IP
        ("203.0.113.10", "cert"),         # una IP no es un nombre
        ("localhost", "cert"),            # sin punto
        ("www.ejemplo.test", "cert"),
    ]
    ours = {"ejemplo.test", "www.ejemplo.test"}

    selected = select_site_names(candidates, lambda name: name in ours, limit=10)

    assert selected == [("ejemplo.test", "cert"), ("www.ejemplo.test", "cert")]


def test_the_limit_caps_the_sites_and_zero_disables_them():
    candidates = [(f"s{i}.ejemplo.test", "cert") for i in range(5)]
    assert len(select_site_names(candidates, lambda _name: True, limit=2)) == 2
    assert select_site_names(candidates, lambda _name: True, limit=0) == []


def test_names_come_from_certificates_and_the_reverse_dns():
    services = [Service(port=443, protocol="tcp", name="https"),
                Service(port=21, protocol="tcp", name="ftp"),
                Service(port=22, protocol="tcp", name="ssh")]
    fetched = []

    def tls_fetch(host, port, starttls=None):
        fetched.append((host, port, starttls))
        return _tls("web.ejemplo.test") if port == 443 else _tls("panel.proveedor.test")

    sites = discover_sites(
        ADDRESS, services, limit=10, tls_fetch=tls_fetch,
        reverse_lookup=lambda _ip: "host.proveedor.test",
        resolve=lambda _name: {ADDRESS},
    )

    assert fetched == [(ADDRESS, 443, None), (ADDRESS, 21, "ftp")]   # el SSH no tiene certificado
    assert sites == [
        ("web.ejemplo.test", "certificado TLS de 443/tcp"),
        ("panel.proveedor.test", "certificado TLS de 21/tcp"),
        ("host.proveedor.test", "DNS inverso de la IP"),
    ]


# ============================================================= clasificación


def test_the_default_site_web_findings_are_labelled_and_capped_at_low():
    # El certificado y las cabeceras de la página que responde sin nombre no
    # son los que ve ningún visitante cuando la IP aloja otras webs. Lo que
    # describe la máquina (las marcas de tiempo TCP) no cambia.
    findings = [
        {"check_id": "lybra:tls-self-signed-cert@1", "confirmed": True, "category": "tls"},
        {"check_id": "lybra:missing-hsts-header@2", "confirmed": True, "category": "security_header"},
        {"check_id": "lybra:tcp-timestamps-enabled@1", "confirmed": True, "category": "network_config"},
    ]
    assert score_finding(findings[0], "public") == "MEDIUM"

    mark_default_site_findings(findings)

    assert findings[0]["vhost"] == DEFAULT_SITE_VHOST
    assert findings[1]["vhost"] == DEFAULT_SITE_VHOST
    assert score_finding(findings[0], "public") == "LOW"
    assert score_finding(findings[1], "public") == "LOW"
    assert "vhost" not in findings[2]


_PLESK_DEFAULT = {443: (200, "digest-plesk", ("plesk", "plesk", ())), 80: (200, "digest-plesk", None)}


def test_a_name_that_serves_the_same_page_and_certificate_is_an_alias_of_the_default_site():
    assert is_alias_of_default_site(_PLESK_DEFAULT, dict(_PLESK_DEFAULT)) is True


def test_a_name_with_its_own_page_or_certificate_is_a_site_of_its_own():
    own_page = {**_PLESK_DEFAULT, 80: (200, "digest-joomla", None)}
    own_certificate = {**_PLESK_DEFAULT, 443: (200, "digest-plesk", ("web.ejemplo.test", "R3", ("web.ejemplo.test",)))}
    assert is_alias_of_default_site(_PLESK_DEFAULT, own_page) is False
    assert is_alias_of_default_site(_PLESK_DEFAULT, own_certificate) is False


def test_two_sites_that_did_not_answer_are_not_called_aliases():
    # Sin respuesta no hay nada que comparar: ante la duda, se audita.
    silent = {80: (None, None, None)}
    assert is_alias_of_default_site(silent, dict(silent)) is False


def test_only_a_site_that_is_not_an_alias_counts_as_an_own_named_site():
    alias = site_finding("ip203-0-113-10.proveedor.test", "DNS inverso de la IP", serves_default_site=True)
    own = site_finding("web.ejemplo.test", "certificado TLS de 443/tcp")
    assert "sirve el sitio por defecto" in alias["title"]
    assert has_own_named_sites([alias]) is False
    assert has_own_named_sites([alias, own]) is True


def test_the_same_check_on_two_sites_of_the_same_port_are_two_findings():
    base = {"host_id": 1, "port": 443, "check_id": "lybra:missing-hsts-header@2"}
    keys = {compute_dedup_key(base),
            compute_dedup_key({**base, "vhost": "a.ejemplo.test"}),
            compute_dedup_key({**base, "vhost": "b.ejemplo.test"})}
    assert len(keys) == 3


# ================================================================== auditoría


def test_each_site_is_audited_by_name_and_pinned_to_the_scanned_ip(monkeypatch):
    monkeypatch.setattr(engine_module, "discover_sites",
                        lambda *_args, **_kwargs: [("web.ejemplo.test", "certificado TLS de 443/tcp")])
    services = [Service(port=443, protocol="tcp", name="https"), Service(port=22, protocol="tcp", name="ssh")]
    seen = []

    def run_checks(name, web_services):
        seen.append((name, socket.getaddrinfo(name, 443)[0][4][0], [s.port for s in web_services]))
        return [{"check_id": "lybra:missing-hsts-header@2", "port": 443}]

    findings = engine_module._audit_named_sites(ADDRESS, services, lambda: False, run_checks,
                                                view_site=_distinct_views)

    assert seen == [("web.ejemplo.test", ADDRESS, [443])]
    assert [f["category"] for f in findings if "category" in f] == ["virtual_host"]
    assert all(finding["vhost"] == "web.ejemplo.test" for finding in findings)


def test_a_machine_finding_is_not_repeated_for_each_named_site(monkeypatch):
    """Las marcas de tiempo TCP son de la máquina: ya las da el escaneo por IP.

    Repetirlas en cada sitio mostraría el mismo aviso dos veces, idéntico, y lo
    sumaría dos veces en los totales de prioridad.
    """
    monkeypatch.setattr(engine_module, "discover_sites",
                        lambda *_args, **_kwargs: [("web.ejemplo.test", "certificado TLS de 443/tcp")])
    services = [Service(port=80, protocol="tcp", name="http")]

    def run_checks(_name, _web_services):
        return [
            {"check_id": "lybra:x-frame-options-deprecated@1", "category": "security_header", "port": 80},
            {"check_id": "lybra:tcp-timestamps-enabled@1", "category": "network_config", "port": 80},
        ]

    findings = engine_module._audit_named_sites(ADDRESS, services, lambda: False, run_checks,
                                                view_site=_distinct_views)

    check_ids = [finding.get("check_id") for finding in findings if finding.get("category") != "virtual_host"]
    assert check_ids == ["lybra:x-frame-options-deprecated@1"]


def test_a_name_that_only_serves_the_default_site_is_listed_but_not_audited(monkeypatch):
    """El nombre del DNS inverso de un hosting resuelve a la IP pero sirve la
    página por defecto: auditarlo repetiría los hallazgos de ésta con otro
    nombre."""
    monkeypatch.setattr(engine_module, "discover_sites",
                        lambda *_args, **_kwargs: [("ip203-0-113-10.proveedor.test", "DNS inverso de la IP")])
    services = [Service(port=443, protocol="tcp", name="https")]
    audited = []

    findings = engine_module._audit_named_sites(
        ADDRESS, services, lambda: False, lambda name, _web: audited.append(name) or [],
        view_site=lambda _host, _web: {443: (200, "digest-plesk", ("plesk", "plesk", ()))})

    assert audited == []
    assert [finding["category"] for finding in findings] == ["virtual_host"]
    assert findings[0]["_serves_default_site"] is True


def _distinct_views(host, web_services):
    """Cada sitio sirve una página propia: ninguno es alias del sitio por defecto."""
    return {service.port: (200, f"digest-{host}", None) for service in web_services}
