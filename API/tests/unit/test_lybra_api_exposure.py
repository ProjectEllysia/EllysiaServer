"""Exposición de APIs: los checks de GraphQL y de especificaciones del feed."""

import pytest

from src.modules.features.themis.lybra import Service
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
