"""Lo que el rastreo descubre navegando alimenta tres checks concretos.

El rastreador ya sabía qué directorios reales tiene un sitio y en qué ruta
vio un formulario de acceso, pero sólo generaba un aviso informativo de
"formulario detectado", sin comprobar nada más sobre esa ruta. Esta necesidad
conecta tres comprobaciones ya existentes a lo que el rastreo descubrió: las
copias de backup y el listado de directorios se repiten sobre cada
**directorio**, y el formulario de acceso servido por HTTP mira la **ruta
exacta** de cada login descubierto — de ahí el mecanismo nuevo,
``onDiscoveredPaths``, que sustituye la ruta de la petición en vez de
anteponerle un directorio.
"""

import pytest

from src.modules.features.themis.lybra.checks import (
    Check,
    CheckRuntime,
    Matcher,
    Request,
    Response,
    Service,
    load_checks,
    validate_checks,
)

pytestmark = pytest.mark.unit

_SERVICE = Service(80, "tcp", "http", None, None, None)


def _feed():
    checks = {check.id: check for check in load_checks()}
    return (
        checks["backup-file-near-discovered-directory"],
        checks["directory-listing-enabled"],
        checks["login-form-served-over-http"],
    )


def _site(files):
    def fetch(host, port, method, path, body=None, headers=None):
        if path in files:
            status, body_text, headers_out = files[path]
            return Response(status, body_text, headers_out, requested_scheme="http", url=f"http://x{path}")
        return Response(404, "Not Found", {}, requested_scheme="http", url=f"http://x{path}")
    return fetch


def _run(check, fetch, **kwargs):
    return CheckRuntime([check], fetch).run("10.0.0.1", [_SERVICE], **kwargs)


# ============================================================ onDiscoveredPaths, el mecanismo


def test_a_discovered_path_replaces_the_check_own_path_entirely():
    check = Check(
        id="probe", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={"title": "x"}, runs_on_discovered_paths=True,
        requests=(Request(path="/placeholder", matchers=(
            Matcher(type="status", values=(200,)),)),),
    )
    fetch = _site({"/cuenta/acceso": (200, "ok", {})})

    findings = _run(check, fetch, discovered_paths={80: ["/cuenta/acceso"]})

    assert [f["check_id"] for f in findings] == ["lybra:probe@1"]
    assert findings[0]["title"] == "x (en /cuenta/acceso)"


def test_without_any_discovered_path_only_the_feed_path_is_tried():
    check = Check(
        id="probe", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={"title": "x"}, runs_on_discovered_paths=True,
        requests=(Request(path="/placeholder", matchers=(
            Matcher(type="status", values=(200,)),)),),
    )
    fetch = _site({"/cuenta/acceso": (200, "ok", {})})

    assert _run(check, fetch) == []


def test_a_hit_on_the_feed_path_itself_is_not_replaced():
    check = Check(
        id="probe", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={"title": "x"}, runs_on_discovered_paths=True,
        requests=(Request(path="/placeholder", matchers=(
            Matcher(type="status", values=(200,)),)),),
    )
    fetch = _site({"/placeholder": (200, "ok", {}), "/cuenta/acceso": (200, "ok", {})})

    findings = _run(check, fetch, discovered_paths={80: ["/cuenta/acceso"]})

    assert findings[0]["title"] == "x"                        # sin sufijo "(en ...)"


def test_paths_of_another_port_do_not_apply():
    check = Check(
        id="probe", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={"title": "x"}, runs_on_discovered_paths=True,
        requests=(Request(path="/placeholder", matchers=(
            Matcher(type="status", values=(200,)),)),),
    )
    fetch = _site({"/cuenta/acceso": (200, "ok", {})})

    assert _run(check, fetch, discovered_paths={8080: ["/cuenta/acceso"]}) == []


def test_a_post_request_is_rejected_by_validation():
    check = Check(
        id="bad", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={}, runs_on_discovered_paths=True,
        requests=(Request(method="POST", path="/login", matchers=(
            Matcher(type="status", values=(200,)),)),),
    )

    assert any("onDiscoveredPaths" in problem for problem in validate_checks([check]))


def test_a_root_path_is_now_a_valid_target_for_discovered_directories():
    """Relajación de #1045: el listado de directorios necesita poder repetir
    su propia ruta raíz sobre cada directorio descubierto."""
    check = Check(
        id="ok", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={}, runs_on_discovered_directories=True,
        requests=(Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),),
    )

    assert validate_checks([check]) == []


