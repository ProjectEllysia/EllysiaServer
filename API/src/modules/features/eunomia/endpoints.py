"""
Endpoints del módulo Eunomia.

Este fichero solo hace autenticación y validación de schema: toda la lógica vive en
``managers/``, y el acceso a datos, únicamente vía ``UnitOfWork`` + repositorio.

El blueprint se sirve bajo ``/eunomia``. Ese prefijo está dado de alta en el matcher
``@api`` de ``web/Caddyfile`` y en el proxy de ``web/app/vite.config.js``; una página
del SPA que cuelgue de él tiene que declararse además en ``@spa_bajo_prefijo_api`` y en
``FRONTEND_SUBROUTES``, o al recargarla la recibiría Flask.
"""

import io
import logging
from datetime import date

from flask import request, send_file
from flask_smorest import Blueprint as SmorestBlueprint

import src.modules.system.config_reading as CR
from src.modules.shared import handle_exceptions, limiter
from src.modules.shared.schemas import ErrorSchema
from src.modules.users import AttributeType, get_current_user, require_attributes, require_oauth_token

from .exceptions import EunomiaError, EvidenceFileMissingError
from .managers import (
    CatalogManager,
    EunomiaAssessmentManager,
    EunomiaDocumentManager,
    EunomiaEvidenceManager,
    EunomiaFrameworkManager,
    EunomiaTemplateManager,
)
from .schemas import (
    AdoptionCreateSchema,
    AdoptionListSchema,
    AdoptedTreeSchema,
    AdoptionSchema,
    AssessmentHistorySchema,
    AssessmentSchema,
    SummarySchema,
    AssessmentWriteSchema,
    RemovalPreviewSchema,
    UpgradePlanSchema,
    TemplateDraftSchema,
    TemplateDraftWriteSchema,
    TemplateListSchema,
    DocumentListSchema,
    DocumentRequestSchema,
    DocumentSchema,
    DocumentsQuerySchema,
    CatalogFrameworkListSchema,
    CatalogVersionSchema,
    EvidenceLinkSchema,
    EvidenceListSchema,
    EvidenceSchema,
    EvidenceUpdateSchema,
)

eunomia_blp = SmorestBlueprint(
    "eunomia", __name__,
    description="Marcos de cumplimiento normativo: catálogo de controles, evaluación y evidencias (Eunomia)",
)
logger = logging.getLogger(__name__)


@eunomia_blp.get("/frameworks")
@eunomia_blp.response(200, CatalogFrameworkListSchema, description="Marcos del catálogo")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def list_frameworks():
    """El catálogo resumido: cada marco con sus versiones y la vigente"""
    return {"frameworks": CatalogManager().list_frameworks()}


@eunomia_blp.get("/frameworks/<string:key>/<string:version>")
@eunomia_blp.response(200, CatalogVersionSchema, description="Árbol de una versión de un marco")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework or version not found")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def get_framework_version(key, version):
    """El árbol de controles de una versión de un marco"""
    return CatalogManager().get_version(key, version)


@eunomia_blp.get("/adoptions")
@eunomia_blp.response(200, AdoptionListSchema, description="Marcos adoptados del dueño efectivo")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Insufficient permissions")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def list_adoptions():
    """Los marcos que tiene adoptados el dueño efectivo de los datos, con su versión"""
    return EunomiaFrameworkManager().list_adoptions(get_current_user().id)


@eunomia_blp.post("/adoptions")
@eunomia_blp.arguments(AdoptionCreateSchema)
@eunomia_blp.response(201, AdoptionSchema, description="Marco adoptado")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(402, schema=ErrorSchema, description="Plan limit reached")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Members cannot adopt frameworks")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not found")
@eunomia_blp.alt_response(409, schema=ErrorSchema, description="Already adopted, or archived")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_CREATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def adopt_framework(data):
    """Adoptar un marco fijando la versión vigente del catálogo"""
    return EunomiaFrameworkManager().adopt(get_current_user().id, data["frameworkKey"]), 201


