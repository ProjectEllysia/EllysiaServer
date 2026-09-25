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

- cada error que declara ``message_key`` tiene su plantilla en ``es.json``,
  y rellenada con sus ``params`` da **exactamente** su ``user_message``;
- ``es.json`` no tiene plantillas de error que ningún error use.
"""

import importlib
import json
import re
from pathlib import Path

import pytest

from src.modules.shared._exceptions import (
    DatabaseConnectionError,
    EllysiaException,
    EntityNotFoundError,
    MissingJsonBodyError,
    MissingParameterError,
    SurfaceDisabledError,
    ValidationError,
    _derive_entity_key,
    create_error_response,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULES_ROOT = _REPO_ROOT / "API" / "src" / "modules"
_SPANISH_DICTIONARY = _REPO_ROOT / "web" / "app" / "src" / "i18n" / "locales" / "es.json"

# {parameter} -> parameter. Es la interpolación con nombre de vue-i18n.
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _import_every_exceptions_module() -> None:
    """Importa todos los ``exceptions.py`` de ``src/modules`` para registrar sus clases.

    ``__subclasses__`` solo ve las clases de módulos ya importados; sin esto, una
    excepción de un módulo que ningún otro test haya cargado quedaría fuera.
    """
    for path in _MODULES_ROOT.rglob("exceptions.py"):
        module_name = ".".join(path.relative_to(_REPO_ROOT / "API").with_suffix("").parts)
        importlib.import_module(module_name)


def _collect_subclasses(base: type) -> list[type]:
    """Devuelve todas las subclases de ``base``, a cualquier profundidad.

    Args:
        base: Clase de la que partir.

    Returns:
        list[type]: Las subclases, sin repetir y sin incluir ``base``.
    """
    found: dict[type, None] = {}
    pending = list(base.__subclasses__())
    while pending:
        subclass = pending.pop()
        if subclass not in found:
            found[subclass] = None
            pending.extend(subclass.__subclasses__())
    return list(found)


def _build_translatable_errors() -> list[EllysiaException]:
    """Construye un ejemplar de cada error cuyo mensaje sale de una plantilla.

    Returns:
        list[EllysiaException]: Un «no encontrado» por cada entidad del
            proyecto y un ejemplar de cada error con plantilla fija.
    """
    _import_every_exceptions_module()
    not_found_errors = [error_class() for error_class in _collect_subclasses(EntityNotFoundError)]
    return not_found_errors + [
        MissingParameterError("port"),
        MissingJsonBodyError(),
        SurfaceDisabledError("registration"),
        DatabaseConnectionError("connection refused"),
    ]


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


def test_a_free_text_error_carries_no_message_reference():
    """Un texto libre no se traduce por plantilla: la interfaz lo enseña tal cual."""
    assert ValidationError("el puerto 70000 está fuera de rango").to_message_reference() == {}
    assert SurfaceDisabledError("registration", user_message="Solo por invitación.").to_message_reference() == {}


def test_the_error_response_carries_the_message_reference():
    """La respuesta HTTP lleva la clave y los valores junto al texto."""
    response, status_code = create_error_response(MissingParameterError("port"))
    assert status_code == 400
    assert response["messageKey"] == "missingParameter"
    assert response["params"] == {"parameter": "port"}
    assert response["error_description"] == "El parámetro 'port' es obligatorio."


def test_derive_entity_key_strips_the_suffix_and_lowercases_the_initial():
    """La clave de entidad se deduce del nombre de la excepción."""
    assert _derive_entity_key("IrisCaseNotFoundError") == "irisCase"
    assert _derive_entity_key("ScanNotFoundError") == "scan"
    assert _derive_entity_key("EntityNotFoundError") == "entity"
