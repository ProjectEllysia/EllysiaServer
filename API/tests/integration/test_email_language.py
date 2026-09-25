"""Los correos a usuarios de Ellysia salen en el idioma de cada destinatario.

El idioma es el de ``resolve_effective_language``: el que eligió el usuario,
si no el de su organización, si no el de la plataforma. Se prueba con el
recordatorio de MFA, que sale de un proceso de fondo sin nadie delante, y con
una versión inglesa de su plantilla puesta en un ``templatesDir`` temporal.
"""

from unittest import mock

import pytest

import src.modules.system.config_reading as CR
from src.modules.accounts.model import Organization, OrganizationMember
from src.modules.infrastructure.unit_of_work import UnitOfWork
from src.modules.tools.herald import SendResult
from src.modules.users.model import User
from src.modules.users.services.mfa_notices import send_mfa_reminders

pytestmark = pytest.mark.integration


@pytest.fixture()
def mailer():
    """Sustituye el envío real y deja ver los mensajes."""
    value = mock.Mock()
    value.send.return_value = SendResult(ok=True)
    with mock.patch("src.modules.users.services.mfa_notices.build_mailer", return_value=value):
        yield value


@pytest.fixture(autouse=True)
def english_mfa_reminder(tmp_path, monkeypatch):
    """Un ``templatesDir`` con el recordatorio de MFA en inglés."""
    english = tmp_path / "en"
    english.mkdir()
    (english / "mfa_reminder.subject.j2").write_text("Turn on MFA", encoding="utf-8")
    (english / "mfa_reminder.html.j2").write_text("<p>Hi, {{ recipient_name }}</p>", encoding="utf-8")
    monkeypatch.setattr(CR, "herald_config", lambda: CR.HeraldConfig(templates_dir=str(tmp_path)))


def _set_user_language(app, user_id: int, language: str | None) -> None:
    """Guarda el idioma elegido por un usuario."""
    with app.app_context():
        with UnitOfWork() as uow:
            uow.session.get(User, user_id).language = language


def _sent_subject(mailer) -> str:
    """Asunto del único correo enviado."""
    assert mailer.send.call_count == 1
    return mailer.send.call_args.args[0].subject


def test_without_choices_the_email_is_in_the_platform_language(app, regular_user, mailer):
    """Sin elección propia ni de organización, el correo sale en castellano."""
    with app.app_context():
        send_mfa_reminders()
    assert _sent_subject(mailer).startswith("Activa la autenticación")


def test_the_user_language_is_used(app, regular_user, mailer):
    """Quien eligió inglés recibe el correo en inglés."""
    _set_user_language(app, regular_user.id, "en")
    with app.app_context():
        send_mfa_reminders()
    assert _sent_subject(mailer) == "Turn on MFA"


def test_members_without_a_choice_get_the_organization_language(app, make_user, regular_user, mailer):
    """Quien no eligió sigue el idioma por defecto de su organización."""
    owner = make_user(unverified=True)  # no verificado: no recibe recordatorio
    with app.app_context():
        with UnitOfWork() as uow:
            organization = Organization(name="Acme", slug="acme", owner_user_id=owner.id, default_language="en")
            uow.session.add(organization)
            uow.session.flush()
            uow.session.add(OrganizationMember(
                organization_id=organization.id, user_id=regular_user.id, member_role="member",
            ))
        send_mfa_reminders()
    assert _sent_subject(mailer) == "Turn on MFA"
