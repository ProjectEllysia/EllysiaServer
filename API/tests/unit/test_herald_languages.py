"""Los correos en el idioma de cada destinatario.

Las plantillas de herald viven en una carpeta por idioma. Un correo sale entero
en el idioma pedido si ese idioma tiene la plantilla, y entero en el de la
plataforma si no: nunca un asunto en un idioma con el cuerpo en otro. Estos
tests fijan esa elección, que el asunto sale de una plantilla y no del código,
y que cada correo del paquete trae su asunto.
"""

from pathlib import Path

import pytest

import src.modules.system.config_reading as CR
from src.modules.tools.herald import render_email

pytestmark = pytest.mark.unit

_PACKAGE_TEMPLATES = Path(CR.__file__).parents[1] / "tools" / "herald" / "templates"

#: Plantillas compartidas que no son un correo por sí mismas.
_SHARED_PIECES = {"base", "_macros"}


@pytest.fixture()
def english_override(tmp_path, monkeypatch):
    """Un ``templatesDir`` con la versión inglesa de ``mfa_reminder`` y nada más."""
    english = tmp_path / "en"
    english.mkdir()
    (english / "mfa_reminder.subject.j2").write_text("Turn on MFA in {{ brand.productName }}", encoding="utf-8")
    (english / "mfa_reminder.html.j2").write_text(
        '{% extends "base.html.j2" %}{% block content %}<p>Hi, {{ recipient_name }}</p>{% endblock %}',
        encoding="utf-8",
    )
    monkeypatch.setattr(CR, "herald_config", lambda: CR.HeraldConfig(templates_dir=str(tmp_path)))
    return tmp_path


def _email_names(language: str) -> set[str]:
    """Nombres base de los correos que trae el paquete en un idioma."""
    return {
        path.name.removesuffix(".html.j2")
        for path in (_PACKAGE_TEMPLATES / language).glob("*.html.j2")
    } - _SHARED_PIECES


def test_every_email_has_its_subject_template():
    """Cada correo del paquete trae su asunto: si faltara, el envío fallaría al renderizar."""
    names = _email_names("es")
    assert names, "no hay plantillas en templates/es/"
    missing = {name for name in names if not (_PACKAGE_TEMPLATES / "es" / f"{name}.subject.j2").is_file()}
    assert missing == set()


def test_the_subject_comes_from_its_template():
    """El asunto se renderiza con los datos del correo y en una sola línea."""
    rendered = render_email("iris_reauth_required", language="es", account_email="ana@example.com")
    assert rendered.subject == "[Iris] Reconecta tu buzón: ana@example.com"


def test_the_subject_collapses_line_breaks_from_the_data():
    """Un salto de línea en un dato (el asunto de un correo analizado) no rompe la cabecera."""
    rendered = render_email("iris_phishing", language="es", subject="Tu\nfactura", analysis_id=1, score=0.1)
    assert rendered.subject == "[Iris] Ten cuidado con el correo: Tu factura"


def test_the_subject_is_not_html_escaped():
    """El asunto es texto plano: un ``&`` no sale como ``&amp;``."""
    rendered = render_email("anomaly", language="es", hostname="a&b", kind="k", metric="m", value=1, threshold=1)
    assert rendered.subject == "[Hygeia] Anomalía crítica en a&b"


def test_without_language_the_email_uses_the_platform_one():
    """Sin idioma, el correo sale en el de la plataforma y lo declara en el HTML."""
    rendered = render_email("mfa_reminder", recipient_name="Ana", profile_url="https://e.es/p")
    assert rendered.language == CR.localization_config().default_language
    assert f'<html lang="{rendered.language}">' in rendered.html


def test_a_language_with_the_template_is_used(english_override):
    """Si el idioma tiene la plantilla, el correo sale entero en él."""
    rendered = render_email("mfa_reminder", language="en", recipient_name="Ana", profile_url="https://e.es/p")

    assert rendered.language == "en"
    assert rendered.subject == "Turn on MFA in Ellysia"
    assert "Hi, Ana" in rendered.html
    assert '<html lang="en">' in rendered.html


def test_shared_pieces_fall_back_to_the_platform_language(english_override):
    """Una traducción no copia ``base.html.j2``: la toma del idioma de la plataforma."""
    rendered = render_email("mfa_reminder", language="en", recipient_name="Ana", profile_url="https://e.es/p")
    assert rendered.html.startswith("<!DOCTYPE html>")


def test_a_language_without_the_template_falls_back_whole(english_override):
    """Si el idioma no tiene ese correo, sale entero en el de la plataforma, asunto incluido."""
    rendered = render_email("password_reset", language="en", recipient_name="Ana", reset_url="https://e.es/r", ttl_minutes=30)

    assert rendered.language == CR.localization_config().default_language
    assert rendered.subject == "Recupera tu clave de Ellysia"


def test_an_unknown_language_falls_back_to_the_platform():
    """Un código sin carpeta (el de una píldora es texto libre) no falla: usa el de la plataforma."""
    rendered = render_email("mfa_reminder", language="fr", recipient_name="Ana", profile_url="https://e.es/p")
    assert rendered.language == CR.localization_config().default_language


def test_a_language_code_cannot_escape_the_templates_folder(tmp_path, monkeypatch):
    """Un código como ``..`` no compone una ruta fuera de la carpeta del idioma."""
    (tmp_path / "mfa_reminder.subject.j2").write_text("fuera", encoding="utf-8")
    (tmp_path / "mfa_reminder.html.j2").write_text("fuera", encoding="utf-8")
    (tmp_path / "es").mkdir()
    monkeypatch.setattr(CR, "herald_config", lambda: CR.HeraldConfig(templates_dir=str(tmp_path / "es")))

    rendered = render_email("mfa_reminder", language="..", recipient_name="Ana", profile_url="https://e.es/p")

    assert rendered.language == CR.localization_config().default_language
    assert rendered.subject != "fuera"
