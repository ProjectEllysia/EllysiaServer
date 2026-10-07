"""El pie de cada correo explica por qué lo recibe su destinatario.

Antes el pie daba una sola razón para todos los correos, cierta en las
formaciones de Aegis y falsa en los demás (confirmación de cuenta, recuperación
de contraseña, alertas...). Ahora cada correo trae su propio
``<nombre>.reason.j2``. Estos tests fijan que no falte ninguno, que la frase de
la formación no se cuele en otro correo y que el motivo llegue al HTML y al
texto plano.
"""

from pathlib import Path

import pytest

import src.modules.system.config_reading as CR
from src.modules.tools.herald import render_email

pytestmark = pytest.mark.unit

_PACKAGE_TEMPLATES = Path(CR.__file__).parents[1] / "tools" / "herald" / "templates"
_SPANISH = _PACKAGE_TEMPLATES / "es"

#: Plantillas compartidas que no son un correo por sí mismas.
_SHARED_PIECES = {"base", "_macros"}

#: Lo que solo es verdad para quien recibe una formación de concienciación.
_TRAINING_REASON = "plan de concienciación"


def _email_names() -> set[str]:
    """Nombres base de los correos que trae el paquete en castellano."""
    return {
        path.name.removesuffix(".html.j2") for path in _SPANISH.glob("*.html.j2")
    } - _SHARED_PIECES


def _reason_of(name: str) -> str:
    return (_SPANISH / f"{name}.reason.j2").read_text(encoding="utf-8").strip()


def test_every_email_has_its_own_reason():
    missing = {name for name in _email_names() if not (_SPANISH / f"{name}.reason.j2").is_file()}

    assert missing == set(), f"correos sin motivo en el pie: {sorted(missing)}"
    assert all(_reason_of(name) for name in _email_names()), "hay un motivo vacío"


def test_no_reason_file_is_left_without_its_email():
    orphans = {
        path.name.removesuffix(".reason.j2") for path in _SPANISH.glob("*.reason.j2")
    } - _email_names()

    assert orphans == set()


def test_each_email_gives_a_different_reason():
    reasons = {name: _reason_of(name) for name in _email_names()}

    assert len(set(reasons.values())) == len(reasons), "dos correos comparten motivo"


def test_the_training_reason_only_appears_in_the_campaign_email():
    """La frase de la formación era falsa en todos los demás correos."""
    offenders = sorted(
        path.name
        for path in _SPANISH.glob("*.j2")
        if not path.name.startswith("campaign.") and _TRAINING_REASON in path.read_text(encoding="utf-8")
    )

    assert offenders == []
    assert _TRAINING_REASON in _reason_of("campaign")
    assert _TRAINING_REASON not in CR.herald_config().branding.get("footerNote", "")


def test_the_footer_slot_is_in_the_base_and_in_every_plain_text_twin():
    assert "footer_reason" in (_SPANISH / "base.html.j2").read_text(encoding="utf-8")
    without_slot = [
        path.name for path in _SPANISH.glob("*.txt.j2")
        if "footer_reason" not in path.read_text(encoding="utf-8")
    ]
    assert without_slot == []


def test_the_reason_reaches_the_html_and_the_text():
    rendered = render_email("password_reset", reset_url="https://x.test/r", ttl_minutes=30)

    assert "alguien ha pedido restablecer la contraseña" in rendered.html
    assert "alguien ha pedido restablecer la contraseña" in rendered.text
    assert _TRAINING_REASON not in rendered.html
    assert _TRAINING_REASON not in rendered.text


def test_the_reason_can_use_the_brand_of_the_email():
    brand = {**CR.herald_config().branding, "productName": "Acme Seguridad"}

    rendered = render_email("mfa_reminder", brand=brand, recipient_name="Ana", profile_url="https://x.test")

    assert "cuenta de Acme Seguridad todavía no tiene activada" in rendered.html


def test_the_reason_is_escaped_in_the_html():
    brand = {**CR.herald_config().branding, "productName": "<b>Acme</b>"}

    rendered = render_email("mfa_reminder", brand=brand, recipient_name="Ana", profile_url="https://x.test")

    assert "&lt;b&gt;Acme&lt;/b&gt; todavía" in rendered.html
    assert "<b>Acme</b> todavía" not in rendered.html


def test_an_email_in_another_language_does_not_borrow_the_spanish_reason(tmp_path, monkeypatch):
    """Un correo en inglés sin su motivo sale sin él, no con uno en castellano."""
    english = tmp_path / "en"
    english.mkdir()
    (english / "mfa_reminder.subject.j2").write_text("Turn on MFA", encoding="utf-8")
    (english / "mfa_reminder.html.j2").write_text(
        '{% extends "base.html.j2" %}{% block content %}<p>Hi</p>{% endblock %}', encoding="utf-8",
    )
    monkeypatch.setattr(CR, "herald_config", lambda: CR.HeraldConfig(templates_dir=str(tmp_path)))

    rendered = render_email("mfa_reminder", language="en", recipient_name="Ana", profile_url="https://x.test")

    assert rendered.language == "en"
    assert "Recibes este correo" not in rendered.html
