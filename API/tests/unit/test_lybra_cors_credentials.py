"""CORS: una web que deja a cualquier otra web leer sus respuestas con la sesión del usuario.

Un navegador bloquea, por defecto, que una página de un origen lea las
respuestas de otro origen donde el usuario tiene sesión iniciada. Una web sólo
es vulnerable cuando desactiva esa protección **mal**: aceptando cualquier
origen y, a la vez, dejando viajar las credenciales (cookies de sesión) con la
petición. Aceptar cualquier origen sin credenciales es habitual y no es, por sí
solo, el hallazgo — por eso cada check exige las dos cosas a la vez.
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

_SERVICE = Service(80, "tcp", "http", None, None, None)
_ORIGIN_A = "https://lybra-cors-probe-a.invalid"
_ORIGIN_B = "https://lybra-cors-probe-b.invalid"


def _feed():
    checks = {check.id: check for check in load_checks()}
    return checks["cors-wildcard-origin-with-credentials"], checks["cors-reflects-any-origin-with-credentials"]


def _run(check, fetch):
    return CheckRuntime([check], fetch).run("10.0.0.1", [_SERVICE])


# ============================================================ comodín de origen


def test_a_wildcard_origin_with_credentials_fires():
    wildcard_check, _ = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "", {
            "access-control-allow-origin": "*",
            "access-control-allow-credentials": "true",
        })

    assert [f["check_id"] for f in _run(wildcard_check, fetch)] == [
        "lybra:cors-wildcard-origin-with-credentials@1"]


def test_a_wildcard_origin_without_credentials_does_not_fire():
    """Señuelo del propio issue: comodín sin credenciales es habitual y no dispara."""
    wildcard_check, _ = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "", {"access-control-allow-origin": "*"})

    assert _run(wildcard_check, fetch) == []


def test_credentials_without_a_wildcard_origin_does_not_fire():
    wildcard_check, _ = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "", {
            "access-control-allow-origin": "https://app.example.test",
            "access-control-allow-credentials": "true",
        })

    assert _run(wildcard_check, fetch) == []


# ============================================================ reflejo de cualquier origen


def test_a_site_that_reflects_both_probe_origins_with_credentials_fires():
    """El criterio de cierre: acepta cualquier origen con credenciales."""
    _, reflect_check = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        origin = (headers or {}).get("Origin", "")
        return Response(200, "", {
            "access-control-allow-origin": origin,
            "access-control-allow-credentials": "true",
        })

    assert [f["check_id"] for f in _run(reflect_check, fetch)] == [
        "lybra:cors-reflects-any-origin-with-credentials@1"]


def test_a_site_with_a_concrete_allowlist_does_not_fire():
    """El señuelo: una lista concreta de orígenes permitidos sigue funcionando
    para esos orígenes sin disparar el aviso — ninguno de los dos orígenes de
    sonda está en la lista."""
    _, reflect_check = _feed()

    allowed = {"https://app.example.test", "https://admin.example.test"}

    def fetch(host, port, method, path, body=None, headers=None):
        origin = (headers or {}).get("Origin", "")
        headers_out = {"access-control-allow-credentials": "true"}
        if origin in allowed:
            headers_out["access-control-allow-origin"] = origin
        return Response(200, "", headers_out)

    assert _run(reflect_check, fetch) == []


def test_reflecting_the_origin_without_credentials_does_not_fire():
    _, reflect_check = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        origin = (headers or {}).get("Origin", "")
        return Response(200, "", {"access-control-allow-origin": origin})

    assert _run(reflect_check, fetch) == []


def test_a_fixed_wildcard_answer_does_not_fire_the_reflection_check():
    """Un «*» fijo no es un reflejo: no cambia entre las dos peticiones, así
    que el matcher ``compare`` no lo confunde con un reflejo real. (El
    comodín ya lo cubre el otro check.)"""
    _, reflect_check = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "", {
            "access-control-allow-origin": "*",
            "access-control-allow-credentials": "true",
        })

    assert _run(reflect_check, fetch) == []


def test_only_one_of_the_two_probe_origins_reflected_does_not_fire():
    """Si sólo uno de los dos orígenes de sonda coincide con algo permitido —
    por casualidad—, no basta: hacen falta las dos peticiones disparando."""
    _, reflect_check = _feed()

    def fetch(host, port, method, path, body=None, headers=None):
        origin = (headers or {}).get("Origin", "")
        if origin == _ORIGIN_A:
            return Response(200, "", {
                "access-control-allow-origin": origin,
                "access-control-allow-credentials": "true",
            })
        return Response(200, "", {"access-control-allow-credentials": "true"})

    assert _run(reflect_check, fetch) == []


# ============================================================ el feed


def test_the_shipped_feed_is_still_well_formed():
    assert validate_checks(load_checks()) == []


def test_the_two_cors_checks_are_registered_with_the_expected_category():
    wildcard_check, reflect_check = _feed()

    assert wildcard_check.category == "security_header"
    assert reflect_check.category == "security_header"
    assert reflect_check.type == "http" and len(reflect_check.requests) == 2
