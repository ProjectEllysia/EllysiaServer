"""
EunomiaTemplateManager — los borradores de documentos del dueño efectivo de los datos.

El formulario de una plantilla llega ya relleno con lo que Ellysia sabe (el perfil de empresa y
las evaluaciones del dueño efectivo) y con lo que alguien escribió antes. El dueño y los miembros
de su organización rellenan el mismo borrador, igual que las evaluaciones.
"""

import logging
from datetime import date, datetime
from typing import Optional

from src.modules.accounts import CompanyProfileManager, OrganizationManager
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive

from ..exceptions import RecordNotFoundError, TemplateNotFoundError, TemplateValuesInvalidError
from ..model import ADOPTION_ACTIVE, EunomiaTemplateDraft
from ..repositories import (
    EunomiaControlAssessmentRepository,
    EunomiaFrameworkAdoptionRepository,
    EunomiaRecordRepository,
    EunomiaTemplateDraftRepository,
)
from ..services.registers import FIELD_DATE as REGISTER_DATE
from ..services.registers import FIELD_DATETIME, FIELD_SELECT, RegisterType, get_register
from ..services.templates import (
    FIELD_DATE,
    SOURCE_RECORD,
    SOURCE_TODAY,
    DocumentTemplate,
    TemplateField,
    get_template,
    load_templates,
)
from .assessments import display_name

logger = logging.getLogger(__name__)

#: Longitud máxima del valor de un campo; evita borradores con megabytes de texto.
MAX_VALUE_LENGTH = 20_000

ORIGIN_SAVED = "saved"
ORIGIN_COMPANY = "company"
ORIGIN_ASSESSMENT = "assessment"
ORIGIN_RECORD = "record"
ORIGIN_DEFAULT = "default"
ORIGIN_EMPTY = "empty"


def _record_text(register: RegisterType, key: str, value: str) -> str:
    """Un valor de una ficha tal como se lee en un documento: fechas legibles y etiquetas de opción."""
    field = register.field(key)
    if field is None or not value:
        return value
    try:
        if field.type == FIELD_DATETIME:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
        if field.type == REGISTER_DATE:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value
    if field.type == FIELD_SELECT:
        return dict(field.options).get(value, value)
    return value


def _prefilled(field: TemplateField, framework: str, owner_user_id: int, company: dict,
               record: Optional[dict] = None) -> Optional[tuple[str, str]]:
    """El valor con el que Ellysia precarga un campo y de dónde sale.

    Args:
        field: El campo de la plantilla.
        framework: Marco de la plantilla, contra el que se buscan las evaluaciones.
        owner_user_id: Dueño efectivo de los datos.
        company: El perfil de empresa del dueño efectivo, tal como lo da ``CompanyProfileManager``.
        record: Los valores ya legibles de la ficha de la que se genera el documento, o ``None``.

    Returns:
        Optional[tuple[str, str]]: ``(valor, origen)``; ``None`` si no hay nada que precargar.
    """
    source = field.source
    if source is None:
        return (field.default, ORIGIN_DEFAULT) if field.default else None
    if source == SOURCE_TODAY:
        return date.today().isoformat(), ORIGIN_DEFAULT
    if source.startswith(SOURCE_RECORD):
        value = (record or {}).get(source[len(SOURCE_RECORD):])
        return (value, ORIGIN_RECORD) if value else None
    if source.startswith("company."):
        value = company.get(source[len("company."):])
        return (str(value), ORIGIN_COMPANY) if value not in (None, "") else None
    control, _, datum = source[len("assessment."):].rpartition(".")
    return _assessment_value(owner_user_id, framework, control, datum)


def _assessment_value(owner_user_id: int, framework: str, control: str, datum: str) -> Optional[tuple[str, str]]:
    """El responsable o la fecha límite de la evaluación de un control, si existe."""
    row = build_repository(EunomiaControlAssessmentRepository).get_for_control(owner_user_id, framework, control)
    if row is None:
        return None
    if datum == "responsible":
        name = display_name(row.responsible_user_id)
        return (name, ORIGIN_ASSESSMENT) if name else None
    return (row.due_date.isoformat(), ORIGIN_ASSESSMENT) if row.due_date else None


def _validate_values(template: DocumentTemplate, values: dict) -> dict[str, str]:
    """Comprueba los valores que llegan y devuelve solo los que traen texto.

    Raises:
        TemplateValuesInvalidError: Si hay un campo desconocido, un valor que no es texto o
            demasiado largo, o una fecha que no es ``AAAA-MM-DD``.
    """
    clean: dict[str, str] = {}
    for key, value in values.items():
        field = template.field(key)
        if field is None or not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH:
            raise TemplateValuesInvalidError(key)
        if field.type == FIELD_DATE and value:
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise TemplateValuesInvalidError(key) from error
        if value.strip():
            clean[key] = value
    return clean


def resolve_values(template: DocumentTemplate, owner_user_id: int, saved: dict, company: dict,
                   record: Optional[dict] = None) -> list[dict]:
    """Combina lo guardado con lo precargado: un valor guardado gana a la precarga.

    Args:
        template: La plantilla.
        owner_user_id: Dueño efectivo de los datos.
        saved: ``{campo: texto}`` del borrador del dueño.
        company: El perfil de empresa del dueño efectivo.
        record: Valores legibles de la ficha de origen; un valor de la ficha gana a uno guardado,
            porque el borrador guardado es de la plantilla y no de este incidente. ``None`` si el
            documento no sale de una ficha.

    Returns:
        list[dict]: Un elemento por campo, en el orden de la plantilla: ``key``, ``label``,
            ``type``, ``isRequired``, ``help``, ``source``, ``value`` y ``origin``
            (``saved``, ``company``, ``assessment``, ``default`` o ``empty``).
    """
    resolved = []
    for field in template.fields:
        from_record = _prefilled(field, template.framework, owner_user_id, company, record) \
            if record is not None and (field.source or "").startswith(SOURCE_RECORD) else None
        if from_record is not None:
            value, origin = from_record
        elif saved.get(field.key, "").strip():
            value, origin = saved[field.key], ORIGIN_SAVED
        else:
            value, origin = _prefilled(field, template.framework, owner_user_id, company, record) or ("", ORIGIN_EMPTY)
        resolved.append({
            "key": field.key, "label": field.label, "type": field.type, "isRequired": field.is_required,
            "help": field.help, "source": field.source, "value": value, "origin": origin,
        })
    return resolved


