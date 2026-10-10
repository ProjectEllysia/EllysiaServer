"""
EunomiaDocumentManager — los documentos de cumplimiento generados en segundo plano.

Pedir un documento valida la plantilla y los campos obligatorios en el acto, consume una unidad de
la cuota ``eunomia.documents`` del dueño efectivo, registra la fila en ``pending`` y encola la
generación en ``eunomia.report``. El worker lo compone en PDF o en Word, lo escribe en el
directorio de salida de Eunomia y lo deja en ``done`` o ``error``. Los documentos son del dueño
efectivo: los miembros de su organización los ven y los descargan.
"""

import logging
import os
import re
from datetime import date
from typing import Tuple

import src.modules.system.config_reading as CR
from src.modules.accounts import CompanyProfileManager, LimitKey, OrganizationManager, QuotaManager
from src.modules.infrastructure import UnitOfWork
from src.modules.shared._documents import (
    DocumentManager,
    run_report_generation,
    submit_report_generation,
)
from src.modules.shared._exceptions import DocumentNotFoundError, DocumentNotReadyError
from src.modules.system.taskqueue import TaskQueue, job_context

from ..exceptions import EunomiaError, TemplateIncompleteError, TemplateNotFoundError
from ..model import EunomiaDocument
from ..repositories import EunomiaDocumentRepository
from ..services.documents import missing_required, render_document
from ..services.documents.docx import build_docx
from ..services.documents.pdf import EunomiaTemplatePDF, decode_logo
from ..services.templates import get_template
from .assessments import display_name
from .templates import EunomiaTemplateManager

logger = logging.getLogger(__name__)

FORMATS = ("pdf", "docx")

_MIMETYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

#: Tiempo máximo del trabajo de generación, en segundos.
_JOB_TIMEOUT_SECONDS = 300


def _owner_of(user_id: int) -> int:
    """El dueño efectivo de los datos de un usuario."""
    return OrganizationManager().resolve_data_owner(user_id)


