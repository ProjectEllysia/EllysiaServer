"""
Endpoints del módulo Eunomia.

Este fichero solo hace autenticación y validación de schema: toda la lógica vive en
``managers/``, y el acceso a datos, únicamente vía ``UnitOfWork`` + repositorio.

El blueprint se sirve bajo ``/eunomia``. Ese prefijo está dado de alta en el matcher
``@api`` de ``web/Caddyfile`` y en el proxy de ``web/app/vite.config.js``; una página
del SPA que cuelgue de él tiene que declararse además en ``@spa_bajo_prefijo_api`` y en
``FRONTEND_SUBROUTES``, o al recargarla la recibiría Flask.
"""

from flask_smorest import Blueprint as SmorestBlueprint

eunomia_blp = SmorestBlueprint(
    "eunomia", __name__,
    description="Marcos de cumplimiento normativo: catálogo de controles, evaluación y evidencias (Eunomia)",
)
