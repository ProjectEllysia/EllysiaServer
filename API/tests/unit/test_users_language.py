"""La regla que decide el idioma de cada usuario.

El idioma de un usuario sale de tres escalones: el que eligió, el que su
organización da por defecto y el de la plataforma. Estos tests fijan esa regla y
atan la lista de idiomas admitidos a los ficheros de textos de la interfaz: un
idioma que el servidor acepta y la interfaz no tiene dejaría al usuario pidiendo
algo que nadie sabe enseñarle.
"""

from pathlib import Path

import pytest

import src.modules.system.config_reading as CR
from src.modules.users.services.language import (
    SUPPORTED_LANGUAGES,
    choose_language,
    is_supported_language,
)

pytestmark = pytest.mark.unit

_LOCALES_DIRECTORY = Path(__file__).resolve().parents[3] / "web" / "app" / "src" / "i18n" / "locales"


def test_supported_languages_are_exactly_the_interface_language_files():
    """Cada idioma admitido tiene fichero de textos en la interfaz, y al revés."""
    interface_languages = {path.stem for path in _LOCALES_DIRECTORY.glob("*.json")}
    assert set(SUPPORTED_LANGUAGES) == interface_languages


def test_the_shipped_platform_language_is_supported():
    """El idioma de plataforma que viaja en SecOpsConfig.json es uno admitido."""
    assert is_supported_language(CR.localization_config().default_language)


def test_the_user_choice_wins():
    """Lo que eligió el usuario manda sobre su organización."""
    assert choose_language("en", "es") == "en"


def test_without_a_choice_the_organization_language_applies():
    """Sin elección propia, se usa el idioma por defecto de la organización."""
    assert choose_language(None, "en") == "en"


def test_without_choices_the_platform_language_applies():
    """Sin elección propia ni de la organización, se usa el de la plataforma."""
    assert choose_language(None, None) == CR.localization_config().default_language


def test_an_unsupported_choice_counts_as_no_choice():
    """Un código que la interfaz no tiene no se aplica: se pasa al escalón siguiente."""
    assert choose_language("xx", "en") == "en"
    assert choose_language("xx", "yy") == CR.localization_config().default_language


def test_is_supported_language_rejects_none_and_unknown_codes():
    """``None`` y los códigos desconocidos no son idiomas admitidos."""
    assert not is_supported_language(None)
    assert not is_supported_language("xx")
    assert all(is_supported_language(language) for language in SUPPORTED_LANGUAGES)
