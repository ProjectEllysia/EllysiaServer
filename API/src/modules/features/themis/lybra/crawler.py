"""Rastreo de sólo lectura del mismo origen, con presupuesto duro.

Los checks de Lybra sólo piden las rutas que declaran (``/``, ``/.env``,
``/.git/config``…): nunca miran **qué hay** en el sitio. Eso deja fuera tres
cosas baratas y de sólo lectura que un escáner maduro sí ve:

- ``robots.txt``, que por definición lista las rutas que el dueño considera
  sensibles (``/administrator/``, ``/logs/``, ``/cli/``…).
- Los formularios de login y las rutas tras autenticación básica (un ``401``
  con ``WWW-Authenticate``): la entrada que el motor de credenciales por
  defecto necesita y que hoy no descubre por su cuenta.
- Los directorios reales del sitio, sobre los que los checks de ruta tienen
  más sentido que sobre la raíz.

Este módulo es la capa pura: recibe un ``fetch`` inyectado (la misma forma que
:meth:`~.checks.HttpProbe.fetch`), no toca la red directamente y no sabe nada
de ORM — igual que el resto de ``lybra/``. **Sólo hace ``GET``** y **no sale
del origen** que se le da. Todo el coste va acotado por tres topes: número de
páginas, profundidad de enlaces y tiempo.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple

from .checks import Response

# Los enlaces de una página: el destino de cada ``href`` y de cada ``action``
# de formulario. Deliberadamente simple — es un descubridor de rutas, no un
# navegador: no ejecuta JavaScript ni resuelve enlaces construidos en cliente.
_HREF_RE = re.compile(r"""(?:href|action)\s*=\s*["']([^"'#\s]+)["']""", re.IGNORECASE)
# Un formulario con un campo de contraseña: la marca de una superficie de
# autenticación por formulario.
_PASSWORD_INPUT_RE = re.compile(
    r"""<input\b[^>]*\btype\s*=\s*["']?password["']?""", re.IGNORECASE)
# Las extensiones de recursos que no son páginas: pedirlas no descubre rutas
# nuevas y gasta presupuesto. Un recurso así sólo se salta como enlace a
# seguir, no como hallazgo.
_NON_PAGE_SUFFIXES = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".gz", ".mp4", ".mp3",
)
#: Las entradas de ``robots.txt`` que nombran la web entera, no una ruta
#: concreta. ``Disallow: /`` sólo pide que no se indexe nada: no delata nada
#: que no se sepa ya, y la raíz se rastrea de todas formas.
_WHOLE_SITE_ENTRIES = ("/", "/*")


@dataclass
class CrawlResult:
    """Lo que un rastreo encontró, para que el motor lo convierta en hallazgos.

    Attributes:
        pages_fetched: Cuántas páginas se llegaron a pedir.
        robots_entries: Las rutas que ``robots.txt`` declara (``Disallow`` y
            ``Allow``), en el orden en que aparecen y sin repetir. Vacía si no
            hay ``robots.txt`` o no declara ninguna.
        login_paths: Las rutas donde se vio un formulario con campo de
            contraseña, sin repetir.
        basic_auth_paths: Las rutas que respondieron ``401`` con una cabecera
            ``WWW-Authenticate``, sin repetir.
        directories: Los directorios distintos observados en las rutas
            visitadas y descubiertas (cada segmento que termina en ``/``), sin
            repetir. Son las bases que los checks de ruta pueden reutilizar.
    """
    pages_fetched: int = 0
    robots_entries: List[str] = field(default_factory=list)
    login_paths: List[str] = field(default_factory=list)
    basic_auth_paths: List[str] = field(default_factory=list)
    directories: List[str] = field(default_factory=list)


