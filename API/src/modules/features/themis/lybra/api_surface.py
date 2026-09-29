"""Superficie de una API a partir de su especificación OpenAPI/Swagger.

Cuando un servicio publica su especificación (``/openapi.json``,
``/v3/api-docs``…), esa especificación **dice qué endpoints existen y cuáles
deberían pedir credenciales**. Eso es exactamente lo que un check genérico no
sabe: probar mil rutas al azar es fuzzing y produce una lista plana de ruido,
y el valor está en lo que la especificación declara protegido y, sin embargo,
contesta a quien no se identifica.

Este módulo es la capa pura: parsea el documento y **deriva checks** del tipo
que el runtime ya sabe ejecutar (``type: "http"``). No toca la red ni el ORM,
igual que el resto de ``lybra/``; quien pide la especificación y ejecuta los
checks derivados es el manager (``managers/lybra/api_surface.py``).

Dos reglas mantienen esto lejos de un fuzzer:

- **Sólo se prueba lo que la especificación declara** y, salvo el caso de
  asignación masiva, sólo con peticiones que no cambian nada: un ``GET`` a un
  endpoint sin parámetros de ruta que la especificación marca como protegido.
- **Todo va acotado** por ``max_endpoints``: el tope se aplica al derivar, no
  al ejecutar, así que una especificación con miles de rutas cuesta lo mismo
  que una con veinte.

El único check derivado que escribe en el objetivo es el de asignación masiva
(``mode: aggressive``): un ``PUT``/``PATCH`` a un recurso sin parámetros de
ruta con **una sola propiedad inventada** y un marcador único, y una lectura
posterior que comprueba si el servidor la guardó. Se inventa la propiedad a
propósito: enviar ``role`` o ``isAdmin`` de verdad podría concederle privilegios
a alguien, y demostrar que el servidor persiste propiedades que no declara
basta para probar el fallo.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .checks import Check, Matcher, Request

# Dónde se busca la especificación. Es un ``GET`` a rutas conocidas: cuatro
# peticiones por servicio web, no un barrido.
SPECIFICATION_PATHS: Tuple[str, ...] = (
    "/openapi.json",
    "/swagger.json",
    "/v2/api-docs",
    "/v3/api-docs",
)

# La propiedad inventada y el valor único del check de asignación masiva. Nada
# en una API real se llama así, así que verla de vuelta sólo puede significar
# que el servidor guardó lo que le enviamos.
MASS_ASSIGNMENT_PROPERTY = "lybraProbe"
MASS_ASSIGNMENT_MARKER = "lybra-mass-assignment-marker"

_HTTP_METHODS = ("get", "put", "patch", "post", "delete", "options", "head")
_WRITE_METHODS = ("put", "patch")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_JSON_CONTENT_TYPE = {"Content-Type": "application/json"}


@dataclass(frozen=True)
class ApiEndpoint:
    """Una operación declarada en la especificación.

    Attributes:
        method: El método HTTP en mayúsculas (``"GET"``, ``"PUT"``…).
        path: La ruta tal como la declara la especificación, con su base ya
            antepuesta (``/api/v1/users``). Puede llevar ``{parámetros}``.
        requires_authentication: Si la especificación declara la operación como
            protegida: la operación trae un ``security`` no vacío, o no trae
            ninguno y lo trae el documento entero. Un ``security`` con un
            requisito vacío (``[{}]``) significa que la autenticación es
            opcional y **no** cuenta como protegida.
    """
    method: str
    path: str
    requires_authentication: bool

    @property
    def has_path_parameters(self) -> bool:
        """Si la ruta necesita un valor concreto (``/users/{id}``) que no tenemos."""
        return "{" in self.path


@dataclass(frozen=True)
class ApiSpecification:
    """Lo que interesa de una especificación ya parseada.

    Attributes:
        title: El título que declara ``info.title``, o cadena vacía.
        endpoints: Las operaciones declaradas, en el orden del documento.
    """
    title: str
    endpoints: Tuple[ApiEndpoint, ...]


def _base_path(document: dict) -> str:
    """La ruta base común de todas las operaciones del documento.

    OpenAPI 3 la lleva en la URL del primer servidor; Swagger 2, en
    ``basePath``. Una URL de servidor con variables (``{region}``) no se puede
    resolver sin inventar valores, así que se ignora y las rutas quedan sin
    base.

    Args:
        document: El documento parseado.

    Returns:
        str: La base sin barra final (``"/api/v1"``), o cadena vacía.
    """
    servers = document.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = str(servers[0].get("url") or "")
        if "{" in url:
            return ""
        base = urllib.parse.urlparse(url).path
    else:
        base = str(document.get("basePath") or "")
    return base.rstrip("/") if base.startswith("/") else ""


def _declares_protection(security: Any) -> bool:
    """Si un valor ``security`` de la especificación exige autenticación de verdad.

    Args:
        security: La lista de requisitos, o cualquier otra cosa si el documento
            está mal formado.

    Returns:
        bool: ``True`` si hay al menos un requisito y ninguno es el vacío
            (``{}``), que en OpenAPI significa «la autenticación es opcional».
    """
    if not isinstance(security, list) or not security:
        return False
    return all(isinstance(requirement, dict) and requirement for requirement in security)


def parse_specification(text: str) -> Optional[ApiSpecification]:
    """Parsea una especificación OpenAPI 3 o Swagger 2 en JSON.

    Args:
        text: El cuerpo de la respuesta que debería ser la especificación.

    Returns:
        ApiSpecification: La superficie declarada. ``None`` si el texto no es
            JSON, no es una especificación (sin ``openapi``/``swagger`` y sin
            ``paths``) o no declara ninguna operación — quien llama trata los
            tres casos igual: no hay nada que derivar.
    """
    try:
        document = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(document, dict) or not (document.get("openapi") or document.get("swagger")):
        return None
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return None
    base = _base_path(document)
    document_is_protected = _declares_protection(document.get("security"))
    endpoints: List[ApiEndpoint] = []
    for path, operations in paths.items():
        if not isinstance(operations, dict) or not str(path).startswith("/"):
            continue
        for method in _HTTP_METHODS:
            operation = operations.get(method)
            if not isinstance(operation, dict):
                continue
            protected = (_declares_protection(operation["security"]) if "security" in operation
                         else document_is_protected)
            endpoints.append(ApiEndpoint(method.upper(), base + str(path), protected))
    if not endpoints:
        return None
    info = document.get("info")
    title = str(info.get("title") or "") if isinstance(info, dict) else ""
    return ApiSpecification(title=title, endpoints=tuple(endpoints))


def _identifier(kind: str, endpoint: ApiEndpoint) -> str:
    """El id de un check derivado: distinto por endpoint.

    El id entra en la clave de deduplicación del hallazgo, así que dos
    endpoints con el mismo id se fundirían en uno. Lleva un resumen de la ruta
    además de su forma legible para que dos rutas que difieran sólo en
    caracteres no alfanuméricos no colisionen tras normalizarlas.

    Args:
        kind: El tipo de check derivado (``"open"`` o ``"mass-assignment"``).
        endpoint: El endpoint del que sale.

    Returns:
        str: ``api-<kind>-<método>-<ruta normalizada>-<resumen>``.
    """
    slug = _SLUG_RE.sub("-", endpoint.path.lower()).strip("-")[:40]
    digest = hashlib.sha256(f"{endpoint.method} {endpoint.path}".encode()).hexdigest()[:8]
    return f"api-{kind}-{endpoint.method.lower()}-{slug}-{digest}"


def _open_endpoint_check(endpoint: ApiEndpoint) -> Check:
    """Check de un endpoint declarado protegido que contesta sin credenciales.

    Exige un ``200`` **y** contenido JSON: una aplicación de una sola página
    devuelve su ``index.html`` con ``200`` para cualquier ruta, y eso no es una
    API abierta.

    Args:
        endpoint: Un ``GET`` protegido y sin parámetros de ruta.

    Returns:
        Check: El check listo para el runtime.
    """
    return Check(
        id=_identifier("open", endpoint), version=1, type="http",
        category="api_exposure", severity="HIGH", service="http", mode="safe",
        requests=(Request(
            method="GET", path=endpoint.path,
            matchers=(Matcher("status", values=(200,)),
                      Matcher("word", part="header", values=("application/json",))),
        ),),
        finding={
            "title": f"Endpoint que la especificación declara protegido responde sin credenciales (GET {endpoint.path})",
            "qod": 90, "confirmed": True,
        },
    )


def _mass_assignment_check(endpoint: ApiEndpoint) -> Check:
    """Check de asignación masiva sobre un recurso sin parámetros de ruta.

    Envía la propiedad inventada y, en una segunda petición, lee el recurso:
    sólo si el marcador vuelve, el servidor guardó una propiedad que nadie le
    había declarado. Es ``aggressive`` porque la primera petición escribe.

    Args:
        endpoint: Un ``PUT`` o ``PATCH`` sin parámetros de ruta.

    Returns:
        Check: El check listo para el runtime.
    """
    return Check(
        id=_identifier("mass-assignment", endpoint), version=1, type="http",
        category="api_exposure", severity="MEDIUM", service="http", mode="aggressive",
        requests=(
            Request(
                method=endpoint.method, path=endpoint.path,
                headers=tuple(_JSON_CONTENT_TYPE.items()),
                body=json.dumps({MASS_ASSIGNMENT_PROPERTY: MASS_ASSIGNMENT_MARKER}),
                matchers=(Matcher("status", values=(200, 201, 202, 204)),),
            ),
            Request(
                method="GET", path=endpoint.path,
                matchers=(Matcher("word", part="body", values=(MASS_ASSIGNMENT_MARKER,)),),
            ),
        ),
        finding={
            "title": f"La API guarda propiedades que no declara: asignación masiva ({endpoint.method} {endpoint.path})",
            "qod": 95, "confirmed": True,
        },
    )


def derive_checks(specification: ApiSpecification, max_endpoints: int) -> List[Check]:
    """Deriva los checks de una especificación, con un tope duro.

    Primero los endpoints ``GET`` protegidos y sin parámetros de ruta (lo que
    más importa y no cambia nada) y después los ``PUT``/``PATCH`` sin
    parámetros de ruta (asignación masiva). Los dos comparten el tope: el
    orden decide qué se sacrifica si la especificación es enorme.

    Args:
        specification: La especificación parseada.
        max_endpoints: Máximo de checks derivados. Por debajo de ``1`` no se
            deriva ninguno.

    Returns:
        List[Check]: A lo sumo ``max_endpoints`` checks, sin repeticiones.
    """
    if max_endpoints < 1:
        return []
    candidates = [endpoint for endpoint in specification.endpoints
                  if not endpoint.has_path_parameters]
    protected_reads = [_open_endpoint_check(endpoint) for endpoint in candidates
                       if endpoint.method == "GET" and endpoint.requires_authentication]
    writes = [_mass_assignment_check(endpoint) for endpoint in candidates
              if endpoint.method.lower() in _WRITE_METHODS]
    unique: Dict[str, Check] = {}
    for check in protected_reads + writes:
        unique.setdefault(check.id, check)
    return list(unique.values())[:max_endpoints]