@eunomia_blp.get("/adoptions/<string:key>/upgrade-preview")
@eunomia_blp.response(200, UpgradePlanSchema, description="Qué pasaría al pasar el marco a la versión vigente")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Members cannot upgrade frameworks")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@eunomia_blp.alt_response(409, schema=ErrorSchema, description="Already current, or no version mapping")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def preview_framework_upgrade(key):
    """Qué se traslada, qué se revisa y qué se pierde al pasar un marco a la versión vigente"""
    return EunomiaFrameworkManager().upgrade_preview(get_current_user().id, key)


@eunomia_blp.post("/adoptions/<string:key>/upgrade")
@eunomia_blp.response(200, UpgradePlanSchema, description="Marco pasado a la versión vigente")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Members cannot upgrade frameworks")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@eunomia_blp.alt_response(409, schema=ErrorSchema, description="Already current, or no version mapping")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def upgrade_framework(key):
    """Pasar un marco a la versión vigente trasladando evaluaciones y enlaces"""
    return EunomiaFrameworkManager().upgrade(get_current_user().id, key)


@eunomia_blp.get("/adoptions/<string:key>/removal-preview")
@eunomia_blp.response(200, RemovalPreviewSchema, description="Lo que se perdería al quitar el marco")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Members cannot remove frameworks")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_DELETE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def preview_framework_removal(key):
    """Qué evaluaciones y evidencias se perderían al quitar un marco, y cuáles se conservan"""
    return EunomiaFrameworkManager().removal_preview(get_current_user().id, key)


@eunomia_blp.delete("/adoptions/<string:key>")
@eunomia_blp.response(200, AdoptionSchema, description="Marco archivado")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Members cannot remove frameworks")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_DELETE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def archive_framework(key):
    """Quitar un marco: se archiva y se puede restaurar hasta que pase el plazo"""
    return EunomiaFrameworkManager().archive(get_current_user().id, key)


