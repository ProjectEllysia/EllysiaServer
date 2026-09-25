"""
Qué idioma corresponde a cada usuario.

Un usuario puede elegir idioma, o no. Si no elige, sigue el que su organización
da por defecto; y si su organización tampoco lo ha fijado (o no tiene
organización), el de la plataforma. Esta es la única implementación de esa
regla: la usa el perfil para decirle a la interfaz en qué idioma ponerse, y la
usarán los correos para elegir su plantilla. Dos implementaciones podrían
divergir y dejar a alguien con la web en un idioma y los correos en otro.
"""

from typing import Optional, TYPE_CHECKING

import src.modules.system.config_reading as CR

if TYPE_CHECKING:
    from src.modules.users.model import User

#: Idiomas que la instalación sabe mostrar. Son exactamente los que tienen
#: fichero de textos en la interfaz (``web/app/src/i18n/locales/<código>.json``):
#: guardar otro código dejaría al usuario pidiendo un idioma que la interfaz no
#: tiene. ``test_users_language.py`` ata la tupla a esos ficheros.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es")


def is_supported_language(language: Optional[str]) -> bool:
    """Indica si un código es uno de los idiomas que la instalación sabe mostrar.

    Args:
        language: Código de idioma (``"es"``, ``"en"``…), o ``None``.

    Returns:
        bool: ``True`` si está en ``SUPPORTED_LANGUAGES``; ``False`` si no lo
            está o es ``None``.
    """
    return language in SUPPORTED_LANGUAGES


def choose_language(user_language: Optional[str], organization_language: Optional[str]) -> str:
    """Aplica la regla de escalones a unos valores ya leídos.

    Está separada de ``resolve_effective_language`` para poder probar la regla
    sin base de datos. Un valor que no es un idioma admitido (un código que se
    retiró de la interfaz, por ejemplo) cuenta como no elegido y se pasa al
    escalón siguiente.

    Args:
        user_language: Idioma que eligió el usuario, o ``None`` si no eligió.
        organization_language: Idioma por defecto de su organización, o
            ``None`` si no tiene organización o no lo ha fijado.

    Returns:
        str: El idioma del usuario si es admitido; si no, el de la
            organización si es admitido; si no, el de la plataforma
            (``general.localization.defaultLanguage``).
    """
    for candidate in (user_language, organization_language):
        if is_supported_language(candidate):
            return candidate
    return CR.localization_config().default_language


def resolve_effective_language(user: "User") -> str:
    """Devuelve el idioma que corresponde a un usuario.

    Args:
        user: El usuario. Se lee su ``language`` y, si no eligió, el idioma
            por defecto de su organización.

    Returns:
        str: Código del idioma efectivo; ver ``choose_language``.
    """
    if is_supported_language(user.language):
        return user.language
    # Import diferido: accounts importa users al cargarse, y el ciclo se cierra
    # si este módulo lo importa arriba.
    from src.modules.accounts import OrganizationManager  # pylint: disable=import-outside-toplevel
    organization_language = OrganizationManager().get_default_language(user.id)
    return choose_language(user.language, organization_language)
