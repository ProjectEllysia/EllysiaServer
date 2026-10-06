"""La respuesta de referencia: un servicio que contesta «200» a todo no da exposiciones.

Una aplicación de una sola página devuelve el mismo documento a cualquier ruta,
exista o no. Un check de exposición que se fíe del «200» o de un patrón que ese
documento sí trae daría un hallazgo por cada ruta que se le pida. El runtime
pide, sólo cuando una ruta ya iba a disparar, una ruta inventada y descarta la
coincidencia si el servicio contesta a las dos lo mismo.
"""

import pytest

from src.modules.features.themis.lybra.checks import (
    Baseline,
    Check,
    CheckRuntime,
    Matcher,
    Request,
    Response,
    Service,
    baseline_path,
    load_checks,
)

pytestmark = pytest.mark.unit

_SERVICE = Service(80, "tcp", "http", None, None, None)
_BASELINE_PREFIX = "/lybra-baseline-"
_SPA_PAGE = "<html><body><div id='app'></div><script src='/assets/app.js'></script></body></html>"


def _status_check(path="/backup.sql", guards_baseline=True):
    """Un check de ruta que sólo mira el «200»: el más expuesto al «200 a todo»."""
    return Check(
        id="backup", version=1, type="http", category="exposed_path", severity="HIGH",
        service="http", mode="safe", finding={"title": "x"}, guards_baseline=guards_baseline,
        requests=(Request(path=path, matchers=(Matcher(type="status", values=(200,)),)),),
    )


def _run(check, fetch):
    return CheckRuntime([check], fetch).run("10.0.0.1", [_SERVICE])


def test_a_service_answering_the_same_page_to_everything_fires_nothing():
    calls = []

    def fetch(host, port, method, path):
        calls.append(path)
        return Response(200, _SPA_PAGE, {})

    assert _run(_status_check(), fetch) == []
    assert any(path.startswith(_BASELINE_PREFIX) for path in calls)


def test_the_same_service_with_a_real_file_still_fires():
    def fetch(host, port, method, path):
        if path == "/backup.sql":
            return Response(200, "CREATE TABLE users (id int);", {})
        return Response(200, _SPA_PAGE, {})

    assert [f["check_id"] for f in _run(_status_check(), fetch)] == ["lybra:backup@1"]


def test_a_traditional_server_with_a_real_404_is_unchanged():
    """Señuelo: con un 404 real, la referencia no descarta nada."""
    def fetch(host, port, method, path):
        if path == "/backup.sql":
            return Response(200, "CREATE TABLE users (id int);", {})
        return Response(404, "Not Found", {})

    assert [f["check_id"] for f in _run(_status_check(), fetch)] == ["lybra:backup@1"]


def test_the_baseline_is_only_requested_when_a_path_was_about_to_fire():
    calls = []

    def fetch(host, port, method, path):
        calls.append(path)
        return Response(404, "", {})

    assert _run(_status_check(), fetch) == []
    assert calls == ["/backup.sql"]


def test_the_baseline_is_requested_once_for_all_the_checks_of_a_service():
    calls = []

    def fetch(host, port, method, path):
        calls.append(path)
        return Response(200, _SPA_PAGE, {})

    first, second = _status_check("/a.sql"), _status_check("/b.sql")
    second = Check(**{**first.__dict__, "id": "other", "requests": second.requests})
    CheckRuntime([first, second], fetch).run("10.0.0.1", [_SERVICE])

    assert len([path for path in calls if path.startswith(_BASELINE_PREFIX)]) == 1


def test_a_check_that_looks_for_the_error_page_can_opt_out():
    def fetch(host, port, method, path):
        return Response(404, "Whitelabel Error Page", {})

    check = Check(
        id="error-page", version=1, type="http", category="web_finding", severity="LOW",
        service="http", mode="safe", finding={"title": "x"}, guards_baseline=False,
        requests=(Request(path="/lybra-nonexistent-debug-probe",
                          matchers=(Matcher(type="word", values=("Whitelabel Error Page",)),)),),
    )
    assert [f["check_id"] for f in _run(check, fetch)] == ["lybra:error-page@1"]


def test_the_error_page_checks_of_the_feed_opt_out():
    by_id = {check.id: check for check in load_checks()}
    for check_id in ("django-debug-enabled", "flask-werkzeug-debugger",
                     "default-error-page", "stack-trace-disclosure"):
        assert by_id[check_id].guards_baseline is False


def test_every_other_check_of_the_feed_keeps_the_guard():
    opted_out = {check.id for check in load_checks() if not check.guards_baseline}
    assert opted_out == {"django-debug-enabled", "flask-werkzeug-debugger",
                         "default-error-page", "stack-trace-disclosure"}


def test_a_missing_baseline_discards_nothing():
    """Si el servicio no contesta a la ruta inventada, se comporta como antes."""
    def fetch(host, port, method, path):
        return None if path.startswith(_BASELINE_PREFIX) else Response(200, _SPA_PAGE, {})

    assert [f["check_id"] for f in _run(_status_check(), fetch)] == ["lybra:backup@1"]


def test_the_root_path_is_never_compared_with_the_baseline():
    def fetch(host, port, method, path):
        return Response(200, _SPA_PAGE, {})

    assert [f["check_id"] for f in _run(_status_check("/"), fetch)] == ["lybra:backup@1"]


def test_a_not_found_page_that_echoes_the_path_still_resembles_the_baseline():
    reference = Baseline.from_response(
        "/lybra-baseline-0123456789abcdef",
        Response(200, "Cannot GET /lybra-baseline-0123456789abcdef", {}))

    assert reference.resembles(Response(200, "Cannot GET /backup.sql", {}), "/backup.sql")


def test_a_page_with_a_changing_token_still_resembles_the_baseline():
    reference = Baseline.from_response(
        "/lybra-baseline-0123456789abcdef",
        Response(200, "<meta name='csrf' content='aaaaaaaaaaaaaaaaaaaaaaaa'>", {}))

    assert reference.resembles(
        Response(200, "<meta name='csrf' content='bbbbbbbbbbbbbbbbbbbbbbbb'>", {}), "/x.sql")


def test_a_different_status_or_body_does_not_resemble_the_baseline():
    reference = Baseline.from_response("/lybra-baseline-0123456789abcdef", Response(200, "a", {}))

    assert not reference.resembles(Response(404, "a", {}), "/x")
    assert not reference.resembles(Response(200, "b", {}), "/x")


def test_the_baseline_path_is_random_and_cannot_be_a_real_route():
    first, second = baseline_path(), baseline_path()

    assert first != second
    assert first.startswith(_BASELINE_PREFIX)
