"""Higiene web de menor peso: COOP, caché de la respuesta de sesión y prefijos de cookie.

Cabeceras y prácticas que, una a una, no comprometen un sitio, pero que cierran
la familia de higiene web del feed. Cada check entra con un positivo y con un
señuelo: la misma respuesta con la práctica bien aplicada, que no debe disparar.
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
_SESSION = "PHPSESSID=abc123; Secure; HttpOnly; Path=/"


def _fired(response):
    def fetch(host, port, method, path, _body=None, _headers=None):
        return response if path == "/" else Response(404, "", {})

    findings = CheckRuntime(_CHECKS, fetch).run("10.0.0.5", [_HTTP])
    return {f["check_id"].split(":")[1].split("@")[0] for f in findings}


def test_the_feed_is_still_well_formed():
    assert validate_checks(_CHECKS) == []


# ============================================== Cross-Origin-Opener-Policy


def test_a_missing_coop_header_is_detected_and_a_present_one_is_not():
    assert "missing-coop-header" in _fired(Response(200, "<html>", {}))
    present = Response(200, "<html>", {"cross-origin-opener-policy": "same-origin"})
    assert "missing-coop-header" not in _fired(present)


def test_coop_is_not_asked_of_a_redirect_to_https():
    redirect = Response(200, "<html>", {}, url="https://example.com/", requested_scheme="http")
    assert "missing-coop-header" not in _fired(redirect)


# ============================================== caché de la respuesta de sesión


def test_a_cacheable_session_response_is_detected():
    response = Response(200, "<html>", {"set-cookie": _SESSION})
    assert "session-response-cacheable" in _fired(response)


@pytest.mark.parametrize("cache_control", ["no-store", "private, max-age=0", "no-cache, no-store, must-revalidate"])
def test_a_session_response_that_forbids_caching_is_not_flagged(cache_control):
    response = Response(200, "<html>", {"set-cookie": _SESSION, "cache-control": cache_control})
    assert "session-response-cacheable" not in _fired(response)


def test_a_response_without_a_session_cookie_is_not_flagged_for_caching():
    """Señuelo: sin cookie de sesión no hay nada privado que una caché pueda servir a otro."""
    response = Response(200, "<html>", {"set-cookie": "lang=es; Path=/"})
    assert "session-response-cacheable" not in _fired(response)


def test_a_redirect_that_sets_the_session_is_not_flagged_for_caching():
    response = Response(302, "", {"set-cookie": _SESSION, "location": "/home"})
    assert "session-response-cacheable" not in _fired(response)


# ============================================== prefijos de nombre de cookie


def test_a_session_cookie_without_prefix_is_detected_and_a_prefixed_one_is_not():
    assert "session-cookie-without-prefix" in _fired(
        Response(200, "<html>", {"set-cookie": _SESSION}))
    prefixed = Response(200, "<html>", {"set-cookie": "__Host-session=abc; Secure; Path=/; HttpOnly"})
    assert "session-cookie-without-prefix" not in _fired(prefixed)


def test_a_non_session_cookie_is_not_flagged_for_lacking_a_prefix():
    assert "session-cookie-without-prefix" not in _fired(
        Response(200, "<html>", {"set-cookie": "lang=es; Path=/"}))


@pytest.mark.parametrize("cookie", [
    "__Host-session=abc; Path=/; HttpOnly",                         # sin Secure
    "__Secure-session=abc; Path=/; HttpOnly",                       # sin Secure
    "__Host-session=abc; Secure; Path=/; Domain=example.com",       # Domain prohibido
    "__Host-session=abc; Secure; Path=/app",                        # Path distinto de /
    "__Host-session=abc; Secure",                                   # sin Path
])
def test_a_prefixed_cookie_that_breaks_its_own_requirements_is_detected(cookie):
    assert "cookie-prefix-requirements-unmet" in _fired(Response(200, "<html>", {"set-cookie": cookie}))


@pytest.mark.parametrize("cookie", [
    "__Host-session=abc; Secure; Path=/; HttpOnly; SameSite=Lax",
    "__Host-session=abc; Path=/; Secure",
    "__Secure-session=abc; Secure; Path=/app",                      # __Secure- no exige Path=/
    "session=abc; Path=/app",                                       # sin prefijo: no es de este check
])
def test_a_cookie_that_meets_its_prefix_requirements_is_not_flagged(cookie):
    assert "cookie-prefix-requirements-unmet" not in _fired(Response(200, "<html>", {"set-cookie": cookie}))
