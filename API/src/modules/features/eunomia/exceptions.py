"""
Excepciones específicas del módulo Eunomia.

Hierarchy:
    EunomiaError (EllysiaException)
    ├── FrameworkNotFoundError    (404)
    ├── FrameworkAlreadyAdoptedError (409)
    ├── FrameworkArchivedError    (409)
    └── AdoptionNotFoundError     (404)
"""

from __future__ import annotations

from src.modules.shared._exceptions import EllysiaException, EntityNotFoundError, ErrorCode


class EunomiaError(EllysiaException):
    """Excepción base para todos los errores del módulo Eunomia."""
    default_code = ErrorCode.UNKNOWN_ERROR
    default_status_code = 500


class FrameworkNotFoundError(EntityNotFoundError, EunomiaError):
    """El catálogo no tiene ese marco, o no tiene esa versión de él."""

    entity_label = "Marco de cumplimiento"
    id_field = "framework"


class FrameworkAlreadyAdoptedError(EunomiaError):
    """El marco ya está adoptado y activo."""

    default_code = ErrorCode.ENTITY_ALREADY_EXISTS
    default_status_code = 409

    def __init__(self, framework_key: str) -> None:
        super().__init__(
            message=f"El marco '{framework_key}' ya esta adoptado",
            user_message=f"El marco «{framework_key}» ya está adoptado.",
            message_key="frameworkAlreadyAdopted",
            params={"framework": framework_key},
        )


class FrameworkArchivedError(EunomiaError):
    """El marco está archivado: en vez de empezar de cero se ofrece restaurarlo."""

    default_code = ErrorCode.ENTITY_ALREADY_EXISTS
    default_status_code = 409

    def __init__(self, framework_key: str) -> None:
        super().__init__(
            message=f"El marco '{framework_key}' esta archivado",
            user_message=(
                f"El marco «{framework_key}» está archivado. Puedes restaurarlo y recuperar "
                f"lo que habías evaluado."
            ),
            message_key="frameworkArchived",
            params={"framework": framework_key},
        )


class AdoptionNotFoundError(EntityNotFoundError, EunomiaError):
    """El dueño no tiene adoptado ese marco."""

    entity_label = "Adopción"
    entity_is_feminine = True
    id_field = "framework"
