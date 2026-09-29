"""Exposición de APIs: los checks de GraphQL y de especificaciones del feed."""

import json

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.themis.lybra import Service, derive_api_checks, parse_specification
from src.modules.features.themis.managers.lybra.api_surface import run_api_surface
from src.modules.features.themis.lybra.checks import CheckRuntime, Response, load_checks

pytestmark = pytest.mark.unit

_HTTP = Service(80, "tcp", "http", "nginx", "1.18", None)
_INTROSPECTION_ENABLED = '{"data":{"__schema":{"queryType":{"name":"Query"},"types":[{"name":"User"}]}}}'
_INTROSPECTION_DISABLED = '{"errors":[{"message":"GraphQL introspection is not allowed, but the query contained __schema"}]}'


def _graphql_server(introspection_body: str, suggestion_body: str = '{"errors":[]}', path: str = "/graphql"):
    """Un fetch falso que sólo contesta a POST en ``path`` según la consulta recibida."""
    def fetch(_host, _port, method, request_path, body=None, headers=None):
        if method != "POST" or request_path != path:
            return Response(404, "", {})
        assert (headers or {}).get("Content-Type") == "application/json"
        if "__schema" in (body or ""):
            return Response(200, introspection_body, {})
        return Response(200, suggestion_body, {})
    return fetch


def _fired_ids(fetch) -> set:
    findings = CheckRuntime(load_checks(), fetch).run("10.0.0.5", [_HTTP])
    return {finding["check_id"] for finding in findings}


def test_open_graphql_introspection_is_reported():
    assert "lybra:graphql-introspection-enabled@1" in _fired_ids(_graphql_server(_INTROSPECTION_ENABLED))


def test_disabled_introspection_is_not_reported():
    # Un servidor con la introspección apagada nombra `__schema` en su error:
    # el check exige el esquema devuelto, no la palabra.
    assert "lybra:graphql-introspection-enabled@1" not in _fired_ids(_graphql_server(_INTROSPECTION_DISABLED))


def test_graphql_is_found_at_a_non_default_path():
    fetch = _graphql_server(_INTROSPECTION_ENABLED, path="/api/graphql")
    assert "lybra:graphql-introspection-enabled@1" in _fired_ids(fetch)


def test_field_suggestion_is_reported_only_when_the_server_suggests():
    suggesting = _graphql_server(_INTROSPECTION_DISABLED,
                                 '{"errors":[{"message":"Cannot query field \\"__typenam\\". Did you mean \\"__typename\\"?"}]}')
    assert "lybra:graphql-field-suggestion@1" in _fired_ids(suggesting)
    assert "lybra:graphql-field-suggestion@1" not in _fired_ids(_graphql_server(_INTROSPECTION_DISABLED))


def test_a_site_without_graphql_reports_nothing_of_it():
    fetch = lambda *_args, **_kwargs: Response(404, "", {})  # noqa: E731
    assert not {i for i in _fired_ids(fetch) if "graphql" in i}


def test_versioned_api_docs_are_reported():
    def fetch(_host, _port, _method, path, _body=None, _headers=None):
        if path == "/v3/api-docs":
            return Response(200, '{"openapi":"3.0.1","paths":{}}', {})
        return Response(404, "", {})
    assert "lybra:api-docs-versioned-exposure@1" in _fired_ids(fetch)


# ============================================ la especificación y sus checks derivados

def _openapi(paths: dict, **extra) -> str:
    return json.dumps({"openapi": "3.0.1", "info": {"title": "Demo"}, "paths": paths, **extra})


_SECURED = [{"bearerAuth": []}]


def test_a_specification_is_parsed_with_what_it_declares_protected():
    spec = parse_specification(_openapi(
        {
            "/users": {"get": {"security": _SECURED}},
            "/health": {"get": {"security": []}},
            "/optional": {"get": {"security": [{}]}},
            "/inherited": {"get": {}},
        },
        security=_SECURED,
        servers=[{"url": "https://api.example.com/v1/"}],
    ))

    protected = {endpoint.path: endpoint.requires_authentication for endpoint in spec.endpoints}
    assert spec.title == "Demo"
    # La base del servidor se antepone; `security: []` y `[{}]` no son protección.
    assert protected == {
        "/v1/users": True, "/v1/health": False, "/v1/optional": False, "/v1/inherited": True}


def test_a_swagger_two_document_uses_its_base_path():
    spec = parse_specification(json.dumps({
        "swagger": "2.0", "basePath": "/api", "paths": {"/me": {"get": {"security": _SECURED}}}}))
    assert [endpoint.path for endpoint in spec.endpoints] == ["/api/me"]


@pytest.mark.parametrize("text", [
    "no es json", "[]", "{}", '{"paths": {}}', json.dumps({"openapi": "3.0.0"}),
    json.dumps({"openapi": "3.0.0", "paths": {}}),
])
def test_what_is_not_a_specification_yields_nothing(text):
    assert parse_specification(text) is None


def test_a_server_url_with_variables_leaves_the_paths_without_base():
    spec = parse_specification(_openapi(
        {"/users": {"get": {"security": _SECURED}}}, servers=[{"url": "https://{region}.example.com/v1"}]))
    assert spec.endpoints[0].path == "/users"


