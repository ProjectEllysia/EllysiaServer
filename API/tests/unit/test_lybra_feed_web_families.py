"""Las familias web nuevas del feed: cada una con positivo y señuelo.

La regla de oro del issue es que un check nuevo entra con su señuelo. Un check
que sólo mira el código de estado saca falsos positivos contra un banco de
señuelos —seis a la vez, y el banco ya lo demuestra—, así que cada check de aquí
exige una cadena propia del producto además del 200. Estos tests son esa regla
en pequeño: por cada familia, una respuesta que **debe** disparar y un señuelo
plausible que **no** debe.
"""

import pytest

from src.modules.features.themis.lybra.checks import (
    CheckRuntime,
    Response,
    Service,
    load_checks,
    validate_checks,
)

pytestmark = pytest.mark.unit

_HTTP = Service(80, "tcp", "http", "nginx", "1.18", None)
_CHECKS = load_checks()


def _fetch(by_path):
    def fetch(host, port, method, path, _body=None, _headers=None):
        return by_path.get(path, Response(404, "", {}))
    return fetch


def _fired(by_path):
    findings = CheckRuntime(_CHECKS, _fetch(by_path)).run("10.0.0.5", [_HTTP])
    return {f["check_id"].split(":")[1].split("@")[0] for f in findings}


# =========================================================== forma del feed


def test_the_feed_reached_at_least_fifty_checks():
    """El umbral exigido para el feed: al menos 50 checks."""
    assert len(_CHECKS) >= 50


def test_the_grown_feed_is_still_well_formed():
    assert validate_checks(_CHECKS) == []


# ================================================= paneles y consolas


def test_a_tomcat_manager_is_detected_and_a_bare_200_is_not():
    body = "<html><title>Tomcat Web Application Manager</title></html>"
    assert "tomcat-manager-exposed" in _fired({"/manager/html": Response(200, body, {})})
    # Señuelo: un 200 en /manager/html que no es Tomcat (una SPA cualquiera).
    decoy = Response(200, "<html><title>Mi aplicacion</title></html>", {})
    assert "tomcat-manager-exposed" not in _fired({"/manager/html": decoy})


def test_a_spring_actuator_env_is_detected_and_a_health_ping_is_not():
    env = Response(200, '{"activeProfiles":["prod"],"propertySources":[]}', {})
    assert "spring-actuator-env" in _fired({"/actuator/env": env})
    # Señuelo: /actuator/env devuelve 200 pero con un cuerpo que no es el de env
    # (un 401 disfrazado, o un health accidental).
    decoy = Response(200, '{"status":"UP"}', {})
    assert "spring-actuator-env" not in _fired({"/actuator/env": decoy})


def test_a_jenkins_header_is_detected_and_its_absence_is_not():
    hit = Response(200, "<html></html>", {"x-jenkins": "2.426.3"})
    assert "jenkins-exposed" in _fired({"/": hit})
    assert "jenkins-exposed" not in _fired({"/": Response(200, "<html></html>", {})})


# ================================================= depuración en producción


def test_a_werkzeug_debugger_is_detected_and_a_plain_500_is_not():
    body = "<html><h1>Werkzeug Debugger</h1>Traceback (most recent call last)</html>"
    assert "flask-werkzeug-debugger" in _fired({"/lybra-nonexistent-debug-probe":
                                                Response(500, body, {})})
    # Señuelo: un 500 corriente sin el depurador interactivo.
    decoy = Response(500, "<html>Internal Server Error</html>", {})
    assert "flask-werkzeug-debugger" not in _fired({"/lybra-nonexistent-debug-probe": decoy})


# ================================================= config y control de versiones


def test_an_htpasswd_is_detected_and_a_404_is_not():
    body = "admin:$apr1$abcd$efghijklmnop\n"
    assert "htpasswd-exposure" in _fired({"/.htpasswd": Response(200, body, {})})
    assert "htpasswd-exposure" not in _fired({"/.htpasswd": Response(404, "Not Found", {})})


def test_a_web_config_is_detected_and_an_html_error_page_is_not():
    body = "<configuration><system.webServer></system.webServer></configuration>"
    assert "web-config-exposure" in _fired({"/web.config": Response(200, body, {})})
    # Señuelo: /web.config devuelve la página de la SPA (200) en vez del fichero.
    decoy = Response(200, "<!doctype html><html><body>app</body></html>", {})
    assert "web-config-exposure" not in _fired({"/web.config": decoy})


# ================================================= documentación de API


def test_a_swagger_spec_is_detected_and_an_html_page_is_not():
    body = '{"swagger":"2.0","paths":{}}'
    assert "swagger-json-exposure" in _fired({"/swagger.json": Response(200, body, {})})
    decoy = Response(200, "<html>not found spa route</html>", {})
    assert "swagger-json-exposure" not in _fired({"/swagger.json": decoy})


# ================================================= cabeceras y cookies