def crawl(
    host: str,
    port: Optional[int],
    fetch: Callable[..., Optional[Response]],
    max_pages: int = 50,
    max_depth: int = 3,
    time_budget_seconds: float = 20.0,
    now: Callable[[], float] = time.monotonic,
) -> CrawlResult:
    """Rastrea el sitio en ``host:port`` de sólo lectura y con presupuesto.

    Se empieza por ``robots.txt`` y la raíz, y se sigue por los enlaces del
    mismo origen dentro de los tres topes. Cada página se pide una sola vez.

    Args:
        host: El objetivo. Durante un escaneo por nombre la resolución está
            fijada a la IP validada, así que ``host`` puede ser el nombre.
        port: El puerto (decide http vs https en el ``fetch``).
        fetch: La función de red inyectada, con la forma
            ``(host, port, method, path, body=None, headers=None) -> Response
            | None``. **Sólo se la llama con** ``method="GET"``.
        max_pages: Tope de páginas pedidas. A cero o menos, no se rastrea.
        max_depth: Profundidad máxima de enlaces desde la raíz.
        time_budget_seconds: Tope de tiempo del rastreo entero, en segundos.
        now: Reloj monótono inyectable, para que el test controle el tiempo.

    Returns:
        Un :class:`CrawlResult`. Vacío (con ``pages_fetched=0``) si
        ``max_pages`` es cero o menos.
    """
    result = CrawlResult()
    if max_pages <= 0:
        return result

    deadline = now() + time_budget_seconds
    seen: Set[str] = set()
    directories: Set[str] = set()
    queue: deque = deque()

    def enqueue(path: str, depth: int) -> None:
        normalized = _normalize_path(path)
        if normalized and normalized not in seen and depth <= max_depth:
            _record_directory(normalized, directories)
            queue.append((normalized, depth))

    for entry in _read_robots(host, port, fetch):
        result.robots_entries.append(entry)
        enqueue(entry, 1)
    enqueue("/", 0)

    while queue and result.pages_fetched < max_pages and now() < deadline:
        path, depth = queue.popleft()
        if path in seen:
            continue
        seen.add(path)

        response = fetch(host, port, "GET", path)
        result.pages_fetched += 1
        if response is None:
            continue

        if response.status == 401 and "www-authenticate" in response.headers:
            if path not in result.basic_auth_paths:
                result.basic_auth_paths.append(path)
            continue
        if response.status >= 400 or _is_non_page(path):
            continue

        if _PASSWORD_INPUT_RE.search(response.body or "") and path not in result.login_paths:
            result.login_paths.append(path)
        for link in _same_origin_links(response.body or "", path):
            enqueue(link, depth + 1)

    result.directories = sorted(directories)
    return result


def _read_robots(host, port, fetch) -> List[str]:
    """Las rutas que declara ``robots.txt``, en orden y sin repetir.

    Se leen tanto ``Disallow`` como ``Allow``: las dos nombran rutas que el
    dueño ha tenido presentes, y una ``Allow`` bajo un ``Disallow`` amplio
    suele señalar justo la excepción interesante. Las que nombran la web
    entera (:data:`_WHOLE_SITE_ENTRIES`) se omiten.

    Args:
        host: El host rastreado.
        port: El puerto del servicio web.
        fetch: ``(host, port, método, ruta) -> Response | None``.

    Returns:
        List[str]: Las rutas normalizadas; vacía si no hay ``robots.txt`` o no
            declara ninguna ruta concreta.
    """
    response = fetch(host, port, "GET", "/robots.txt")
    if response is None or response.status != 200:
        return []
    entries: List[str] = []
    for line in (response.body or "").splitlines():
        directive, _, value = line.partition(":")
        if directive.strip().lower() in ("disallow", "allow"):
            path = _normalize_path(value.strip())
            if path and path not in entries and path not in _WHOLE_SITE_ENTRIES:
                entries.append(path)
    return entries


def _same_origin_links(body: str, base_path: str) -> List[str]:
    """Las rutas del mismo origen a las que enlaza una página.

    Un enlace absoluto a otro host se descarta: el rastreo no sale del origen.
    Uno relativo se resuelve contra la ruta de la página actual. Se conserva
    sólo la ruta (sin esquema, host, query ni fragmento), que es la unidad que
    el rastreo pide y deduplica.
    """
    links: List[str] = []
    for raw in _HREF_RE.findall(body):
        split = urllib.parse.urlsplit(raw)
        if split.scheme and split.scheme not in ("http", "https"):
            continue          # mailto:, javascript:, tel:…
        if split.netloc:
            continue          # otro origen: fuera
        resolved = urllib.parse.urljoin(base_path, split.path)
        normalized = _normalize_path(resolved)
        if normalized and normalized not in links:
            links.append(normalized)
    return links


def _record_directory(path: str, directories: Set[str]) -> None:
    """Apunta el directorio contenedor de una ruta (todo hasta la última barra)."""
    directory = path.rsplit("/", 1)[0] + "/"
    directories.add(directory)


def _normalize_path(path: str) -> Optional[str]:
    """Normaliza una ruta a su forma canónica, o ``None`` si no es utilizable.

    Deja la ruta empezando por ``/``, sin query ni fragmento, y colapsa las
    barras repetidas. Una ruta vacía o que sube por encima de la raíz devuelve
    ``None``.
    """
    if not path:
        return None
    path = urllib.parse.urlsplit(path).path
    if not path:
        return None
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/{2,}", "/", path)
    if ".." in path.split("/"):
        return None
    return path


def _is_non_page(path: str) -> bool:
    """Si una ruta apunta a un recurso que no es una página (una hoja de estilo, una imagen)."""
    return path.lower().rsplit("/", 1)[-1].endswith(_NON_PAGE_SUFFIXES)
