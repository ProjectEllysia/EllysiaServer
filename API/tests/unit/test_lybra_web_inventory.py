"""El inventario web: el CMS, sus librerías y el panel, con su versión.

Casi todo el riesgo de una web está en la aplicación y no en el servidor, y la
correlación de CVEs necesita la versión. La tecnología moderna ya no la anuncia
en la portada: Joomla 4 y 5 la quitan de la etiqueta *generator*, pero la dejan
en el manifiesto que publican en una ruta fija, y las librerías JavaScript la
llevan en la URL o en la cabecera de licencia del fichero.
"""

from types import SimpleNamespace

import pytest

from src.modules.features.themis.lybra import LybraEngine, compute_dedup_key
from src.modules.features.themis.lybra.checks import Response
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.http import (
    fingerprint_http,
    load_tech_signatures,
    validate_tech_signatures,
    web_components,
)

pytestmark = pytest.mark.unit

JOOMLA_HOME = """<html><head>
<meta name="generator" content="Joomla! - Open Source Content Management">
<script src="/media/vendor/jquery/js/jquery.min.js?3.7.1" defer></script>
<script src="/media/vendor/bootstrap/js/bootstrap-es5.min.js?5.3.8" nomodule defer></script>
<script src="/media/system/js/core.min.js?2cb912"></script>
</head><body>Hola</body></html>"""

FILES = {
    "/administrator/manifests/files/joomla.xml":
        "<extension><name>files_joomla</name><version>5.4.8</version></extension>",
    "/media/vendor/jquery/js/jquery.min.js": "/*! jQuery v3.7.1 | (c) OpenJS Foundation */",
}


def _response(body, headers=None):
    return Response(status=200, body=body, headers=headers or {"server": "Apache"})


def _fetcher(files):
    requested = []

    def fetch_path(path):
        requested.append(path)
        return files.get(path)
    return fetch_path, requested


def test_the_bundled_feed_is_well_formed():
    assert validate_tech_signatures(load_tech_signatures()) == []


def test_a_joomla_5_without_generator_version_gets_it_from_its_manifest():
    fetch_path, requested = _fetcher(FILES)
    response = _response(JOOMLA_HOME)

    components = web_components(fingerprint_http(response), response.body, fetch_path)

    assert ("Joomla", "5.4.8") in components
    assert requested[0] == "/administrator/manifests/files/joomla.xml"


def test_javascript_libraries_take_their_version_from_the_url():
    fetch_path, requested = _fetcher(FILES)
    response = _response(JOOMLA_HOME)

    components = dict(web_components(fingerprint_http(response), response.body, fetch_path))

    assert components["jQuery"] == "3.7.1"
    assert components["Bootstrap"] == "5.3.8"
    assert not any(path.endswith(".js") for path in requested)   # la URL bastó


def test_a_local_library_without_version_in_the_url_is_read_from_its_header():
    body = '<script src="/media/vendor/jquery/js/jquery.min.js"></script>'
    fetch_path, requested = _fetcher(FILES)

    components = dict(web_components(fingerprint_http(_response(body)), body, fetch_path))

    assert components["jQuery"] == "3.7.1"
    assert requested == ["/media/vendor/jquery/js/jquery.min.js"]


def test_a_script_on_another_domain_is_never_fetched():
    body = '<script src="https://cdn.ajeno.test/js/jquery.min.js"></script>'
    fetch_path, requested = _fetcher(FILES)

    components = dict(web_components(fingerprint_http(_response(body)), body, fetch_path))

    assert components["jQuery"] is None
    assert requested == []


def test_a_signature_that_did_not_match_sends_no_probes():
    body = "<html><body>Una web cualquiera</body></html>"
    fetch_path, requested = _fetcher(FILES)

    assert web_components(fingerprint_http(_response(body)), body, fetch_path) == ()
    assert requested == []


def test_the_hosting_panel_is_inventoried_from_x_powered_by():
    response = _response("<html></html>", {"server": "Apache", "x-powered-by": "PleskLin"})
    fetch_path, _requested = _fetcher({})

    assert ("Plesk", None) in web_components(fingerprint_http(response), response.body, fetch_path)


# ====================================================================== motor


def test_each_component_is_correlated_as_a_service_of_its_port():
    cve = SimpleNamespace(cve_id="CVE-2023-23752", cvss_score=5.3, cvss_vector=None,
                          severity="MEDIUM", required_os=None)
    engine = LybraEngine(
        cve_lookup=lambda vendor, product, version: [cve] if product == "joomla\\!" else [])
    service = Service(443, "tcp", "https", "Apache httpd", "2.4.62",
                      components=(("Joomla", "4.2.7"), ("jQuery", "3.7.1")))

    findings = engine.analyze([service])

    inventory = [f for f in findings if f["category"] == "web_component"]
    assert [f["service"] for f in inventory] == ["Joomla", "jQuery"]
    assert len({compute_dedup_key({**f, "host_id": 1}) for f in inventory}) == 2
    vulnerable = [f for f in findings if f.get("cve_ids")]
    assert [(f["cve_ids"], f["port"]) for f in vulnerable] == [(["CVE-2023-23752"], 443)]


# ============================================================ plugins de WordPress

WORDPRESS_HOME = """<html><head>
<meta name="generator" content="WordPress 6.5.2">
<link rel="stylesheet" href="/wp-content/plugins/contact-form-7/includes/css/styles.css?ver=5.9.3">
<script src="/wp-content/plugins/elementor/assets/js/frontend.min.js"></script>
</head><body>wp-content</body></html>"""


def test_wordpress_plugins_are_inventoried_with_their_version():
    fetch_path, requested = _fetcher({
        "/wp-content/plugins/elementor/readme.txt": "=== Elementor ===\nStable tag: 3.21.0\n"})
    response = _response(WORDPRESS_HOME)

    components = dict(web_components(fingerprint_http(response), response.body, fetch_path))

    assert components["contact-form-7"] == "5.9.3"            # del ?ver= del asset
    assert components["elementor"] == "3.21.0"                # del readme.txt
    assert requested == ["/wp-content/plugins/elementor/readme.txt"]

