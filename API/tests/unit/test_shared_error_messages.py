"""Los errores traducibles de la API y su texto en el diccionario de la interfaz.

La API contesta a un error con su texto en castellano (``error_description``) y,
cuando ese texto sale entero de una plantilla, con la referencia a la plantilla
(``messageKey`` + ``params``). La interfaz busca esa clave en
``web/app/src/i18n/locales/es.json`` (y en el fichero de cada idioma) y
enseña su propio texto en vez del del servidor.

Eso abre una divergencia silenciosa: si la plantilla del servidor y la del
diccionario dicen cosas distintas, el usuario ve una frase que no es la que el
servidor quería decir, y ningún test de un lado ni del otro lo nota. Este
fichero ata las dos mitades, igual que ``test_caddy_api_routes.py`` ata el
Caddyfile a los blueprints:

- cada excepción que declara ``message_key`` (y cada subclase suya) tiene su
  plantilla en ``es.json``, y rellenada con sus ``params`` da **exactamente**
  su ``user_message``;
- ``es.json`` no tiene plantillas de error que ninguna excepción use.

Las excepciones se descubren solas: se buscan en ``src/`` las clases que pasan
``message_key=`` y se construye un ejemplar de cada una (y de sus subclases).
La que necesite argumentos para construirse los toma de
``_SAMPLE_ARGUMENTS``; si falta, el test lo dice.
"""

import ast
import importlib
import json
import re
from pathlib import Path

import pytest