def _download_name(title: str, file_format: str) -> str:
    """Nombre de descarga: el título sin acentos ni signos, y la fecha."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))).strip("-")
    return f"{slug or 'documento'}-{date.today().isoformat()}.{file_format}"


def _write_file(document_id: int, content: bytes, file_format: str) -> str:
    """Escribe el documento en el directorio de salida; el nombre en disco lleva solo el id."""
    directory = CR.verify_directory(CR.DirectoryType.OUTPUT_EUNOMIA)
    path = directory / f"eunomia-document-{document_id}.{file_format}"
    path.write_bytes(content)
    return str(path)


def _compose(document: EunomiaDocument, owner_user_id: int) -> bytes:
    """Compone el fichero de un documento con los valores guardados al pedirlo."""
    template = get_template(document.template_key, document.template_version)
    if template is None:
        raise EunomiaError(message=f"La plantilla {document.template_key}@{document.template_version} ya no existe")
    values = dict(document.values)
    profile = CompanyProfileManager().get_for(owner_user_id)
    options = {
        "document": render_document(template, values),
        "company_name": profile.get("legalName") or values.get("company_name", ""),
        "tax_id": profile.get("taxId") or values.get("tax_id", ""),
        "framework_label": template.framework.upper(),
        "logo": decode_logo(profile.get("brandLogo")),
    }
    if document.format == "docx":
        return build_docx(**options)
    return EunomiaTemplatePDF(**options).generate()


def _run_document_generation(document_id: int) -> None:
    """Cuerpo del trabajo que genera un documento de Eunomia.

    Lo marca ``running``, lo compone, guarda el fichero y su nombre de descarga y deja el estado
    final en ``done`` o ``error`` mediante ``run_report_generation``, que relanza el error para que
    el trabajo figure como fallido en la cola. Un documento borrado antes de empezar no hace nada.

    Args:
        document_id: Clave primaria del ``EunomiaDocument``.
    """
    with UnitOfWork() as uow:
        document = EunomiaDocumentRepository(uow).get_by_id(document_id)
        if document is None:
            logger.warning("Documento Eunomia %s borrado antes de generarse", document_id)
            return
        document.status = "running"
        owner_user_id, title, file_format = document.user_id, document.title, document.format

    def render() -> str:
        """Compone el fichero, guarda su nombre de descarga y devuelve su ruta."""
        with UnitOfWork() as uow:
            current = EunomiaDocumentRepository(uow).get_by_id(document_id)
            content = _compose(current, owner_user_id)
        path = _write_file(document_id, content, file_format)
        with UnitOfWork() as uow:
            generated = EunomiaDocumentRepository(uow).get_by_id(document_id)
            if generated is not None:
                generated.download_name = _download_name(title, file_format)
        return path

    run_report_generation(document_id, EunomiaDocumentRepository, render)


class EunomiaDocumentManager(DocumentManager):
    """Documentos de Eunomia y su ciclo de vida.

    Todas las operaciones reciben el usuario que actúa y trabajan sobre los documentos de su
    dueño efectivo.

    Attributes:
        EXTERNAL_ID_PREFIX: Prefijo del ``external_id`` de sus trabajos (``eunomia-doc:``).
        TASK_CATEGORY: Categoría de TaskQueue (``eunomia.report``).
    """

    EXTERNAL_ID_PREFIX = "eunomia-doc:"
    TASK_CATEGORY = "eunomia.report"

    _REPOSITORY = EunomiaDocumentRepository
    _NOT_FOUND_ERROR = DocumentNotFoundError

    def create_document(self, user_id: int, template_key: str, file_format: str) -> dict:
        """Pide un documento: valida, consume cuota, registra y encola.

        Args:
            user_id: Usuario que lo pide; el documento es de su dueño efectivo.
            template_key: Identificador de la plantilla.
            file_format: ``"pdf"`` o ``"docx"``.

        Returns:
            dict: El documento recién creado en ``pending`` (``EunomiaDocument.to_dict``).

        Raises:
            TemplateNotFoundError: Si no hay plantilla con esa clave (404).
            TemplateIncompleteError: Si falta algún campo obligatorio (400).
            QuotaExceededError: Si el dueño agotó ``eunomia.documents`` este periodo (402).
        """
        template = get_template(template_key)
        if template is None:
            raise TemplateNotFoundError(template_key)
        draft = EunomiaTemplateManager().get_draft(user_id, template_key)
        values = {item["key"]: item["value"] for item in draft["fields"]}
        missing = missing_required(template, values)
        if missing:
            raise TemplateIncompleteError([template.field(key).label for key in missing])

        owner_user_id = _owner_of(user_id)
        QuotaManager().consume(owner_user_id, LimitKey.EUNOMIA_DOCUMENTS)
        with UnitOfWork() as uow:
            document = EunomiaDocument(
                document_type="eunomia", filename="", format=file_format, status="pending", is_ai_generated=0,
                user_id=owner_user_id, template_key=template.key, template_version=template.version,
                title=template.title, values=values, requested_by_name=display_name(user_id) or "",
            )
            EunomiaDocumentRepository(uow).save(document)
            uow.commit_for_handoff()
            serialized = document.to_dict()

        submit_report_generation(
            self._task_queue, serialized["id"], EunomiaDocumentRepository,
            func=EunomiaDocumentManager.execute_document_generation, args=(serialized["id"],),
            name=f"EunomiaDocument-{serialized['id']}", category=self.TASK_CATEGORY,
            external_id=self.external_id_for(serialized["id"]), timeout=_JOB_TIMEOUT_SECONDS,
        )
        return serialized

    def list_documents(self, user_id: int, page: int, per_page: int) -> Tuple[list, int]:
        """Una página de los documentos del dueño efectivo, más recientes primero.

        Args:
            user_id: Usuario que pregunta; ve los documentos de su dueño efectivo.
            page: Página, desde 1.
            per_page: Documentos por página.

        Returns:
            Tuple[list, int]: Los documentos como diccionarios y el total.
        """
        documents, total = self.get_documents_for_user_paginated(_owner_of(user_id), page, per_page)
        return [item.to_dict() for item in documents], total

    def get_document(self, user_id: int, document_id: int) -> dict:
        """Un documento del dueño efectivo.

        Args:
            user_id: Usuario que pregunta.
            document_id: Clave primaria del documento.

        Raises:
            DocumentNotFoundError: Si no existe o es de otro dueño (404).
        """
        return self.assert_document_ownership(document_id, _owner_of(user_id)).to_dict()

    def get_document_file(self, user_id: int, document_id: int) -> Tuple[str, str, str]:
        """Dónde está el fichero de un documento listo y cómo se descarga.

        Args:
            user_id: Usuario que descarga.
            document_id: Clave primaria del documento.

        Returns:
            Tuple[str, str, str]: Ruta en disco, nombre de descarga y tipo MIME.

        Raises:
            DocumentNotFoundError: Si no existe o es de otro dueño (404).
            DocumentNotReadyError: Si aún no está en ``done`` o su fichero ya no está (409).
        """
        document = self.assert_document_ownership(document_id, _owner_of(user_id))
        if document.status != "done" or not document.filename or not os.path.exists(document.filename):
            raise DocumentNotReadyError(document_id, document.status)
        return (document.filename, document.download_name or os.path.basename(document.filename),
                _MIMETYPES.get(document.format, "application/octet-stream"))

    def delete_user_document(self, user_id: int, document_id: int) -> None:
        """Borra un documento del dueño efectivo y su fichero.

        Args:
            user_id: Usuario que borra.
            document_id: Clave primaria del documento.

        Raises:
            DocumentNotFoundError: Si no existe o es de otro dueño (404).
        """
        self.assert_document_ownership(document_id, _owner_of(user_id))
        self.delete_document(document_id)

    @staticmethod
    def execute_document_generation(document_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            document_id: Clave primaria del ``EunomiaDocument`` a generar.
        """
        with job_context():
            _run_document_generation(document_id)

    @classmethod
    def reconcile_orphaned_documents(cls) -> int:
        """Marca como ``error`` los documentos que ya nadie va a terminar.

        Se llama una vez al arrancar la API: un trabajo que sigue en la cola o corre en un worker
        vivo se respeta (``TaskQueue.is_recoverable``).

        Returns:
            int: Documentos marcados como ``error``.
        """
        task_queue = TaskQueue.get_instance()
        manager = cls(task_queue=task_queue)
        fixed = 0
        with UnitOfWork() as uow:
            for document in EunomiaDocumentRepository(uow).get_unfinished_documents():
                if task_queue.is_recoverable(manager.external_id_for(document.id), cls.TASK_CATEGORY):
                    continue
                document.status = "error"
                fixed += 1
        return fixed
