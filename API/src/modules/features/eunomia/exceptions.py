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
    ├── AssessmentConflictError   (409)
    ├── EvidenceNotFoundError     (404)
    ├── EvidenceFileMissingError  (400)
    ├── EvidenceTooLargeError     (413)
    ├── EvidenceStorageFullError  (402)
    ├── EvidenceTypeNotAllowedError (400)
    ├── EvidenceTypeMismatchError (400)
    └── EvidenceActiveContentError (400)
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


class EvidenceNotFoundError(EntityNotFoundError, EunomiaError):
    """La evidencia no existe, o no es del dueño efectivo del usuario.

    El mismo error en los dos casos: distinguirlos permitiría enumerar evidencias ajenas.
    """

    entity_label = "Evidencia"
    entity_is_feminine = True
    id_field = "evidence_id"


class EvidenceFileMissingError(EunomiaError):
    """La petición de subida no trae ningún fichero."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self) -> None:
        super().__init__(
            message="La subida no incluye ningun fichero",
            user_message="Elige un fichero para subirlo como evidencia.",
            message_key="evidenceFileMissing",
        )


class EvidenceTooLargeError(EunomiaError):
    """El fichero supera el tamaño máximo de una evidencia."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 413

    def __init__(self, max_megabytes: int) -> None:
        super().__init__(
            message=f"La evidencia supera el maximo de {max_megabytes} MB",
            user_message=f"El fichero supera el máximo de {max_megabytes} MB por evidencia.",
            message_key="evidenceTooLarge",
            params={"maxMegabytes": max_megabytes},
        )


class EvidenceStorageFullError(EunomiaError):
    """La subida superaría el almacenamiento de evidencias que da el plan del dueño.

    402 y no 413: se arregla con espacio (borrando evidencias o subiendo de plan), no
    achicando el fichero. Las cifras van en megabytes, que es lo que el usuario entiende.
    """

    default_code = ErrorCode.PLAN_LIMIT_REACHED
    default_status_code = 402

    def __init__(self, used_megabytes: int, limit_megabytes: int) -> None:
        super().__init__(
            message=f"Almacenamiento de evidencias agotado: {used_megabytes}/{limit_megabytes} MB",
            user_message=(
                f"Tu plan incluye {limit_megabytes} MB de evidencias y ya usas {used_megabytes} MB. "
                f"Borra alguna o amplía tu plan para subir más."
            ),
            message_key="evidenceStorageFull",
            params={"usedMegabytes": used_megabytes, "limitMegabytes": limit_megabytes},
        )


class EvidenceTypeNotAllowedError(EunomiaError):
    """El tipo de fichero no está entre los admitidos como evidencia."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, extension: str, allowed: str) -> None:
        super().__init__(
            message=f"Tipo de evidencia no admitido: '{extension}'",
            user_message=f"El tipo de fichero «{extension}» no se admite como evidencia. Admitidos: {allowed}.",
            message_key="evidenceTypeNotAllowed",
            params={"extension": extension, "allowed": allowed},
        )


class EvidenceTypeMismatchError(EunomiaError):
    """El contenido no es del tipo que dice su extensión (un ejecutable renombrado a ``.pdf``)."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, extension: str) -> None:
        super().__init__(
            message=f"El contenido no corresponde a la extension '{extension}'",
            user_message=f"El contenido del fichero no es un «{extension}» de verdad, aunque se llame así.",
            message_key="evidenceTypeMismatch",
            params={"extension": extension},
        )


class EvidenceActiveContentError(EunomiaError):
    """El fichero lleva contenido activo que se ejecutaría al abrirlo (macros, JavaScript…)."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(
            message=f"Evidencia con contenido activo: {detail}",
            user_message=(
                f"El fichero lleva contenido que se ejecutaría al abrirlo y no se admite como "
                f"evidencia: {detail}"
            ),
            message_key="evidenceActiveContent",
            params={"detail": detail},
        )


class FrameworkUpToDateError(EunomiaError):
    """El marco ya está en la versión vigente del catálogo."""

    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self, framework_key: str) -> None:
        super().__init__(
            message=f"El marco '{framework_key}' ya está en la versión vigente",
            user_message=f"El marco «{framework_key}» ya está en la versión vigente del catálogo.",
            message_key="frameworkUpToDate",
            params={"framework": framework_key},
        )


class VersionMappingMissingError(EunomiaError):
    """No hay correspondencias publicadas entre la versión adoptada y la vigente."""

    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self, framework_key: str, from_version: str, to_version: str) -> None:
        super().__init__(
            message=f"Sin correspondencias de '{framework_key}' entre {from_version} y {to_version}",
            user_message=(
                f"No hay correspondencias entre las versiones {from_version} y {to_version} del marco "
                f"«{framework_key}», así que no se puede trasladar tu evaluación automáticamente."
            ),
            message_key="versionMappingMissing",
            params={"framework": framework_key, "fromVersion": from_version, "toVersion": to_version},
        )


class TemplateNotFoundError(EntityNotFoundError, EunomiaError):
    """El catálogo de plantillas no tiene ninguna con esa clave."""

    entity_label = "Plantilla"
    entity_is_feminine = True
    id_field = "template"


class TemplateValuesInvalidError(EunomiaError):
    """Los valores de un borrador traen un campo que la plantilla no tiene o un valor mal formado."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, field_key: str) -> None:
        super().__init__(
            message=f"Valor no válido para el campo '{field_key}'",
            user_message=f"El valor del campo «{field_key}» no es válido para esta plantilla.",
            message_key="templateValueInvalid",
            params={"field": field_key},
        )


class TemplateIncompleteError(EunomiaError):
    """Faltan campos obligatorios de la plantilla: no se genera un documento a medias."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, labels: list[str]) -> None:
        joined = ", ".join(labels)
        super().__init__(
            message=f"Faltan campos obligatorios de la plantilla: {joined}",
            user_message=f"Para generar el documento falta completar: {joined}.",
            message_key="templateIncomplete",
            params={"fields": joined},
            details={"fields": labels},
        )


class RegisterNotFoundError(EntityNotFoundError, EunomiaError):
    """No hay ningún tipo de registro con esa clave."""

    entity_label = "Registro"
    id_field = "register"


class RecordNotFoundError(EntityNotFoundError, EunomiaError):
    """La ficha no existe, o no es del dueño efectivo del usuario (el mismo error en los dos casos)."""

    entity_label = "Ficha"
    entity_is_feminine = True
    id_field = "record"


class RecordInvalidError(EunomiaError):
    """La ficha no cumple la definición del registro."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, fields: list[str], labels: list[str]) -> None:
        joined = ", ".join(labels)
        super().__init__(
            message=f"La ficha no cumple la definición del registro: {', '.join(fields)}",
            user_message=f"Revisa estos campos: {joined}.",
            message_key="recordInvalid",
            params={"fields": joined},
            details={"fields": fields},
        )


class RecordConflictError(EunomiaError):
    """Alguien cambió la ficha entre que se leyó y se guardó; lleva su valor actual."""

    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409
    expose_details = True

    def __init__(self, current: dict | None) -> None:
        super().__init__(
            message="La ficha cambio mientras se editaba",
            user_message="Otra persona ha cambiado esta ficha mientras la editabas. Revisa su valor actual.",
            message_key="recordConflict",
            details={"current": current},
        )
