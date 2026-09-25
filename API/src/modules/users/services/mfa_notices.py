"""Recordatorios periódicos para activar MFA."""

from __future__ import annotations

import logging
from datetime import timedelta

import src.modules.system.config_reading as CR
from src.modules.infrastructure.unit_of_work import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.tools.herald import EmailMessage, build_mailer, render_email

from ..repositories import UserRepository
from .language import resolve_effective_language

logger = logging.getLogger(__name__)


def send_mfa_reminders() -> dict[str, int]:
    """Envía recordatorios vencidos sin interrumpir el lote ante un fallo."""
    now = utcnow_naive()
    interval_days = CR.mfa_config().notice_interval_days
    if interval_days <= 0:
        logger.warning("El intervalo de recordatorios MFA debe ser mayor que cero")
        return {"sent": 0, "failed": 0}

    with UnitOfWork() as uow:
        candidates = UserRepository(uow).get_pending_mfa_reminder_users(
            now - timedelta(days=interval_days)
        )
        recipients = [
            (user.id, user.email, user.first_name, resolve_effective_language(user))
            for user in candidates
        ]

    if not recipients:
        return {"sent": 0, "failed": 0}

    try:
        mailer = build_mailer("accounts")
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("No se pudo preparar el correo de recordatorios MFA: %s", exc)
        return {"sent": 0, "failed": len(recipients)}

    sent = 0
    failed = 0
    profile_url = f"{CR.general_config().public_url}/profile#mfa"

    for user_id, email, first_name, language in recipients:
        try:
            rendered = render_email(
                "mfa_reminder",
                language=language,
                recipient_name=first_name,
                profile_url=profile_url,
            )
            result = mailer.send(EmailMessage(
                to=email,
                to_name=first_name,
                subject=rendered.subject,
                html_body=rendered.html,
                text_body=rendered.text,
            ))
            if result is not None and not result.ok:
                raise RuntimeError(result.error or "El proveedor rechazó el correo")

            with UnitOfWork() as uow:
                UserRepository(uow).mark_mfa_reminder_sent(user_id, now)
            sent += 1
        except Exception as exc:  # pylint: disable=broad-except
            failed += 1
            logger.error("No se pudo enviar el recordatorio MFA a %s: %s", email, exc)

    summary = {"sent": sent, "failed": failed}
    logger.info("Recordatorios MFA procesados: %s", summary)
    return summary