# ============================================================ los tres checks del feed


def test_a_backup_file_near_a_discovered_directory_fires():
    """El criterio de cierre de esta parte: la copia cuelga de un directorio
    que sólo el rastreo descubrió, no de la raíz."""
    backup_check, _listing_check, _login_check = _feed()
    fetch = _site({"/admin/config.php.bak": (200, "<?php $db_pass = 'x';", {})})

    findings = _run(backup_check, fetch, discovered_directories={80: ["/admin/"]})

    assert findings[0]["check_id"] == "lybra:backup-file-near-discovered-directory@1"
    assert findings[0]["title"].endswith("(en /admin/)")


def test_a_discovered_directory_with_nothing_stale_does_not_fire_the_backup_check():
    backup_check, _listing_check, _login_check = _feed()
    fetch = _site({"/admin/index.html": (200, "<html></html>", {})})

    assert _run(backup_check, fetch, discovered_directories={80: ["/admin/"]}) == []


def test_directory_listing_fires_on_a_discovered_directory_not_just_the_root():
    """El criterio de cierre de esta parte: el listado está en un directorio
    real, la raíz se sirve normal."""
    _backup_check, listing_check, _login_check = _feed()
    fetch = _site({
        "/": (200, "<html>Bienvenido</html>", {}),
        "/uploads/": (200, "<title>Directory listing for /uploads/</title>", {}),
    })

    findings = _run(listing_check, fetch, discovered_directories={80: ["/uploads/"]})

    assert findings[0]["check_id"] == "lybra:directory-listing-enabled@1"
    assert findings[0]["title"].endswith("(en /uploads/)")


def test_the_root_still_fires_the_listing_check_without_any_discovery():
    """Señuelo: el comportamiento de siempre no cambia."""
    _backup_check, listing_check, _login_check = _feed()
    fetch = _site({"/": (200, "<title>Directory listing for /</title>", {})})

    findings = _run(listing_check, fetch)

    assert findings[0]["check_id"] == "lybra:directory-listing-enabled@1"
    assert findings[0]["title"] == "Listado de directorios activo (el servidor enumera ficheros)"


def test_a_discovered_login_form_over_plain_http_fires():
    """El criterio de cierre del Issue: un formulario de acceso real, en una
    ruta que el rastreador descubrió navegando, servido por HTTP."""
    _backup_check, _listing_check, login_check = _feed()
    fetch = _site({"/cuenta/acceso": (200, "<form><input type=password></form>", {})})

    findings = _run(login_check, fetch, discovered_paths={80: ["/cuenta/acceso"]})

    assert findings[0]["check_id"] == "lybra:login-form-served-over-http@1"
    assert findings[0]["title"].endswith("(en /cuenta/acceso)")


def test_the_same_login_form_over_https_does_not_fire():
    """Señuelo directo del Issue: el mismo formulario por HTTPS no dispara."""
    _backup_check, _listing_check, login_check = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        if path == "/cuenta/acceso":
            return Response(200, "<form></form>", {}, requested_scheme="https",
                            url="https://x/cuenta/acceso")
        return Response(404, "", {}, requested_scheme="https", url=f"https://x{path}")

    assert _run(login_check, fetch, discovered_paths={80: ["/cuenta/acceso"]}) == []


def test_a_discovered_directory_with_nothing_wrong_fires_none_of_the_three():
    """El señuelo conjunto del Issue: sin backup, sin listado, login por
    HTTPS — ningún aviso."""
    backup_check, listing_check, login_check = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        if path == "/cuenta/acceso":
            return Response(200, "<form></form>", {}, requested_scheme="https",
                            url="https://x/cuenta/acceso")
        if path == "/panel/":
            return Response(200, "<html>panel</html>", {}, requested_scheme="http",
                            url="http://x/panel/")
        return Response(404, "", {}, requested_scheme="http", url=f"http://x{path}")

    assert _run(backup_check, fetch, discovered_directories={80: ["/panel/"]}) == []
    assert _run(listing_check, fetch, discovered_directories={80: ["/panel/"]}) == []
    assert _run(login_check, fetch, discovered_paths={80: ["/cuenta/acceso"]}) == []


def test_the_shipped_feed_is_still_well_formed():
    assert validate_checks(load_checks()) == []
