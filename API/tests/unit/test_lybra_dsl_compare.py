"""El DSL de checks sabe comparar dos respuestas y reflejar lo que mandó.

Hay comprobaciones que no buscan un texto fijo en una respuesta: repiten una
petición cambiando un solo detalle y quieren saber si el servicio contestó otra
cosa, o si la respuesta devuelve lo mismo que se le mandó (el caso de una web
que refleja el origen que se le declara). Aquí se prueban las dos piezas que lo
permiten sin un plugin ``script`` por check: el matcher ``compare`` y los
marcadores ``{{nombre}}`` en los valores de un matcher.
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


def _run(check, fetch):
    return CheckRuntime([check], fetch).run("10.0.0.1", [_SERVICE])


def _check(requests, payloads=()):
    return Check(id="probe", version=1, type="http", category="web_finding", severity="MEDIUM",
                 service="http", mode="safe", finding={"title": "x"},
                 requests=tuple(requests), payloads=payloads)


def _two_requests(relation, second_header="X-Variant"):
    """Dos peticiones a la misma ruta; la segunda cambia una cabecera y compara."""
    return _check((
        Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),
        Request(path="/", headers=((second_header, "1"),),
                matchers=(Matcher(type="compare", part="body", against=0, relation=relation),)),
    ))


def _fetch_varying_with_header(host, port, method, path, body=None, headers=None):
    return Response(200, "variante" if headers else "base", {})


def _fetch_ignoring_header(host, port, method, path, body=None, headers=None):
    return Response(200, "igual", {})


def test_compare_differs_fires_when_the_changed_request_changes_the_answer():
    assert [f["check_id"] for f in _run(_two_requests("differs"), _fetch_varying_with_header)] == [
        "lybra:probe@1"]


def test_compare_differs_does_not_fire_when_the_answer_is_the_same():
    """Señuelo: un servicio que ignora la cabecera contesta lo mismo."""
    assert _run(_two_requests("differs"), _fetch_ignoring_header) == []


def test_compare_same_fires_when_both_answers_are_identical():
    assert [f["check_id"] for f in _run(_two_requests("same"), _fetch_ignoring_header)] == [
        "lybra:probe@1"]


def test_compare_can_look_at_a_single_part_of_the_response():
    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "mismo cuerpo", {"x-token": "b" if headers else "a"})

    check = _check((
        Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),
        Request(path="/", headers=(("X-Variant", "1"),),
                matchers=(Matcher(type="compare", part="header", against=0, relation="differs"),)),
    ))

    assert [f["check_id"] for f in _run(check, fetch)] == ["lybra:probe@1"]


def test_compare_without_a_previous_response_never_fires():
    check = _check((Request(path="/", matchers=(
        Matcher(type="compare", part="body", against=0, relation="differs"),)),))

    assert _run(check, _fetch_varying_with_header) == []


def test_a_negative_compare_inverts_the_result():
    check = _check((
        Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),
        Request(path="/", headers=(("X-Variant", "1"),), matchers=(
            Matcher(type="compare", part="body", against=0, relation="differs", negative=True),)),
    ))

    assert [f["check_id"] for f in _run(check, _fetch_ignoring_header)] == ["lybra:probe@1"]


def test_a_matcher_value_can_reflect_what_the_request_sent():
    """El caso de una web que devuelve el origen que se le declara."""
    def fetch(host, port, method, path, body=None, headers=None):
        origin = (headers or {}).get("Origin", "")
        return Response(200, "", {"access-control-allow-origin": origin})

    check = _check(
        (Request(path="/", headers=(("Origin", "{{origin}}"),),
                 matchers=(Matcher(type="word", part="header",
                                   values=("access-control-allow-origin: {{origin}}",)),)),),
        payloads=(("origin", ("https://lybra-probe.invalid",)),),
    )

    assert [f["check_id"] for f in _run(check, fetch)] == ["lybra:probe@1"]


def test_a_service_that_does_not_reflect_the_value_does_not_fire():
    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "", {"access-control-allow-origin": "https://app.example"})

    check = _check(
        (Request(path="/", headers=(("Origin", "{{origin}}"),),
                 matchers=(Matcher(type="word", part="header",
                                   values=("access-control-allow-origin: {{origin}}",)),)),),
        payloads=(("origin", ("https://lybra-probe.invalid",)),),
    )

    assert _run(check, fetch) == []


def test_a_variable_in_a_regex_matcher_is_matched_as_literal_text():
    """El punto de un nombre de dominio no es «cualquier carácter»."""
    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "origin=https://lybra-probeXinvalid", {})

    check = _check(
        (Request(path="/", matchers=(Matcher(type="regex", values=("origin={{origin}}",)),)),),
        payloads=(("origin", ("https://lybra-probe.invalid",)),),
    )

    assert _run(check, fetch) == []


def test_an_unbound_marker_in_a_matcher_stays_verbatim():
    def fetch(host, port, method, path, body=None, headers=None):
        return Response(200, "texto con {{sin_ligar}}", {})

    check = _check((Request(path="/", matchers=(
        Matcher(type="word", values=("{{sin_ligar}}",)),)),))

    assert [f["check_id"] for f in _run(check, fetch)] == ["lybra:probe@1"]


def test_existing_matchers_behave_as_before_without_variables():
    """Señuelo: sin marcadores ni comparaciones, nada cambia."""
    check = _check((Request(path="/", matchers=(
        Matcher(type="status", values=(200,)), Matcher(type="word", values=("base",)))),))

    assert _run(check, _fetch_ignoring_header) == []
    assert [f["check_id"] for f in _run(check, _fetch_varying_with_header)] == ["lybra:probe@1"]


# ===================================================== validación de forma


def test_the_shipped_feed_is_still_well_formed():
    assert validate_checks(load_checks()) == []


def test_a_compare_without_against_is_reported():
    check = _check((Request(path="/", matchers=(Matcher(type="compare"),)),))

    assert any("'against'" in problem for problem in validate_checks([check]))


def test_a_compare_against_a_request_that_is_not_earlier_is_reported():
    check = _check((
        Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),
        Request(path="/", matchers=(Matcher(type="compare", against=1),)),
    ))

    assert any("no es anterior" in problem for problem in validate_checks([check]))


def test_a_compare_with_an_unknown_relation_is_reported():
    check = _check((
        Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),
        Request(path="/", matchers=(Matcher(type="compare", against=0, relation="igual"),)),
    ))

    assert any("relación" in problem for problem in validate_checks([check]))


def test_the_yaml_feed_parses_a_compare_matcher(tmp_path):
    feed = tmp_path / "feed.yaml"
    feed.write_text(
        "checks:\n"
        "  - id: cmp\n"
        "    type: http\n"
        "    category: web_finding\n"
        "    severity: LOW\n"
        "    requests:\n"
        "      - path: /\n"
        "        matchers:\n"
        "          - type: status\n"
        "            value: [200]\n"
        "      - path: /\n"
        "        matchers:\n"
        "          - type: compare\n"
        "            part: body\n"
        "            against: 0\n"
        "            relation: same\n",
        encoding="utf-8")

    (loaded,) = load_checks(str(feed))

    assert validate_checks([loaded]) == []
    assert loaded.requests[1].matchers[0].against == 0
    assert loaded.requests[1].matchers[0].relation == "same"
