"""
EunomiaRegisterManager — las fichas de los registros del dueño efectivo de los datos.

Los tipos de registro son datos (``registers/``); aquí solo se guardan y se leen sus fichas.
El dueño y los miembros de su organización crean y editan las mismas fichas, como con las
evaluaciones. Los plazos se calculan al leer y no se guardan.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.modules.accounts import CompanyProfileManager, OrganizationManager
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive

from ..exceptions import RecordConflictError, RecordInvalidError, RecordNotFoundError, RegisterNotFoundError
from ..model import EunomiaRecord, EunomiaRecordEvent
from ..repositories import EunomiaRecordEventRepository, EunomiaRecordRepository
from ..services.documents.register_export import RegisterPDF, build_csv
from ..services.registers import RegisterType, compute_deadlines, get_register, load_registers, validate_values
from ..services.templates import load_templates
from .assessments import display_name

logger = logging.getLogger(__name__)


def _register(key: str) -> RegisterType:
    """La última versión de un tipo de registro, o ``RegisterNotFoundError``."""
    register = get_register(key)
    if register is None:
        raise RegisterNotFoundError(key)
    return register


def _payload(register: RegisterType, row: EunomiaRecord, names: dict, now: datetime) -> dict:
    """Una ficha tal como la ve el cliente, con sus plazos calculados."""
    values = dict(row.values)
    return {
        "id": row.id, "registerKey": row.register_key, "values": values,
        "title": values.get(register.title_field, ""), "isArchived": row.is_archived,
        "createdAt": row.created_at, "createdByName": names.get(row.created_by_user_id),
        "updatedAt": row.updated_at, "updatedByName": names.get(row.updated_by_user_id),
        # Las fechas de los plazos viajan en ISO con «Z»: dentro de un ``Dict`` ningún schema las formatea.
        "deadlines": [{**item, "dueAt": item["dueAt"].isoformat() + "Z" if item["dueAt"] else None}
                      for item in compute_deadlines(register, values, now)],
    }


def _names(rows: list[EunomiaRecord]) -> dict:
    """Los nombres de quienes crearon o editaron las fichas, resueltos una vez por usuario."""
    ids = {value for row in rows for value in (row.created_by_user_id, row.updated_by_user_id) if value}
    return {user_id: display_name(user_id) for user_id in ids}


def _advice(register: RegisterType, company: dict) -> list[str]:
    """Los avisos de la definición que aplican al perfil de empresa."""
    messages = []
    for item in register.advice:
        value = company.get(item["companyField"])
        if isinstance(value, int) and value < item["lessThan"]:
            messages.append(item["message"])
    return messages


def _checked(register: RegisterType, values: dict) -> dict[str, str]:
    """Los valores con texto de una ficha ya validada, o ``RecordInvalidError``."""
    problems = validate_values(register, values)
    if problems:
        labels = [register.field(key).label if register.field(key) else key for key in problems]
        raise RecordInvalidError(problems, labels)
    return {key: value for key, value in values.items() if value.strip()}


def _naive_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """El instante en UTC sin zona, que es como se guarda; el cliente devuelve el testigo con su zona."""
    if moment is not None and moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


class EunomiaRegisterManager:
    """Registros y sus fichas."""

    def list_registers(self, user_id: int) -> list[dict]:
        """Los tipos de registro con cuántas fichas tiene el dueño efectivo en cada uno.

        Args:
            user_id: Usuario que pregunta; ve lo del dueño efectivo.

        Returns:
            list[dict]: ``key``, ``version``, ``title``, ``summary``, ``controls``,
                ``recordCount`` y ``openDeadlines`` (plazos vencidos o por vencer sin cumplir).
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        counts = build_repository(EunomiaRecordRepository).count_by_register(owner_user_id)
        latest: dict[str, RegisterType] = {}
        for register in sorted(load_registers(), key=lambda item: int(item.version)):
            latest[register.key] = register
        return [{"key": item.key, "version": item.version, "title": item.title, "summary": item.summary,
                 "controls": {k: list(v) for k, v in item.controls.items()},
                 "recordCount": counts.get(item.key, 0)} for item in latest.values()]

    def get_register(self, user_id: int, register_key: str, include_archived: bool = False) -> dict:
        """La definición de un registro y sus fichas.

        Args:
            user_id: Usuario que pregunta.
            register_key: Tipo de registro.
            include_archived: Si salen también las archivadas. Por defecto ``False``.

        Returns:
            dict: ``register`` (definición con ``fields``, ``deadlines`` y ``examples``) y
                ``records``.

        Raises:
            RegisterNotFoundError: Si no hay tipo con esa clave (404).
        """
        register = _register(register_key)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        rows = build_repository(EunomiaRecordRepository).list_for_register(owner_user_id, register_key, include_archived)
        names, now = _names(rows), utcnow_naive()
        return {
            "register": {
                "key": register.key, "version": register.version, "title": register.title,
                "summary": register.summary, "titleField": register.title_field,
                "controls": {k: list(v) for k, v in register.controls.items()},
                "fields": [{"key": f.key, "label": f.label, "type": f.type, "isRequired": f.is_required,
                            "options": [{"value": v, "label": label} for v, label in f.options], "help": f.help}
                           for f in register.fields],
                "deadlines": [{"key": d.key, "label": d.label, "framework": d.framework} for d in register.deadlines],
                "hasExamples": bool(register.examples),
            },
            "records": [_payload(register, row, names, now) for row in rows],
            "advice": _advice(register, CompanyProfileManager().get_for(user_id)),
            "templates": [{"key": item.key, "title": item.title} for item in load_templates()
                          if item.register == register_key],
        }

    def create_record(self, user_id: int, register_key: str, values: dict) -> dict:
        """Crea una ficha.

        Args:
            user_id: Usuario que la crea; la ficha es de su dueño efectivo.
            register_key: Tipo de registro.
            values: ``{campo: texto}``.

        Returns:
            dict: La ficha creada.

        Raises:
            RegisterNotFoundError: Si no hay tipo con esa clave (404).
            RecordInvalidError: Si no cumple la definición (400).
        """
        register = _register(register_key)
        clean = _checked(register, values)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        now = utcnow_naive()
        with UnitOfWork() as uow:
            row = EunomiaRecord(
                owner_user_id=owner_user_id, register_key=register_key, register_version=register.version,
                values=clean, created_at=now, created_by_user_id=user_id, updated_at=now, updated_by_user_id=user_id)
            EunomiaRecordRepository(uow).save(row)
            EunomiaRecordEventRepository(uow).save(EunomiaRecordEvent(
                record_id=row.id, owner_user_id=owner_user_id, actor_user_id=user_id,
                actor_name=display_name(user_id) or "", occurred_at=now,
                changes={key: {"from": None, "to": value} for key, value in clean.items()}))
            payload = _payload(register, row, {user_id: display_name(user_id)}, now)
        logger.info("Ficha creada | owner=%s registro=%s id=%s", owner_user_id, register_key, payload["id"])
        return payload

    def create_examples(self, user_id: int, register_key: str) -> list[dict]:
        """Crea las fichas de ejemplo que ofrece la definición del registro.

        Args:
            user_id: Usuario que las pide.
            register_key: Tipo de registro.

        Returns:
            list[dict]: Las fichas creadas; vacía si el tipo no trae ejemplos.

        Raises:
            RegisterNotFoundError: Si no hay tipo con esa clave (404).
        """
        register = _register(register_key)
        return [self.create_record(user_id, register_key, dict(example)) for example in register.examples]

    def update_record(self, user_id: int, register_key: str, record_id: int, values: dict,
                      expected_updated_at: Optional[datetime]) -> dict:
        """Cambia los valores de una ficha, con concurrencia optimista.

        Args:
            user_id: Usuario que edita.
            register_key: Tipo de registro.
            record_id: Clave primaria de la ficha.
            values: ``{campo: texto}`` completos: sustituyen a los anteriores.
            expected_updated_at: El ``updatedAt`` que vio el cliente.

        Returns:
            dict: La ficha guardada.

        Raises:
            RegisterNotFoundError: Si no hay tipo con esa clave (404).
            RecordNotFoundError: Si la ficha no existe o es de otro dueño (404).
            RecordInvalidError: Si no cumple la definición (400).
            RecordConflictError: Si alguien la cambió desde que el cliente la leyó (409).
        """
        register = _register(register_key)
        clean = _checked(register, values)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        expected = _naive_utc(expected_updated_at)
        now = utcnow_naive()
        with UnitOfWork() as uow:
            repo = EunomiaRecordRepository(uow)
            row = repo.get_for_owner(owner_user_id, register_key, record_id)
            if row is None:
                raise RecordNotFoundError(str(record_id))
            if row.updated_at != expected:
                raise RecordConflictError(_payload(register, row, _names([row]), now) | {
                    "createdAt": row.created_at.isoformat(), "updatedAt": row.updated_at.isoformat(),
                    "deadlines": []})
            before = dict(row.values)
            changes = {key: {"from": before.get(key), "to": clean.get(key)}
                       for key in set(before) | set(clean) if before.get(key) != clean.get(key)}
            if not changes:
                return _payload(register, row, _names([row]), now)
            if not repo.update_if_unchanged(row.id, expected, values=clean, updated_at=now, updated_by_user_id=user_id,
                                            register_version=register.version):
                raise RecordConflictError(None)
            EunomiaRecordEventRepository(uow).save(EunomiaRecordEvent(
                record_id=row.id, owner_user_id=owner_user_id, actor_user_id=user_id,
                actor_name=display_name(user_id) or "", occurred_at=now, changes=changes))
            uow.session.refresh(row)
            return _payload(register, row, _names([row]), now)

    def set_archived(self, user_id: int, register_key: str, record_id: int, is_archived: bool) -> dict:
        """Archiva o restaura una ficha: no se borra, conserva su historial.

        Args:
            user_id: Usuario que lo hace.
            register_key: Tipo de registro.
            record_id: Clave primaria de la ficha.
            is_archived: ``True`` para archivar, ``False`` para restaurar.

        Returns:
            dict: La ficha.

        Raises:
            RegisterNotFoundError: Si no hay tipo con esa clave (404).
            RecordNotFoundError: Si la ficha no existe o es de otro dueño (404).
        """
        register = _register(register_key)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        now = utcnow_naive()
        with UnitOfWork() as uow:
            row = EunomiaRecordRepository(uow).get_for_owner(owner_user_id, register_key, record_id)
            if row is None:
                raise RecordNotFoundError(str(record_id))
            if row.is_archived != is_archived:
                EunomiaRecordEventRepository(uow).save(EunomiaRecordEvent(
                    record_id=row.id, owner_user_id=owner_user_id, actor_user_id=user_id,
                    actor_name=display_name(user_id) or "", occurred_at=now,
                    changes={"isArchived": {"from": row.is_archived, "to": is_archived}}))
                row.is_archived = is_archived
                row.updated_at, row.updated_by_user_id = now, user_id
            return _payload(register, row, _names([row]), now)

    def get_history(self, user_id: int, register_key: str, record_id: int) -> list[dict]:
        """El historial de una ficha, del cambio más reciente al más antiguo.

        Args:
            user_id: Usuario que pregunta.
            register_key: Tipo de registro.
            record_id: Clave primaria de la ficha.

        Returns:
            list[dict]: ``actorName``, ``occurredAt`` y ``changes``.

        Raises:
            RecordNotFoundError: Si la ficha no existe o es de otro dueño (404).
        """
        _register(register_key)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        if build_repository(EunomiaRecordRepository).get_for_owner(owner_user_id, register_key, record_id) is None:
            raise RecordNotFoundError(str(record_id))
        return [{"actorName": event.actor_name, "occurredAt": event.occurred_at, "changes": event.changes}
                for event in build_repository(EunomiaRecordEventRepository).list_for_record(record_id)]

    def export(self, user_id: int, register_key: str, file_format: str) -> tuple[bytes, str, str]:
        """Exporta las fichas no archivadas de un registro.

        Args:
            user_id: Usuario que exporta.
            register_key: Tipo de registro.
            file_format: ``"csv"`` o ``"pdf"``.

        Returns:
            tuple[bytes, str, str]: Contenido, nombre de descarga y tipo MIME.

        Raises:
            RegisterNotFoundError: Si no hay tipo con esa clave (404).
        """
        register = _register(register_key)
        data = self.get_register(user_id, register_key)
        stamp = utcnow_naive().strftime("%Y%m%d")
        if file_format == "csv":
            return build_csv(register, data["records"]), f"{register_key}-{stamp}.csv", "text/csv"
        profile = CompanyProfileManager().get_for(user_id)
        address = ", ".join(part for part in (profile.get("addressLine"), profile.get("postalCode"),
                                              profile.get("city")) if part)
        pdf = RegisterPDF(register=register, records=data["records"], company_name=profile.get("legalName") or "",
                          company_details=[("NIF:", profile.get("taxId") or ""), ("Domicilio:", address),
                                           ("Contacto:", profile.get("securityContact") or "")],
                          author=display_name(user_id) or "Ellysia Security Team").generate()
        return pdf, f"{register_key}-{stamp}.pdf", "application/pdf"