from src.modules.shared._exceptions import (
    EntityNotFoundError,
    MissingParameterError,
    SurfaceDisabledError,
    ValidationError,
    _derive_entity_key,
    create_error_response,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _REPO_ROOT / "API"
_SOURCE_ROOT = _API_ROOT / "src"
_SPANISH_DICTIONARY = _REPO_ROOT / "web" / "app" / "src" / "i18n" / "locales" / "es.json"

# {parameter} -> parameter. Es la interpolación con nombre de vue-i18n.
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

#: Argumentos con los que se construye un ejemplar de cada excepción que no se
#: puede construir sin ellos. Los valores son de ejemplo: lo que se comprueba es
#: que la plantilla, rellenada con los ``params`` que salen de ellos, dé el
#: mismo texto que el servidor.
_SAMPLE_ARGUMENTS: dict[str, tuple] = {
    "RouteNotFoundError": ("/no-existe",),
    "MethodNotAllowedError": ("PATCH",),
    "MissingParameterError": ("port",),
    "SurfaceDisabledError": ("registration",),
    "DatabaseConnectionError": ("connection refused",),
    "InvalidAuthorizationHeaderError": ("falta la cabecera",),
    "InsufficientPermissionsError": ("falta el rol admin",),
    "PermissionCheckError": ("fallo al calcular permisos",),
    "TaskNotCancellableError": ("job-1",),
    "InvalidAgentKeyError": ("clave rechazada",),
}

#: Clases que declaran ``message_key`` pero no se lanzan nunca tal cual: solo
#: sus subclases llegan al cliente.
_ABSTRACT_ERRORS = {"EntityNotFoundError"}


def _find_classes_declaring_message_key() -> list[tuple[str, str]]:
    """Busca en ``src/`` las clases que pasan ``message_key=`` en alguna llamada.

    Returns:
        list[tuple[str, str]]: Pares (módulo importable, nombre de la clase).
    """
    declaring: list[tuple[str, str]] = []
    for path in _SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_name = ".".join(path.relative_to(_API_ROOT).with_suffix("").parts)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            passes_message_key = any(
                keyword.arg == "message_key"
                for call in ast.walk(node) if isinstance(call, ast.Call)
                for keyword in call.keywords
            )
            if passes_message_key:
                declaring.append((module_name, node.name))
    return declaring


def _import_every_exceptions_module() -> None:
    """Importa todos los ``exceptions.py`` de ``src/`` para registrar sus subclases.

    ``__subclasses__`` solo ve las clases de módulos ya importados; sin esto, una
    subclase de un módulo que ningún otro test haya cargado quedaría fuera.
    """
    for path in _SOURCE_ROOT.rglob("exceptions.py"):
        importlib.import_module(".".join(path.relative_to(_API_ROOT).with_suffix("").parts))


def _collect_with_subclasses(base: type) -> list[type]:
    """Devuelve ``base`` y todas sus subclases, a cualquier profundidad.

    Args:
        base: Clase de la que partir.

    Returns:
        list[type]: ``base`` seguida de sus subclases, sin repetir.
    """
    found: dict[type, None] = {base: None}
    pending = list(base.__subclasses__())
    while pending:
        subclass = pending.pop()
        if subclass not in found:
            found[subclass] = None
            pending.extend(subclass.__subclasses__())
    return list(found)


def _collect_translatable_error_classes() -> list[type]:
    """Reúne las excepciones con plantilla: las que declaran clave y sus subclases.

    Returns:
        list[type]: Las clases, sin repetir y sin las de ``_ABSTRACT_ERRORS``.
    """
    _import_every_exceptions_module()
    classes: dict[type, None] = {}
    for module_name, class_name in _find_classes_declaring_message_key():
        declaring_class = getattr(importlib.import_module(module_name), class_name)
        for error_class in _collect_with_subclasses(declaring_class):
            if error_class.__name__ not in _ABSTRACT_ERRORS:
                classes[error_class] = None
    return list(classes)


def _build_translatable_errors() -> list:
    """Construye un ejemplar de cada excepción con plantilla.

    Returns:
        list[EllysiaException]: Un ejemplar por clase.

    Raises:
        AssertionError: Si alguna no se puede construir con los argumentos de
            ``_SAMPLE_ARGUMENTS``; el mensaje dice cuáles.
    """
    errors, unbuildable = [], []
    for error_class in _collect_translatable_error_classes():
        try:
            errors.append(error_class(*_SAMPLE_ARGUMENTS.get(error_class.__name__, ())))
        except TypeError as exc:
            unbuildable.append(f"{error_class.__name__}: {exc}")
    assert not unbuildable, (
        "Estas excepciones declaran message_key pero el test no sabe construirlas; "
        "añade sus argumentos de ejemplo a _SAMPLE_ARGUMENTS:\n" + "\n".join(unbuildable)
    )
    # Una subclase con texto propio no hereda la clave de su base: su mensaje
    # ya no sale de la plantilla de la base.
    return [error for error in errors if error.message_key]


def _load_error_templates() -> dict[str, str]:
    """Lee las plantillas de error del diccionario castellano de la interfaz.

    Returns:
        dict[str, str]: Plantilla por clave de mensaje, con las claves anidadas
            unidas por punto (``"entityNotFound.scan"``), tal como las pide
            vue-i18n bajo ``apiErrors``.
    """
    dictionary = json.loads(_SPANISH_DICTIONARY.read_text(encoding="utf-8"))

    def flatten(node: dict, prefix: str) -> dict[str, str]:
        templates: dict[str, str] = {}
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                templates.update(flatten(value, path))
            else:
                templates[path] = value
        return templates

    return flatten(dictionary.get("apiErrors", {}), "")


def _render_template(template: str, params: dict) -> str:
    """Rellena los huecos ``{nombre}`` de una plantilla como lo hace vue-i18n.

    Args:
        template: Texto con huecos ``{nombre}``.
        params: Valor de cada hueco.

    Returns:
        str: La plantilla con cada hueco sustituido por su valor.
    """
    return _PLACEHOLDER_RE.sub(lambda match: str(params[match.group(1)]), template)


def test_every_translatable_error_has_its_spanish_template():
    """Cada error con clave tiene plantilla en es.json y da su mismo texto."""
    templates = _load_error_templates()
    problems = []
    for error in _build_translatable_errors():
        reference = error.to_message_reference()
        key = reference["messageKey"]
        if key not in templates:
            problems.append(f"{type(error).__name__}: falta apiErrors.{key} → «{error.user_message}»")
            continue
        rendered = _render_template(templates[key], reference["params"])
        if rendered != error.user_message:
            problems.append(f"{type(error).__name__}: es.json dice «{rendered}», el servidor «{error.user_message}»")
    assert not problems, "Plantillas de error desalineadas con la API:\n" + "\n".join(problems)


def test_the_spanish_dictionary_has_no_unused_error_templates():
    """Ninguna plantilla de apiErrors se queda sin error que la use."""
    used_keys = {error.message_key for error in _build_translatable_errors()}
    unused_keys = sorted(set(_load_error_templates()) - used_keys)
    assert not unused_keys, f"Plantillas de es.json que ningún error usa: {unused_keys}"


def test_the_discovery_finds_the_known_translatable_errors():
    """El descubrimiento automático encuentra errores de varias familias.

    Protege al propio test: si la búsqueda por AST dejara de encontrar clases,
    los dos tests de arriba pasarían en verde sin comprobar nada.
    """
    class_names = {error_class.__name__ for error_class in _collect_translatable_error_classes()}
    assert {"MissingParameterError", "ScanNotFoundError", "InvalidAccessTokenError", "TaskNotFoundError"} <= class_names


def test_a_free_text_error_carries_no_message_reference():
    """Un texto libre no se traduce por plantilla: la interfaz lo enseña tal cual."""
    assert ValidationError("el puerto 70000 está fuera de rango").to_message_reference() == {}
    assert SurfaceDisabledError("registration", user_message="Solo por invitación.").to_message_reference() == {}


def test_the_error_response_carries_the_message_reference():
    """La respuesta HTTP lleva la clave y los valores junto al texto."""
    response, status_code = create_error_response(MissingParameterError("port"))
    assert status_code == 400
    assert response["error"] == "missing_parameter"
    assert response["messageKey"] == "missingParameter"
    assert response["params"] == {"parameter": "port"}
    assert response["error_description"] == "El parámetro 'port' es obligatorio."


def test_derive_entity_key_strips_the_suffix_and_lowercases_the_initial():
    """La clave de entidad se deduce del nombre de la excepción."""
    assert _derive_entity_key("IrisCaseNotFoundError") == "irisCase"
    assert _derive_entity_key("ScanNotFoundError") == "scan"
    assert _derive_entity_key("EntityNotFoundError") == "entity"
    assert issubclass(type(EntityNotFoundError()), Exception)
