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
from .managers import CatalogManager, EunomiaFrameworkManager
from .schemas import (
    AdoptionCreateSchema,
    AdoptionListSchema,
    AdoptionSchema,
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