@eunomia_blp.post("/adoptions/<string:key>/restore")
@eunomia_blp.response(200, AdoptionSchema, description="Marco restaurado")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(402, schema=ErrorSchema, description="Plan limit reached")
@eunomia_blp.alt_response(403, schema=ErrorSchema, description="Members cannot restore frameworks")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@eunomia_blp.alt_response(409, schema=ErrorSchema, description="Not archived, or the period expired")
@limiter.limit("30 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def restore_framework(key):
    """Reactivar un marco archivado si sigue en plazo"""
    return EunomiaFrameworkManager().restore(get_current_user().id, key)


@eunomia_blp.get("/adoptions/<string:key>/tree")
@eunomia_blp.response(200, AdoptedTreeSchema, description="Árbol del marco adoptado con sus evaluaciones")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def get_adopted_tree(key):
    """El árbol de la versión adoptada de un marco, con la evaluación de cada control"""
    return EunomiaAssessmentManager().get_tree(get_current_user().id, key)


@eunomia_blp.get("/adoptions/<string:key>/summary")
@eunomia_blp.response(200, SummarySchema, description="Resumen de cumplimiento del marco")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def get_adopted_summary(key):
    """Cuánto falta de un marco: global, por rama, vencimientos próximos y controles sin responsable"""
    summary = EunomiaAssessmentManager().get_summary(get_current_user().id, key)
    return {**summary, "overall": summary["global"]}


@eunomia_blp.get("/adoptions/<string:key>/history/<path:identifier>")
@eunomia_blp.response(200, AssessmentHistorySchema, description="Historial de cambios del control")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted or control not found")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def get_assessment_history(key, identifier):
    """Quién cambió qué y cuándo en la evaluación de un control"""
    return {"events": EunomiaAssessmentManager().get_history(get_current_user().id, key, identifier)}


@eunomia_blp.put("/adoptions/<string:key>/controls/<path:identifier>")
@eunomia_blp.arguments(AssessmentWriteSchema)
@eunomia_blp.response(200, AssessmentSchema, description="Evaluación guardada")
@eunomia_blp.alt_response(400, schema=ErrorSchema, description="Invalid assessment")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Framework not adopted or control not found")
@eunomia_blp.alt_response(409, schema=ErrorSchema, description="The control changed meanwhile")
@limiter.limit("300 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def assess_control(data, key, identifier):
    """Evaluar un control de un marco adoptado; el dueño y los miembros escriben sobre lo mismo"""
    return EunomiaAssessmentManager().set_assessment(get_current_user().id, key, identifier, data)


# ── Evidencias ────────────────────────────────────────────────────────────

@eunomia_blp.get("/evidence")
@eunomia_blp.response(200, EvidenceListSchema, description="Evidencias del dueño efectivo")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def list_evidence():
    """Las evidencias del dueño efectivo de los datos, con los controles que demuestran"""
    manager = EunomiaEvidenceManager()
    user_id = get_current_user().id
    return {"evidence": manager.list_evidence(user_id), "usage": manager.usage(user_id)}


@eunomia_blp.post("/evidence")
@eunomia_blp.response(201, EvidenceSchema, description="Evidencia subida")
@eunomia_blp.alt_response(400, schema=ErrorSchema, description="Missing file or type not allowed")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(413, schema=ErrorSchema, description="File too large")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_CREATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def upload_evidence():
    """Subir un fichero como evidencia (multipart: file, title, description, validUntil)"""
    manager = EunomiaEvidenceManager()
    manager.assert_room_for(get_current_user().id, request.content_length or 0)
    upload = request.files.get("file")
    content = upload.stream.read(CR.eunomia_config().max_evidence_bytes + 1) if upload else None
    valid_until = request.form.get("validUntil") or None
    try:
        parsed_valid_until = date.fromisoformat(valid_until) if valid_until else None
    except ValueError as exc:
        raise EvidenceFileMissingError() from exc
    payload = manager.upload(
        get_current_user().id, upload.filename if upload else "", content,
        request.form.get("title", ""), request.form.get("description", ""), parsed_valid_until,
    )
    return payload, 201


@eunomia_blp.get("/evidence/<int:evidence_id>/download")
@eunomia_blp.response(200, description="El fichero de la evidencia")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Evidence not found")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def download_evidence(evidence_id):
    """Descargar una evidencia; siempre como adjunto, nunca para abrirse en la propia página"""
    filename, content_type, content = EunomiaEvidenceManager().get_content(get_current_user().id, evidence_id)
    response = send_file(io.BytesIO(content), mimetype=content_type, as_attachment=True, download_name=filename)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@eunomia_blp.patch("/evidence/<int:evidence_id>")
@eunomia_blp.arguments(EvidenceUpdateSchema)
@eunomia_blp.response(200, EvidenceSchema, description="Evidencia actualizada")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Evidence not found")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def update_evidence(data, evidence_id):
    """Cambiar el título, la descripción o la validez de una evidencia"""
    return EunomiaEvidenceManager().update(get_current_user().id, evidence_id, data)


@eunomia_blp.delete("/evidence/<int:evidence_id>")
@eunomia_blp.response(204, description="Evidencia borrada")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Evidence not found")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_DELETE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def delete_evidence(evidence_id):
    """Borrar una evidencia con su contenido y sus enlaces"""
    EunomiaEvidenceManager().delete(get_current_user().id, evidence_id)
    return "", 204


@eunomia_blp.post("/evidence/<int:evidence_id>/links")
@eunomia_blp.arguments(EvidenceLinkSchema)
@eunomia_blp.response(200, EvidenceSchema, description="Evidencia enlazada")
@eunomia_blp.alt_response(400, schema=ErrorSchema, description="The control is a group")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Evidence, framework or control not found")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def link_evidence(data, evidence_id):
    """Enlazar una evidencia con un control de un marco adoptado"""
    return EunomiaEvidenceManager().link(
        get_current_user().id, evidence_id, data["frameworkKey"], data["controlIdentifier"])


@eunomia_blp.delete("/evidence/<int:evidence_id>/links/<string:framework>/<path:identifier>")
@eunomia_blp.response(200, EvidenceSchema, description="Enlace quitado")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Evidence not found")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def unlink_evidence(evidence_id, framework, identifier):
    """Quitar el enlace entre una evidencia y un control; la evidencia sigue existiendo"""
    return EunomiaEvidenceManager().unlink(get_current_user().id, evidence_id, framework, identifier)


@eunomia_blp.get("/templates")
@eunomia_blp.response(200, TemplateListSchema, description="Plantillas de documentos disponibles")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def list_templates():
    """Las plantillas de documentos, con el marco al que sirven y si ya hay borrador"""
    return {"templates": EunomiaTemplateManager().list_templates(get_current_user().id)}


@eunomia_blp.get("/templates/<string:key>/draft")
@eunomia_blp.response(200, TemplateDraftSchema, description="Formulario con valores guardados y precargados")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Template not found")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def get_template_draft(key):
    """El formulario de una plantilla: lo guardado combinado con lo que Ellysia ya sabe"""
    return EunomiaTemplateManager().get_draft(get_current_user().id, key)


@eunomia_blp.put("/templates/<string:key>/draft")
@eunomia_blp.arguments(TemplateDraftWriteSchema)
@eunomia_blp.response(200, TemplateDraftSchema, description="Borrador guardado")
@eunomia_blp.alt_response(400, schema=ErrorSchema, description="Invalid value")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Template not found")
@limiter.limit("240 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_UPDATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def save_template_draft(data, key):
    """Guardar lo escrito en el formulario de una plantilla"""
    return EunomiaTemplateManager().save_draft(get_current_user().id, key, data["values"])


@eunomia_blp.post("/templates/<string:key>/documents")
@eunomia_blp.arguments(DocumentRequestSchema)
@eunomia_blp.response(202, DocumentSchema, description="Documento en cola")
@eunomia_blp.alt_response(400, schema=ErrorSchema, description="Required fields missing")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(402, schema=ErrorSchema, description="Document quota exhausted")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Template not found")
@limiter.limit("60 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_CREATE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def create_document(data, key):
    """Pedir el documento de una plantilla, en PDF o en Word, en segundo plano"""
    return EunomiaDocumentManager().create_document(get_current_user().id, key, data["format"])


@eunomia_blp.get("/documents")
@eunomia_blp.arguments(DocumentsQuerySchema, location="query")
@eunomia_blp.response(200, DocumentListSchema, description="Documentos del dueño efectivo")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def list_documents(args):
    """Los documentos generados, más recientes primero"""
    documents, total = EunomiaDocumentManager().list_documents(get_current_user().id, args["page"], args["perPage"])
    return {"documents": documents, "total": total, "page": args["page"], "perPage": args["perPage"]}


@eunomia_blp.get("/documents/<int:document_id>")
@eunomia_blp.response(200, DocumentSchema, description="Documento")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Document not found")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def get_document(document_id):
    """Consultar un documento y su estado"""
    return EunomiaDocumentManager().get_document(get_current_user().id, document_id)


@eunomia_blp.get("/documents/<int:document_id>/download")
@eunomia_blp.response(200, description="Fichero del documento")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Document not found")
@eunomia_blp.alt_response(409, schema=ErrorSchema, description="Document not ready")
@limiter.limit("600 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_READ])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def download_document(document_id):
    """Descargar el fichero de un documento ya generado"""
    path, download_name, mimetype = EunomiaDocumentManager().get_document_file(get_current_user().id, document_id)
    return send_file(path, mimetype=mimetype, as_attachment=True, download_name=download_name)


@eunomia_blp.delete("/documents/<int:document_id>")
@eunomia_blp.response(200, description="Documento eliminado")
@eunomia_blp.alt_response(401, schema=ErrorSchema, description="Not authenticated")
@eunomia_blp.alt_response(404, schema=ErrorSchema, description="Document not found")
@limiter.limit("120 per hour")
@require_oauth_token
@require_attributes(at_least_one=[AttributeType.EUNOMIA_DELETE])
@handle_exceptions(default_exception=EunomiaError, logger=logger)
def delete_document(document_id):
    """Borrar un documento y su fichero"""
    EunomiaDocumentManager().delete_user_document(get_current_user().id, document_id)
    return {"message": "Documento eliminado correctamente", "documentId": document_id}
