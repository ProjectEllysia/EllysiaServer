"""
herald.rendering
────────────────
Capa de plantillas de los correos.

Un correo se compone de tres plantillas con el mismo nombre base:
``<nombre>.subject.j2`` (el asunto), ``<nombre>.html.j2`` (el cuerpo) y, si
existe, su gemelo ``<nombre>.txt.j2`` (la alternativa en texto plano).

Las plantillas viven en una carpeta por idioma (``templates/es/``,
``templates/en/``…). Un correo sale entero en el idioma pedido si ese idioma
tiene su cuerpo HTML; si no, sale entero en el idioma de la plataforma
(``general.localization.defaultLanguage``). Se decide por correo y no por
fichero para que un idioma a medio traducir no mezcle un asunto en un idioma
con un cuerpo en otro. Las piezas compartidas (``base.html.j2``,
``_macros.html.j2``) sí caen fichero a fichero al idioma de la plataforma: una
traducción no tiene por qué copiarlas.

``tools.herald.templatesDir`` permite sobreescribir cualquier plantilla desde
fuera sin tocar el código. Ese directorio reproduce la misma estructura por
idioma (``<templatesDir>/es/campaign.html.j2``) y se mira antes que el del
paquete.

El autoescape está activo en el HTML: los datos que llegan de la BD (nombres de
destinatario, títulos de píldora, hostnames) se escapan solos.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, TemplateNotFound

import src.modules.system.config_reading as CR

from .branding import default_brand

logger = logging.getLogger(__name__)

_PACKAGE_TEMPLATES = Path(__file__).parent / "templates"

#: Entornos ya construidos, por (templatesDir, idioma, idioma de plataforma).
#: La clave incluye la config, así que un cambio en ella construye otro.
_env_cache: dict[tuple[str, str, str], Environment] = {}


class RenderedEmail(NamedTuple):
    """Correo ya renderizado, listo para pasarlo a ``EmailMessage``.

    Attributes:
        subject: Asunto en una sola línea, con los espacios normalizados.
        html: Cuerpo HTML.
        text: Cuerpo en texto plano, o ``None`` si la plantilla no tiene
            gemelo ``.txt.j2``; en ese caso la estrategia SMTP lo deriva del
            HTML.
        language: Idioma en que salió de verdad: el pedido, o el de la
            plataforma si el pedido no tiene esa plantilla.
    """

    subject: str
    html: str
    text: str | None
    language: str


def _autoescape(template_name: str | None) -> bool:
    """Indica si una plantilla se renderiza con autoescape.

    Solo se escapa el HTML: en el ``.txt.j2`` y en el asunto saldrían ``&amp;``
    y ``&#39;`` literales.

    Args:
        template_name: Nombre de la plantilla que va a renderizar Jinja.

    Returns:
        bool: ``True`` si es una plantilla ``.html.``.
    """
    return bool(template_name and ".html." in template_name)


def _language_directories(language: str) -> list[Path]:
    """Carpetas en las que buscar las plantillas de un idioma, por prioridad.

    Args:
        language: Código del idioma (``"es"``, ``"en"``…).

    Returns:
        list[Path]: La carpeta del idioma en ``templatesDir`` (si está
            configurado y existe) y después la del paquete.
    """
    override_dir = CR.herald_config().templates_dir
    directories = [_PACKAGE_TEMPLATES / language]
    if override_dir and Path(override_dir).is_dir():
        directories.insert(0, Path(override_dir) / language)
    return directories


def _environment(language: str, platform_language: str) -> Environment:
    """Entorno de Jinja que busca en un idioma y cae al de la plataforma.

    Args:
        language: Idioma del correo.
        platform_language: Idioma de la plataforma, donde se buscan las
            piezas que el idioma del correo no tenga.

    Returns:
        Environment: El entorno, cacheado mientras no cambie la config.
    """
    key = (CR.herald_config().templates_dir, language, platform_language)
    if key not in _env_cache:
        directories = _language_directories(language)
        if platform_language != language:
            directories += _language_directories(platform_language)
        _env_cache[key] = Environment(
            loader=ChoiceLoader([FileSystemLoader(str(directory)) for directory in directories]),
            autoescape=_autoescape,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env_cache[key]


def _has_template(language: str, template: str) -> bool:
    """Indica si un idioma tiene su propio cuerpo HTML para un correo.

    Args:
        language: Código del idioma.
        template: Nombre base de la plantilla, sin extensión.

    Returns:
        bool: ``True`` si ``<idioma>/<template>.html.j2`` existe en
            ``templatesDir`` o en el paquete.
    """
    return any((directory / f"{template}.html.j2").is_file() for directory in _language_directories(language))


def render_email(template: str, language: str | None = None, **context) -> RenderedEmail:
    """Renderiza el asunto y el cuerpo de un correo en un idioma.

    Args:
        template: Nombre base de la plantilla, sin extensión (``"campaign"``).
        language: Idioma del destinatario (``"es"``, ``"en"``…). Si es
            ``None``, no es un código de letras o no tiene esta plantilla, se
            usa el de la plataforma. Por defecto ``None``.
        **context: Variables de la plantilla. Se inyectan solas ``language``
            (el idioma en que sale el correo, para el ``lang`` del HTML) y
            ``brand``, la marca del producto (``branding.default_brand``) si
            el llamante no la pasa; quien haga white-labeling pasa la suya ya
            resuelta con ``branding.apply_white_label``.

    Returns:
        RenderedEmail: Asunto, HTML, texto plano (o ``None``) e idioma usado.

    Raises:
        TemplateNotFound: Si la plantilla no existe ni en el idioma pedido ni
            en el de la plataforma.
    """
    platform_language = CR.localization_config().default_language
    # isalpha() impide que un código como "../x" (el de una píldora es texto
    # libre) componga una ruta fuera de la carpeta de plantillas.
    if not language or not language.isalpha() or not _has_template(language, template):
        if language and language != platform_language:
            logger.info(
                "[herald] '%s' no tiene versión en '%s'; sale en '%s'",
                template, language, platform_language,
            )
        language = platform_language

    env = _environment(language, platform_language)
    context.setdefault("brand", default_brand())
    context["language"] = language

    subject = " ".join(env.get_template(f"{template}.subject.j2").render(**context).split())
    html = env.get_template(f"{template}.html.j2").render(**context)
    try:
        text = env.get_template(f"{template}.txt.j2").render(**context)
    except TemplateNotFound:
        text = None

    return RenderedEmail(subject=subject, html=html, text=text, language=language)
