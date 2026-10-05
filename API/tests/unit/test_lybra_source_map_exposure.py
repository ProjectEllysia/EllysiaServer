"""Mapas de código fuente publicados junto al JavaScript de producción.

Una herramienta de empaquetado suele generar, junto al JavaScript minificado
que de verdad sirve al navegador, un mapa de código fuente para depurar en
desarrollo. Si se publica en producción, regala el código fuente completo del
frontend. El propio JavaScript delata el mapa con un comentario
``//# sourceMappingURL=...``; este check lo sigue y comprueba que lo que hay
al otro lado tiene de verdad forma de mapa, no la respuesta genérica de un
sitio que contesta 200 a cualquier ruta.
"""

import pytest

from src.modules.features.themis.lybra.checks import ScriptContext
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.script_checks import (
    SourceMapExposedPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_HTTP = Service(port=80, protocol="tcp", name="http")
_MAP_BODY = '{"version":3,"sources":["app.js"],"names":[],"mappings":"AAAA","file":"app.min.js"}'


class _FakeProbe:
    """Sonda que contesta por ruta lo que se le configure; ``None`` = sin respuesta."""

    def __init__(self, by_path, baseline=None):
        from src.modules.features.themis.lybra.checks import Response
        self._by_path = by_path
        self._baseline = baseline or Response(404, "Not Found", {})
        self.requested = []

    def fetch(self, host, port, method, path, body=None, headers=None):
        self.requested.append(path)
        if path in self._by_path:
            return self._by_path[path]
        if path.startswith("/lybra-baseline-"):
            return self._baseline
        return None


def _response(status, body, headers=None):
    from src.modules.features.themis.lybra.checks import Response
    return Response(status, body, headers or {})


def test_a_published_source_map_fires():
    """El criterio de cierre: el mapa está publicado y es legible."""
    probe = _FakeProbe({
        "/": _response(200, '<script src="/app.min.js"></script>'),
        "/app.min.js": _response(200, 'console.log(1)\n//# sourceMappingURL=app.min.js.map'),
        "/app.min.js.map": _response(200, _MAP_BODY),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is True
    assert context.evidence == {"scriptPath": "/app.min.js", "sourceMapPath": "/app.min.js.map"}


def test_the_same_site_without_the_map_does_not_fire():
    """Señuelo directo del Issue: mismo sitio, mapa no publicado."""
    probe = _FakeProbe({
        "/": _response(200, '<script src="/app.min.js"></script>'),
        "/app.min.js": _response(200, 'console.log(1)\n//# sourceMappingURL=app.min.js.map'),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False


def test_a_script_without_any_reference_does_not_fire():
    """Señuelo: JavaScript minificado sin ninguna referencia a un mapa."""
    probe = _FakeProbe({
        "/": _response(200, '<script src="/app.min.js"></script>'),
        "/app.min.js": _response(200, 'console.log(1)'),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False


def test_a_site_that_answers_everything_with_200_does_not_fire():
    """No se confunde con la respuesta genérica de un sitio que contesta 200 a todo."""
    generic = _response(200, "<html>app shell</html>")
    probe = _FakeProbe({
        "/": _response(200, '<script src="/app.min.js"></script>'),
        "/app.min.js": _response(200, 'console.log(1)\n//# sourceMappingURL=app.min.js.map'),
        "/app.min.js.map": generic,
    }, baseline=generic)
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False


def test_an_external_script_is_never_followed():
    probe = _FakeProbe({
        "/": _response(200, '<script src="https://cdn.terceros.test/lib.js"></script>'),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False
    assert not any("cdn.terceros.test" in path for path in probe.requested)


def test_a_map_that_points_to_another_origin_is_not_followed():
    probe = _FakeProbe({
        "/": _response(200, '<script src="/app.min.js"></script>'),
        "/app.min.js": _response(
            200, 'console.log(1)\n//# sourceMappingURL=https://otro.test/app.js.map'),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False


def test_the_map_path_is_resolved_relative_to_the_script_not_the_root():
    probe = _FakeProbe({
        "/": _response(200, '<script src="/assets/app.min.js"></script>'),
        "/assets/app.min.js": _response(
            200, 'console.log(1)\n//# sourceMappingURL=app.min.js.map'),
        "/assets/app.min.js.map": _response(200, _MAP_BODY),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is True
    assert context.evidence["sourceMapPath"] == "/assets/app.min.js.map"


def test_a_200_that_is_not_shaped_like_a_map_does_not_fire():
    """Un 200 solo no basta: hace falta que el cuerpo tenga forma de mapa real."""
    probe = _FakeProbe({
        "/": _response(200, '<script src="/app.min.js"></script>'),
        "/app.min.js": _response(200, 'console.log(1)\n//# sourceMappingURL=app.min.js.map'),
        "/app.min.js.map": _response(200, "<html>404 not really</html>"),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False


def test_only_the_first_matching_script_is_reported_but_others_are_tried_first():
    probe = _FakeProbe({
        "/": _response(200, '<script src="/a.js"></script><script src="/b.js"></script>'),
        "/a.js": _response(200, 'console.log(1)'),                          # sin referencia
        "/b.js": _response(200, 'console.log(2)\n//# sourceMappingURL=b.js.map'),
        "/b.js.map": _response(200, _MAP_BODY),
    })
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is True
    assert context.evidence["scriptPath"] == "/b.js"


def test_the_root_page_not_answering_does_not_fire():
    probe = _FakeProbe({})
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    assert SourceMapExposedPlugin(probe=probe).run(context) is False


def test_the_number_of_scripts_examined_is_capped():
    scripts_html = "".join(f'<script src="/s{i}.js"></script>' for i in range(20))
    by_path = {"/": _response(200, scripts_html)}
    for i in range(20):
        by_path[f"/s{i}.js"] = _response(200, "console.log(1)")
    probe = _FakeProbe(by_path)
    context = ScriptContext(target="203.0.113.10", service=_HTTP)

    SourceMapExposedPlugin(probe=probe).run(context)

    examined = [path for path in probe.requested if path.startswith("/s")]
    assert len(examined) <= 8


def test_the_plugin_is_registered():
    assert "source-map-exposed" in default_script_plugins()
