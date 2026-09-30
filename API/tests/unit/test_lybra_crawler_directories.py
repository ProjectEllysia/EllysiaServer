"""Los directorios que el rastreo descubre alimentan a los checks de ruta.

El rastreador ya sabía qué directorios tiene un sitio, pero esa lista no llegaba
a ningún sitio: las comprobaciones de exposición de ficheros pedían siempre las
mismas rutas fijas del feed. Un sitio real casi nunca deja sus copias de
seguridad exactamente en la raíz. Aquí se prueba que un check que lo declara
(``onDiscoveredDirectories``) se repite sobre los directorios descubiertos,
dentro de un tope, sin cambiar nada para los que no lo declaran.
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
from src.modules.features.themis.lybra.crawler import crawl, select_scan_directories

pytestmark = pytest.mark.unit

_SERVICE = Service(80, "tcp", "http", None, None, None)
_ENV_FILE = "APP_KEY=base64:abcdef\nDB_PASSWORD=secreto\n"


def _env_check(runs_on_discovered_directories=True):
    """Un check de exposición de ``.env`` como el del feed, con el flag elegido."""
    return Check(
        id="dotenv", version=1, type="http", category="exposed_path", severity="HIGH",
        service="http", mode="safe", finding={"title": "Fichero .env expuesto"},
        runs_on_discovered_directories=runs_on_discovered_directories,
        requests=(Request(path="/.env", matchers=(
            Matcher(type="status", values=(200,)),
            Matcher(type="regex", values=(r"(?m)^[A-Z][A-Z0-9_]*=",)),
        )),),
    )


def _site(files):
    """Un servidor que sirve ``files`` (ruta → cuerpo), con 404 real para lo demás."""
    calls = []

    def fetch(host, port, method, path, body=None, headers=None):
        calls.append(path)
        if path in files:
            return Response(200, files[path], {})
        return Response(404, "Not Found", {})
    return fetch, calls


def _run(check, fetch, directories=None):
    return CheckRuntime([check], fetch).run("10.0.0.1", [_SERVICE], discovered_directories=directories)


# ============================================================ elegir los directorios


def test_the_root_is_never_selected():
    assert select_scan_directories(["/", "/app/"], 10) == ["/app/"]


def test_directories_are_ordered_from_the_root_down_and_then_alphabetically():
    chosen = select_scan_directories(["/a/b/c/", "/z/", "/a/", "/a/b/"], 10)

    assert chosen == ["/a/", "/z/", "/a/b/", "/a/b/c/"]


def test_the_limit_is_a_hard_cap():
    assert select_scan_directories(["/a/", "/b/", "/c/"], 2) == ["/a/", "/b/"]
    assert select_scan_directories(["/a/"], 0) == []


def test_repeated_directories_count_once():
    assert select_scan_directories(["/a/", "/a/"], 10) == ["/a/"]


# ============================================================ el runtime


def test_a_sensitive_file_in_a_discovered_directory_is_found():
    """El criterio de cierre: el fichero cuelga de un directorio que sólo se
    descubrió rastreando, y el check ya existente lo ve sin declarar la ruta."""
    fetch, _ = _site({"/app/.env": _ENV_FILE})

    findings = _run(_env_check(), fetch, {80: ["/app/"]})

    assert [f["check_id"] for f in findings] == ["lybra:dotenv@1"]
    assert findings[0]["title"] == "Fichero .env expuesto (en /app/)"


def test_the_same_site_without_discovered_directories_finds_nothing():
    fetch, _ = _site({"/app/.env": _ENV_FILE})

    assert _run(_env_check(), fetch) == []


def test_a_check_that_does_not_ask_for_directories_only_looks_at_the_root():
    fetch, calls = _site({"/app/.env": _ENV_FILE})

    assert _run(_env_check(runs_on_discovered_directories=False), fetch, {80: ["/app/"]}) == []
    assert calls == ["/.env"]


def test_a_real_directory_with_nothing_sensitive_gives_no_finding():
    """Señuelo: descubrir un directorio no es un hallazgo por sí solo."""
    fetch, calls = _site({"/app/index.html": "<html></html>"})

    assert _run(_env_check(), fetch, {80: ["/app/"]}) == []
    assert "/app/.env" in calls


def test_a_root_hit_is_reported_at_the_root_and_the_directories_are_not_asked():
    fetch, calls = _site({"/.env": _ENV_FILE, "/app/.env": _ENV_FILE})

    findings = _run(_env_check(), fetch, {80: ["/app/"]})

    assert [f["title"] for f in findings] == ["Fichero .env expuesto"]
    assert "/app/.env" not in calls


def test_directories_of_another_port_do_not_apply():
    fetch, calls = _site({"/app/.env": _ENV_FILE})

    assert _run(_env_check(), fetch, {8080: ["/app/"]}) == []
    assert calls == ["/.env"]


def test_a_directory_that_answers_the_same_to_everything_is_not_a_finding():
    """Una aplicación de una sola página montada en ``/app/``: el raíz da 404 real,
    pero todo lo que cuelga de ``/app/`` devuelve la misma página. La referencia
    se pide **en ese directorio**, no en la raíz."""
    page = "APP_SHELL=1\nMODE=spa\n"

    def fetch(host, port, method, path, body=None, headers=None):
        if path.startswith("/app/"):
            return Response(200, page, {})
        return Response(404, "Not Found", {})

    assert _run(_env_check(), fetch, {80: ["/app/"]}) == []


def test_each_directory_is_tried_until_one_fires_and_no_further():
    fetch, calls = _site({"/b/.env": _ENV_FILE})

    findings = _run(_env_check(), fetch, {80: ["/a/", "/b/", "/c/"]})

    assert findings[0]["title"].endswith("(en /b/)")
    assert "/c/.env" not in calls


def test_the_directory_is_prefixed_only_to_get_paths_that_start_with_a_slash():
    check = Check(
        id="odd", version=1, type="http", category="exposed_path", severity="LOW",
        service="http", mode="safe", finding={"title": "x"},
        runs_on_discovered_directories=True,
        requests=(Request(path="/{{name}}", matchers=(Matcher(type="status", values=(200,)),)),),
        payloads=(("name", ("secret.txt",)),),
    )
    fetch, _ = _site({"/app/secret.txt": "x"})

    assert [f["check_id"] for f in _run(check, fetch, {80: ["/app/"]})] == ["lybra:odd@1"]


# ============================================================ el feed


def test_the_file_exposure_checks_that_opt_in_include_the_two_named_ones():
    """El conjunto exacto lo amplía #1069 (listado de directorios y copias de
    backup); esto sólo ata que los dos originales sigan dentro."""
    opted_in = {check.id for check in load_checks() if check.runs_on_discovered_directories}

    assert {"git-config-exposure", "dotenv-exposure"} <= opted_in


def test_the_shipped_feed_is_still_well_formed():
    assert validate_checks(load_checks()) == []


def test_a_root_path_is_a_valid_target_for_discovered_directories():
    """Relajado en #1069: el listado de directorios necesita repetir su
    propia ruta raíz sobre cada directorio descubierto (``/admin/`` en vez de
    ``/``), así que la raíz ya no está prohibida."""
    check = Check(
        id="root", version=1, type="http", category="security_header", severity="LOW",
        service="http", mode="safe", finding={}, runs_on_discovered_directories=True,
        requests=(Request(path="/", matchers=(Matcher(type="status", values=(200,)),)),),
    )

    assert validate_checks([check]) == []


def test_asking_for_directories_on_a_non_get_request_is_reported():
    check = Check(
        id="post", version=1, type="http", category="exposed_path", severity="LOW",
        service="http", mode="safe", finding={}, runs_on_discovered_directories=True,
        requests=(Request(method="POST", path="/login",
                          matchers=(Matcher(type="status", values=(200,)),)),),
    )

    assert any("onDiscoveredDirectories" in problem for problem in validate_checks([check]))


# ============================================================ del rastreo al runtime


def test_what_the_crawler_discovers_reaches_the_check_end_to_end():
    """Un directorio que sólo aparece enlazado desde una página interior."""
    files = {
        "/": '<a href="/docs/">docs</a>',
        "/docs/": '<a href="/docs/internal/panel">panel</a>',
        "/docs/internal/panel": "<html>panel</html>",
        "/docs/internal/.env": _ENV_FILE,
    }
    fetch, _ = _site(files)

    result = crawl("10.0.0.1", 80, fetch, max_pages=20, max_depth=5)
    directories = select_scan_directories(result.directories, 10)
    findings = _run(_env_check(), fetch, {80: directories})

    assert "/docs/internal/" in directories
    assert [f["title"] for f in findings] == ["Fichero .env expuesto (en /docs/internal/)"]


# ============================================================ el manager y la config


def test_the_crawler_config_carries_the_directory_cap_with_its_default():
    from src.modules.system import config_reading as CR

    assert CR.LybraCrawlerConfig().max_scan_directories == 10


def test_the_manager_hands_the_selected_directories_to_the_check_runtime(monkeypatch):
    from src.modules.features.themis.managers.lybra import engine as engine_module
    from src.modules.features.themis.lybra.crawler import CrawlResult

    monkeypatch.setattr(
        engine_module, "crawl",
        lambda *args, **kwargs: CrawlResult(directories=["/", "/a/", "/b/", "/c/"]))
    monkeypatch.setattr(engine_module.CR, "lybra_crawler_config", lambda: type("_Cfg", (), {
        "max_pages": 5, "max_depth": 2, "time_budget_seconds": 5.0,
        "max_scan_directories": 2})())
    monkeypatch.setattr(engine_module.CR, "lybra_engine_config", lambda: type("_Cfg", (), {
        "http_timeout": 1.0, "http_max_body_bytes": 1000, "http_user_agent": "t"})())

    findings, auth_paths, directories, login_paths = engine_module.LybraEngineManager()._run_crawler(  # pylint: disable=protected-access
        "10.0.0.1", [_SERVICE])

    assert directories == {80: ["/a/", "/b/"]}
    assert auth_paths == [] and findings == []
    assert login_paths == {80: []}


def test_a_disabled_crawl_returns_no_directories(monkeypatch):
    from src.modules.features.themis.managers.lybra import engine as engine_module

    monkeypatch.setattr(engine_module.CR, "lybra_crawler_config", lambda: type("_Cfg", (), {
        "max_pages": 0})())

    assert engine_module.LybraEngineManager()._run_crawler(  # pylint: disable=protected-access
        "10.0.0.1", [_SERVICE]) == ([], [], {}, {})
