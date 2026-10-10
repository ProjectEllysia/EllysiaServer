"""
Avisos por correo de los plazos de los registros.

Un plazo que corre desde una fecha de la ficha (las 24 y 72 horas de un incidente, el mes del
informe final) se pierde si nadie lo mira. Este trabajo programado, que corre cada hora porque
algunos plazos se miden en horas, avisa al dueño efectivo **una vez por ficha y plazo** cuando falta
poco para que venza, o cuando ya venció sin cumplirse. El aviso se anota en la ficha
(``notified_deadlines``): si el plazo se cumple o la ficha se archiva, deja de avisarse.

El correo lleva el nombre de la ficha y el del plazo, nunca el resto de sus datos.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.tools.herald import EmailMessage, build_mailer, render_email
from src.modules.users import UserManager, resolve_effective_language

from ..repositories import EunomiaRecordRepository
from .registers import (
    DEADLINE_OVERDUE,
    DEADLINE_UPCOMING,
    RegisterType,
    compute_deadlines,
    load_registers,
)

logger = logging.getLogger(__name__)

#: Tope de antelación del aviso, en horas: un plazo de un mes no se avisa con un mes de margen.
MAX_ADVANCE_HOURS = 72

_HOURS_PER_UNIT = {"hours": 1, "days": 24, "months": 24 * 30}


def advance_window(register: RegisterType, deadline_key: str) -> timedelta:
    """Con cuánta antelación se avisa de un plazo: un tercio de su duración, con tope.

    Args:
        register: La definición del registro.
        deadline_key: Clave del plazo.

    Returns:
        timedelta: Un tercio de lo que dura el plazo, y como mucho ``MAX_ADVANCE_HOURS``.
    """
    deadline = next(item for item in register.deadlines if item.key == deadline_key)
    span_hours = deadline.amount * _HOURS_PER_UNIT[deadline.unit]
    return timedelta(hours=min(span_hours / 3, MAX_ADVANCE_HOURS))


def send_deadline_notices(now: Optional[datetime] = None) -> int:
    """Avisa de los plazos que están por vencer o ya vencieron sin cumplirse.

    Args:
        now: Instante de referencia (naive UTC). Por defecto, ahora.

    Returns:
        int: Cuántos avisos salieron. Un fallo de envío se registra y no interrumpe al resto; el
            plazo no se marca como avisado y se reintenta en la siguiente pasada.
    """
    now = now or utcnow_naive()
    registers = {register.key: register for register in load_registers() if register.deadlines}
    sent = 0
    with UnitOfWork() as uow:
        repo = EunomiaRecordRepository(uow)
        users = UserManager()
        for record in repo.list_open_for_registers(list(registers)):
            register = registers[record.register_key]
            already = list(record.notified_deadlines or [])
            due_now = []
            for item in compute_deadlines(register, dict(record.values), now):
                if item["key"] in already or item["status"] not in (DEADLINE_UPCOMING, DEADLINE_OVERDUE):
                    continue
                if item["status"] == DEADLINE_OVERDUE or item["dueAt"] - now <= advance_window(register, item["key"]):
                    due_now.append(item)
            if not due_now:
                continue
            user = users.get_user_by_id(record.owner_user_id)
            if user is None:
                continue
            try:
                rendered = render_email(
                    "register_deadline", language=resolve_effective_language(user), recipient_name=user.first_name,
                    register_title=register.title, record_title=record.values.get(register.title_field, ""),
                    deadlines=[{"label": item["label"], "due": item["dueAt"].strftime("%d/%m/%Y %H:%M"),
                                "is_overdue": item["status"] == DEADLINE_OVERDUE} for item in due_now],
                    eunomia_url=f"{CR.general_config().public_url}/eunomia/registros/{register.key}",
                )
                build_mailer("eunomia").send(EmailMessage(
                    to=user.email, to_name=user.first_name, subject=rendered.subject,
                    html_body=rendered.html, text_body=rendered.text))
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("No se pudo avisar a %s de los plazos de la ficha %s: %s", user.email, record.id, exc)
                continue
            record.notified_deadlines = already + [item["key"] for item in due_now]
            repo.save(record)
            sent += 1
    logger.info("Avisos de plazos de registros enviados: %d", sent)
    return sent
