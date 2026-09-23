"""El rastreo de sólo lectura: presupuesto, mismo origen, sólo GET.

Lybra sólo pedía las rutas que sus checks declaran; nunca miraba qué hay en el
sitio. El rastreo cierra ese hueco sin riesgo para el objetivo: sólo lectura,
del mismo origen y con tres topes duros (páginas, profundidad, tiempo).
"""

import pytest

from src.modules.features.themis.lybra.checks import Response
from src.modules.features.themis.lybra.crawler import crawl

pytestmark = pytest.mark.unit

HOST, PORT = "203.0.113.10", 80


def _server(pages):
    """Un ``fetch`` falso que sirve ``pages`` y registra cada petición.

    Cada valor es un ``Response`` o una tupla ``(status, body, headers)``.
    """
    calls = []

    def fetch(host, port, method, path, body=None, headers=None):
        calls.append((method, path))
        page = pages.get(path)
        if page is None:
            return Response(404, "", {})
        if isinstance(page, Response):
            return page
        status, page_body, page_headers = page
        return Response(status, page_body, page_headers)
    return fetch, calls


def test_only_get_is_used_and_the_crawl_stays_on_the_same_origin():
    fetch, calls = _server({
        "/": (200, '<a href="/interna">i</a> <a href="https://otra.test/x">fuera</a>'
                   ' <a href="mailto:x@y.test">m</a>', {}),
        "/interna": (200, "ok", {}),
    })

    crawl(HOST, PORT, fetch, max_pages=50)

    assert all(method == "GET" for method, _ in calls)
    visited = {path for _, path in calls}
    assert "/interna" in visited            # enlace relativo, seguido
    assert "/x" not in visited              # otro origen, descartado
    assert not any("otra.test" in path for _, path in calls)


def test_the_page_budget_is_a_hard_cap():
    # Una tela de araña: cada página enlaza a la siguiente, sin fin.
    pages = {f"/p{i}": (200, f'<a href="/p{i + 1}">next</a>', {}) for i in range(100)}
    pages["/"] = (200, '<a href="/p0">start</a>', {})
    fetch, calls = _server(pages)

    result = crawl(HOST, PORT, fetch, max_pages=10, max_depth=100)

    assert result.pages_fetched == 10
    # /robots.txt no cuenta como página: es la sonda previa.
    assert len([1 for method, path in calls if path != "/robots.txt"]) == 10


def test_the_depth_budget_stops_following_deeper_links():
    fetch, _calls = _server({
        "/": (200, '<a href="/a">a</a>', {}),
        "/a": (200, '<a href="/b">b</a>', {}),
        "/b": (200, '<a href="/c">c</a>', {}),
        "/c": (200, "hoja", {}),
    })

    result = crawl(HOST, PORT, fetch, max_pages=50, max_depth=1)

    # Raíz (0) y /a (1) sí; /b (2) queda fuera del tope de profundidad.
    assert result.pages_fetched == 2


def test_the_time_budget_stops_the_crawl():
    clock = {"t": 0.0}

    def now():
        clock["t"] += 1.0
        return clock["t"]

    pages = {f"/p{i}": (200, f'<a href="/p{i + 1}">n</a>', {}) for i in range(100)}
    pages["/"] = (200, '<a href="/p0">s</a>', {})
    fetch, _calls = _server(pages)

    result = crawl(HOST, PORT, fetch, max_pages=100, time_budget_seconds=5.0, now=now)

    assert result.pages_fetched < 100          # el reloj lo cortó antes


def test_robots_entries_are_read_and_visited_within_budget():
    fetch, calls = _server({
        "/robots.txt": (200, "User-agent: *\nDisallow: /admin/\nAllow: /admin/public\n"
                             "Disallow: /logs/\n", {}),
        "/": (200, "raiz", {}),
        "/admin/": (200, "panel", {}),
    })

    result = crawl(HOST, PORT, fetch, max_pages=50)

    assert result.robots_entries == ["/admin/", "/admin/public", "/logs/"]
    assert ("GET", "/admin/") in calls          # la entrada se visita


def test_a_login_form_and_a_basic_auth_path_are_reported():
    fetch, _calls = _server({
        "/": (200, '<a href="/login">e</a> <a href="/panel">p</a>', {}),
        "/login": (200, '<form><input type="password" name="pw"></form>', {}),
        "/panel": (401, "", {"www-authenticate": 'Basic realm="x"'}),
    })

    result = crawl(HOST, PORT, fetch, max_pages=50)

    assert result.login_paths == ["/login"]
    assert result.basic_auth_paths == ["/panel"]


def test_a_zero_page_budget_does_no_fetch_at_all():
    fetch, calls = _server({"/": (200, "x", {})})

    result = crawl(HOST, PORT, fetch, max_pages=0)

    assert result.pages_fetched == 0
    assert calls == []
