"""
Avisos por correo de evidencias que caducan.

Un control con una evidencia vencida no está tan cumplido como parece, y nadie se acuerda de
revisarla hasta que llega la auditoría. Este trabajo programado avisa al dueño efectivo y al
responsable de cada control que usa la evidencia, **una vez por evidencia y fecha de validez**
(``expiry_notified_for``): si se renueva la fecha, vuelve a avisar cuando toque.

No decide nada ni toca el contenido: solo lee y manda correos, y el correo lleva el título de la
evidencia, nunca su contenido.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.tools.herald import EmailMessage, build_mailer, render_email
from src.modules.users import UserManager, resolve_effective_language

from ..repositories import (
    EunomiaControlAssessmentRepository,
    EunomiaEvidenceLinkRepository,
    EunomiaEvidenceRepository,
)
from .catalog import load_index, load_version

logger = logging.getLogger(__name__)


def _control_label(framework_key: str, identifier: str) -> str:
    """Un control como se lee en el correo: ``«NIS2 · RE.11.1 Control de accesos»``."""
    entry = next((item for item in load_index()["frameworks"] if item["key"] == framework_key), None)
    if entry is None:
        return f"{framework_key} · {identifier}"
    version = load_version(framework_key, entry["current"])
    node = version.node(f"{framework_key}:{identifier}") if version else None
    title = f" {node.title}" if node else ""
    return f"{entry['shortName']} · {identifier}{title}"


def send_expiry_notices(today: Optional[date] = None) -> int:
    """Avisa de las evidencias que vencen dentro de la antelación configurada o ya vencieron.

    Args:
        today: El día de referencia. Por defecto, hoy (UTC).

    Returns:
        int: Cuántas evidencias se avisaron. Un fallo de envío se registra y no interrumpe al
            resto; una evidencia cuyo aviso no salió a nadie se reintenta al día siguiente.
    """
    today = today or datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=CR.eunomia_config().evidence_expiry_notice_days)
    notified = 0
    with UnitOfWork() as uow:
        evidence_repo = EunomiaEvidenceRepository(uow)
        links_repo = EunomiaEvidenceLinkRepository(uow)
        assessments = EunomiaControlAssessmentRepository(uow)
        users = UserManager()
        for evidence in evidence_repo.list_expiring(horizon):
            links = links_repo.list_for_evidence(evidence.id)
            recipients = {evidence.owner_user_id}
            for link in links:
                row = assessments.get_for_control(evidence.owner_user_id, link.framework_key,
                                                  link.control_identifier)
                if row is not None and row.responsible_user_id is not None:
                    recipients.add(row.responsible_user_id)
            controls = [_control_label(link.framework_key, link.control_identifier) for link in links]
            sent = 0
            for user_id in recipients:
                user = users.get_user_by_id(user_id)
                if user is None:
                    continue
                try:
                    rendered = render_email(
                        "evidence_expiry",
                        language=resolve_effective_language(user),
                        recipient_name=user.first_name,
                        evidence_title=evidence.title,
                        valid_until=evidence.valid_until.strftime("%d/%m/%Y"),
                        is_expired=evidence.valid_until < today,
                        controls=controls,
                        eunomia_url=f"{CR.general_config().public_url}/eunomia/marcos",
                    )
                    build_mailer("eunomia").send(EmailMessage(
                        to=user.email, to_name=user.first_name, subject=rendered.subject,
                        html_body=rendered.html, text_body=rendered.text,
                    ))
                    sent += 1
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("No se pudo avisar a %s de la caducidad de la evidencia %s: %s",
                                 user.email, evidence.id, exc)
            if sent:
                evidence.expiry_notified_for = evidence.valid_until
                evidence_repo.save(evidence)
                notified += 1
    logger.info("Avisos de caducidad de evidencias enviados: %d", notified)
    return notified
