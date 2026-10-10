"""
Endpoints del módulo Eunomia.

Este fichero solo hace autenticación y validación de schema: toda la lógica vive en
``managers/``, y el acceso a datos, únicamente vía ``UnitOfWork`` + repositorio.

El blueprint se sirve bajo ``/eunomia``. Ese prefijo está dado de alta en el matcher
``@api`` de ``web/Caddyfile`` y en el proxy de ``web/app/vite.config.js``; una página
del SPA que cuelgue de él tiene que declararse además en ``@spa_bajo_prefijo_api`` y en
``FRONTEND_SUBROUTES``, o al recargarla la recibiría Flask.
"""

import logging

from flask_smorest import Blueprint as SmorestBlueprint

from src.modules.shared import handle_exceptions, limiter
from src.modules.shared.schemas import ErrorSchema
from src.modules.users import AttributeType, get_current_user, require_attributes, require_oauth_token

from .exceptions import EunomiaError
from .managers import CatalogManager, EunomiaAssessmentManager, EunomiaFrameworkManager
from .schemas import (
    AdoptionCreateSchema,
    AdoptionListSchema,
    AdoptedTreeSchema,
    AdoptionSchema,
    AssessmentHistorySchema,
    AssessmentSchema,
    AssessmentWriteSchema,
    RemovalPreviewSchema,
    CatalogFrameworkListSchema,
    CatalogVersionSchema,
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