def test_a_missing_csp_header_is_detected_and_a_present_one_is_not():
    assert "missing-csp-header" in _fired({"/": Response(200, "<html>", {})})
    present = Response(200, "<html>", {"content-security-policy": "default-src 'self'"})
    assert "missing-csp-header" not in _fired({"/": present})


def test_a_session_cookie_without_secure_is_detected():
    insecure = Response(200, "<html>", {"set-cookie": "PHPSESSID=abc123; HttpOnly; Path=/"})
    assert "session-cookie-without-secure" in _fired({"/": insecure})


def test_a_session_cookie_with_secure_is_not_flagged():
    secure = Response(200, "<html>",
                      {"set-cookie": "PHPSESSID=abc123; Secure; HttpOnly; Path=/"})
    assert "session-cookie-without-secure" not in _fired({"/": secure})


def test_a_non_session_cookie_is_not_flagged():
    """El señuelo del check de cookies: una cookie que no es de sesión (una
    preferencia de idioma, por ejemplo) sin Secure no es un hallazgo."""
    other = Response(200, "<html>", {"set-cookie": "lang=es; Path=/"})
    assert "session-cookie-without-secure" not in _fired({"/": other})


# ================================ criterio de las cabeceras (contraste de campo)


def _https(headers, body="<html>"):
    return Response(200, body, headers, url="https://h/", requested_scheme="https")


def test_joomlas_hex_named_session_cookie_is_recognised():
    """Joomla llama a su cookie de sesión con 32 caracteres hexadecimales."""
    cookie = {"set-cookie": "3e45507a9471bd104ea38b2a131f0ef2=abc; Path=/"}
    fired = _fired({"/": _https(cookie)})
    assert {"session-cookie-without-secure", "session-cookie-without-httponly",
            "session-cookie-without-samesite"} <= fired


def test_a_hardened_session_cookie_raises_nothing():
    cookie = {"set-cookie": "PHPSESSID=abc; Secure; HttpOnly; SameSite=Lax; Path=/"}
    fired = _fired({"/": _https(cookie)})
    assert not fired & {"session-cookie-without-secure", "session-cookie-without-httponly",
                        "session-cookie-without-samesite"}


@pytest.mark.parametrize("max_age,weak", [("60", True), ("15551999", True),
                                           ("15552000", False), ("63072000", False)])
def test_a_short_hsts_max_age_is_flagged(max_age, weak):
    fired = _fired({"/": _https({"strict-transport-security": f"max-age={max_age}"})})
    assert ("hsts-weak-max-age" in fired) is weak


def test_x_frame_options_without_frame_ancestors_is_called_deprecated():
    assert "x-frame-options-deprecated" in _fired({"/": _https({"x-frame-options": "SAMEORIGIN"})})
    modern = {"x-frame-options": "SAMEORIGIN", "content-security-policy": "frame-ancestors 'self'"}
    assert "x-frame-options-deprecated" not in _fired({"/": _https(modern)})


@pytest.mark.parametrize("headers,leaks", [
    ({"x-powered-by": "PHP/8.3.33"}, True),
    ({"server": "nginx/1.18.0"}, True),
    ({"server": "nginx"}, False),
    ({"x-powered-by": "PleskLin"}, False),
])
def test_a_versioned_software_header_is_a_disclosure(headers, leaks):
    assert ("http-version-disclosure" in _fired({"/": _https(headers)})) is leaks


def test_compression_over_https_with_cookies_is_a_possible_breach():
    compressed = {"content-encoding": "gzip", "set-cookie": "sid=1"}
    assert "http-compression-breach" in _fired({"/": _https(compressed)})
    assert "http-compression-breach" not in _fired({"/": _https({"content-encoding": "gzip"})})


# ==================================================================== Joomla

# Un sitio que contesta 200 con la misma página a cualquier ruta: el señuelo
# que ningún check de Joomla debe confundir con un hallazgo.
_CATCH_ALL = Response(200, "<html><title>Inicio</title>joomla</html>", {})


class _CatchAll(dict):
    """Un ``by_path`` que responde ``_CATCH_ALL`` a cualquier ruta que no conozca."""

    def get(self, path, _default=None):
        return super().get(path, _CATCH_ALL)


def test_a_joomla_configuration_backup_is_detected():
    fired = _fired({"/configuration.php.bak": Response(
        200, "<?php\nclass JConfig {\n\tpublic $password = 'x';\n}", {})})
    assert "joomla-configuration-backup" in fired


def test_the_joomla_installer_and_admin_panel_are_detected():
    fired = _fired({
        "/installation/index.php": Response(200, "<title>Joomla! Web Installer</title>", {}),
        "/administrator/": Response(200, '<form action="index.php?option=com_login">', {}),
    })
    assert {"joomla-installation-directory", "joomla-admin-exposed"} <= fired


def test_a_site_that_answers_200_to_everything_fires_no_joomla_check():
    fired = _fired(_CatchAll())
    assert not {name for name in fired if name.startswith("joomla-")}