def test_only_protected_reads_without_path_parameters_are_derived():
    spec = parse_specification(_openapi({
        "/users": {"get": {"security": _SECURED}},
        "/users/{id}": {"get": {"security": _SECURED}},
        "/public": {"get": {"security": []}},
        "/orders": {"post": {"security": _SECURED}},
    }))

    checks = derive_api_checks(spec, max_endpoints=10)

    assert [check.requests[0].path for check in checks] == ["/users"]
    assert checks[0].mode == "safe" and checks[0].category == "api_exposure"


def test_the_cap_bounds_the_derived_checks_however_large_the_specification():
    paths = {f"/resource{n}": {"get": {"security": _SECURED}} for n in range(500)}
    spec = parse_specification(_openapi(paths))

    assert len(derive_api_checks(spec, max_endpoints=25)) == 25
    assert derive_api_checks(spec, max_endpoints=0) == []


def test_derived_check_ids_are_distinct_per_endpoint():
    # Dos rutas que sólo difieren en caracteres no alfanuméricos no se funden.
    spec = parse_specification(_openapi({
        "/a-b": {"get": {"security": _SECURED}}, "/a_b": {"get": {"security": _SECURED}}}))
    ids = [check.id for check in derive_api_checks(spec, 10)]
    assert len(ids) == len(set(ids)) == 2


def _run_derived(paths: dict, responses: dict, mode: str = "safe"):
    """Ejecuta el análisis contra un servidor falso: publica `paths` y contesta a `responses`."""
    requested = []

    def fetch(_host, _port, method, path, body=None, headers=None):
        requested.append((method, path))
        if path == "/openapi.json":
            return Response(200, _openapi(paths), {})
        return responses.get((method, path), Response(404, "", {}))

    findings = run_api_surface("10.0.0.5", [_HTTP], mode=mode, fetch=fetch)
    return findings, requested


_OPEN = {"/users": {"get": {"security": _SECURED}}}


def test_a_protected_endpoint_answering_json_without_credentials_is_reported():
    findings, _ = _run_derived(_OPEN, {("GET", "/users"): Response(200, "[]", {"content-type": "application/json"})})

    assert [finding["category"] for finding in findings] == ["api_exposure"]
    assert findings[0]["severity"] == "HIGH" and "GET /users" in findings[0]["title"]


def test_a_protected_endpoint_that_refuses_is_not_reported():
    findings, _ = _run_derived(_OPEN, {("GET", "/users"): Response(401, "{}", {"content-type": "application/json"})})
    assert findings == []


def test_a_catch_all_page_is_not_an_open_api():
    # Una aplicación de una sola página devuelve su HTML con 200 para cualquier ruta.
    findings, _ = _run_derived(_OPEN, {("GET", "/users"): Response(200, "<html></html>", {"content-type": "text/html"})})
    assert findings == []


def test_a_service_without_a_specification_costs_only_the_discovery_requests():
    requested = []
    findings = run_api_surface(
        "10.0.0.5", [_HTTP],
        fetch=lambda _h, _p, method, path, *_: requested.append((method, path)) or Response(404, "", {}))
    assert findings == []
    assert sorted(path for _m, path in requested) == sorted(
        ["/openapi.json", "/swagger.json", "/v2/api-docs", "/v3/api-docs"])


def test_the_analysis_is_off_when_the_cap_is_zero(monkeypatch):
    monkeypatch.setattr(CR, "lybra_api_surface_config", lambda: CR.LybraApiSurfaceConfig(max_endpoints=0))
    _, requested = _run_derived(_OPEN, {})
    assert requested == []


# ------------------------------------------------------------ asignación masiva

_WRITABLE = {"/profile": {"put": {"security": _SECURED}}}


def _stateful_server(persists_unknown_properties: bool):
    """Un servidor con un recurso `/profile` que guarda (o no) lo que se le manda."""
    stored = {}
    requested = []

    def fetch(_host, _port, method, path, body=None, headers=None):
        requested.append(method)
        if path == "/openapi.json":
            return Response(200, _openapi(_WRITABLE), {})
        if path == "/profile" and method == "PUT":
            if persists_unknown_properties:
                stored.update(json.loads(body))
            return Response(200, "{}", {})
        if path == "/profile" and method == "GET":
            return Response(200, json.dumps(stored), {"content-type": "application/json"})
        return Response(404, "", {})

    return fetch, requested


def test_mass_assignment_is_reported_when_the_server_stores_an_undeclared_property():
    fetch, _ = _stateful_server(persists_unknown_properties=True)
    findings = run_api_surface("10.0.0.5", [_HTTP], mode="aggressive", fetch=fetch)
    assert [finding["severity"] for finding in findings] == ["MEDIUM"]
    assert "asignación masiva" in findings[0]["title"]


def test_mass_assignment_is_not_reported_when_the_server_ignores_the_property():
    fetch, _ = _stateful_server(persists_unknown_properties=False)
    assert run_api_surface("10.0.0.5", [_HTTP], mode="aggressive", fetch=fetch) == []


def test_mass_assignment_never_writes_in_safe_mode():
    fetch, requested = _stateful_server(persists_unknown_properties=True)
    assert run_api_surface("10.0.0.5", [_HTTP], mode="safe", fetch=fetch) == []
    assert "PUT" not in requested
