"""
Excepciones específicas del módulo Eunomia.

Hierarchy:
    EunomiaError (EllysiaException)
    ├── FrameworkNotFoundError    (404)
    ├── FrameworkAlreadyAdoptedError (409)
    ├── FrameworkArchivedError    (409)
    ├── FrameworkNotArchivedError (409)
    ├── FrameworkRestoreExpiredError (409)
    ├── AdoptionNotFoundError     (404)
    ├── ControlNotFoundError      (404)
    ├── ControlNotAssessableError (400)
    ├── JustificationRequiredError (400)
    ├── ResponsibleNotInOrganizationError (400)
    └── AssessmentConflictError   (409)
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


class FrameworkNotArchivedError(EunomiaError):
    """Se intenta restaurar o purgar un marco que no está archivado."""

    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self, framework_key: str) -> None:
        super().__init__(
            message=f"El marco '{framework_key}' no esta archivado",
            user_message=f"El marco «{framework_key}» no está archivado.",
            message_key="frameworkNotArchived",
            params={"framework": framework_key},
        )


class FrameworkRestoreExpiredError(EunomiaError):
    """El marco archivado ya pasó el plazo de recuperación."""

    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self, framework_key: str) -> None:
        super().__init__(
            message=f"El plazo para restaurar el marco '{framework_key}' ha vencido",
            user_message=(
                f"El plazo para restaurar el marco «{framework_key}» ha vencido. "
                f"Puedes adoptarlo de nuevo, pero empezarás de cero."
            ),
            message_key="frameworkRestoreExpired",
            params={"framework": framework_key},
        )


class AdoptionNotFoundError(EntityNotFoundError, EunomiaError):
    """El dueño no tiene adoptado ese marco."""

    entity_label = "Adopción"
    entity_is_feminine = True
    id_field = "framework"


class ControlNotFoundError(EntityNotFoundError, EunomiaError):
    """El control no existe en la versión del marco que el dueño tiene adoptada."""

    entity_label = "Control"
    id_field = "control"


class ControlNotAssessableError(EunomiaError):
    """El nodo es un grupo: no se evalúa, agrega el estado de sus hijos."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, identifier: str) -> None:
        super().__init__(
            message=f"El nodo '{identifier}' no es evaluable",
            user_message=f"«{identifier}» agrupa otros controles y no se evalúa directamente.",
            message_key="controlNotAssessable",
            params={"control": identifier},
        )


class JustificationRequiredError(EunomiaError):
    """«No aplica» sin justificación: una exclusión sin motivo no se sostiene ante una auditoría."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self) -> None:
        super().__init__(
            message="Un control 'no aplica' necesita justificacion",
            user_message="Para marcar un control como «no aplica» tienes que explicar por qué.",
            message_key="justificationRequired",
        )


class ResponsibleNotInOrganizationError(EunomiaError):
    """El responsable no es el dueño ni un miembro de su organización."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self) -> None:
        super().__init__(
            message="El responsable no pertenece a la organizacion",
            user_message="El responsable tiene que ser el dueño de la organización o uno de sus miembros.",
            message_key="responsibleNotInOrganization",
        )


class AssessmentConflictError(EunomiaError):
    """Alguien cambió el control entre que se leyó y se guardó.

    Lleva en ``details`` el valor actual, para que el cliente lo enseñe y la persona decida.
    """

    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409
    expose_details = True

    def __init__(self, current: dict | None) -> None:
        super().__init__(
            message="La evaluacion cambio mientras se editaba",
            user_message="Otra persona ha cambiado este control mientras lo editabas. Revisa su valor actual.",
            message_key="assessmentConflict",
            details={"current": current},
        )