class EunomiaTemplateManager:
    """Plantillas de documentos y sus borradores."""

    def list_templates(self, user_id: int) -> list[dict]:
        """Las plantillas disponibles, con si el marco está adoptado y si hay borrador.

        Args:
            user_id: Usuario que pregunta; ve lo del dueño efectivo.

        Returns:
            list[dict]: ``key``, ``version``, ``framework``, ``title``, ``summary``, ``controls``,
                ``isFrameworkAdopted`` y ``hasDraft``.
        """
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        adopted = {row.framework_key for row in
                   build_repository(EunomiaFrameworkAdoptionRepository).list_for_owner(owner_user_id)
                   if row.status == ADOPTION_ACTIVE}
        drafts = {row.template_key for row in
                  build_repository(EunomiaTemplateDraftRepository).list_for_owner(owner_user_id)}
        latest: dict[str, DocumentTemplate] = {}
        for template in sorted(load_templates(), key=lambda item: int(item.version)):
            latest[template.key] = template
        return [{
            "key": item.key, "version": item.version, "framework": item.framework, "title": item.title,
            "summary": item.summary, "controls": list(item.controls),
            "isFrameworkAdopted": item.framework in adopted, "hasDraft": item.key in drafts,
        } for item in latest.values()]

    def get_draft(self, user_id: int, template_key: str, record_id: Optional[int] = None) -> dict:
        """El formulario de una plantilla con los valores guardados y los precargados.

        Args:
            user_id: Usuario que pregunta; ve lo del dueño efectivo.
            template_key: Identificador de la plantilla.
            record_id: Ficha de un registro de la que toma datos la plantilla (``record.<campo>``).
                Por defecto ``None``: sin ficha, esos campos salen vacíos.

        Returns:
            dict: ``template`` (``key``, ``version``, ``title``, ``summary``, ``framework``),
                ``fields`` (ver ``resolve_values``), ``missingRequired`` (claves obligatorias
                sin valor), ``updatedAt`` y ``updatedByName`` del borrador (``None`` si aún no
                hay).

        Raises:
            TemplateNotFoundError: Si no hay plantilla con esa clave (404).
            RecordNotFoundError: Si ``record_id`` no es una ficha del dueño efectivo (404).
        """
        template = get_template(template_key)
        if template is None:
            raise TemplateNotFoundError(template_key)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        draft = build_repository(EunomiaTemplateDraftRepository).get_for_owner(owner_user_id, template_key)
        company = CompanyProfileManager().get_for(user_id)
        record = None
        if record_id is not None and template.register:
            row = build_repository(EunomiaRecordRepository).get_for_owner(owner_user_id, template.register, record_id)
            if row is None:
                raise RecordNotFoundError(str(record_id))
            register = get_register(template.register)
            record = {key: _record_text(register, key, value) for key, value in dict(row.values).items()}
        fields = resolve_values(template, owner_user_id, dict(draft.values) if draft else {}, company, record)
        return {
            "template": {"key": template.key, "version": template.version, "title": template.title,
                         "summary": template.summary, "framework": template.framework},
            "fields": fields,
            "missingRequired": [item["key"] for item in fields if item["isRequired"] and not item["value"].strip()],
            "updatedAt": draft.updated_at if draft else None,
            "updatedByName": display_name(draft.updated_by_user_id) if draft else None,
        }

    def save_draft(self, user_id: int, template_key: str, values: dict) -> dict:
        """Guarda lo que el usuario escribió en el formulario.

        Sustituye el borrador entero: los campos que no vienen (o vienen vacíos) dejan de estar
        guardados y vuelven a precargarse.

        Args:
            user_id: Usuario que escribe; el borrador es del dueño efectivo.
            template_key: Identificador de la plantilla.
            values: ``{campo: texto}``; las fechas en ``AAAA-MM-DD``.

        Returns:
            dict: Lo mismo que ``get_draft``.

        Raises:
            TemplateNotFoundError: Si no hay plantilla con esa clave (404).
            TemplateValuesInvalidError: Si algún valor no es válido (400).
        """
        template = get_template(template_key)
        if template is None:
            raise TemplateNotFoundError(template_key)
        clean = _validate_values(template, values)
        owner_user_id = OrganizationManager().resolve_data_owner(user_id)
        with UnitOfWork() as uow:
            repo = EunomiaTemplateDraftRepository(uow)
            draft = repo.get_for_owner(owner_user_id, template_key)
            if draft is None:
                draft = EunomiaTemplateDraft(owner_user_id=owner_user_id, template_key=template_key)
            draft.template_version = template.version
            draft.values = clean
            draft.updated_at = utcnow_naive()
            draft.updated_by_user_id = user_id
            repo.save(draft)
        logger.info("Borrador guardado | owner=%s plantilla=%s campos=%s", owner_user_id, template_key, len(clean))
        return self.get_draft(user_id, template_key)
