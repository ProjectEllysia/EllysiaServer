"""Excepciones del módulo de sistema: lectura de logs y cola de tareas."""

from src.modules.shared._exceptions import (
    EllysiaException,
    EntityNotFoundError,
    ErrorCode,
    ErrorSeverity,
)


class LogNotFoundError(EllysiaException):
    """El handler de logging todavía no ha creado el fichero."""

    default_code = ErrorCode.ENTITY_NOT_FOUND
    default_status_code = 404
    default_severity = ErrorSeverity.LOW
    error_name = "log_not_found"

    def __init__(self, message: str = "El fichero de log todavía no existe"):
        """Construye el error.

        Args:
            message: Detalle para el log. Por defecto, que el fichero aún no
                existe.
        """
        super().__init__(
            message=message,
            user_message="No hay ningún log disponible en este momento.",
            message_key="logNotFound",
        )


class LogSnapshotChangedError(EllysiaException):
    """El fichero fue reemplazado o truncado durante una consulta paginada."""

    default_code = ErrorCode.ILLEGAL_STATE_ERROR
    default_status_code = 409
    default_severity = ErrorSeverity.LOW
    error_name = "log_changed"

    def __init__(self, message: str = "El fichero de log cambió durante la consulta"):
        """Construye el error.

        Args:
            message: Qué cambió, para el log. Por defecto, un texto genérico.
        """
        super().__init__(
            message=message,
            user_message="El log cambió durante la consulta. Inicia una nueva lectura.",
            message_key="logChanged",
        )


class LogQueryError(EllysiaException):
    """Los filtros solicitados son incompatibles o no son válidos.

    El texto es libre (dice qué filtro falla), así que no lleva clave de
    mensaje: la interfaz lo enseña tal cual. Lo ve quien opera el despliegue
    desde la vista de logs.
    """

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400
    default_severity = ErrorSeverity.LOW
    error_name = "invalid_log_query"

    def __init__(self, message: str):
        """Construye el error.

        Args:
            message: Qué filtro no es válido, en castellano; es a la vez el
                texto técnico y el del usuario.
        """
        super().__init__(message=message, user_message=message)


class TaskNotFoundError(EntityNotFoundError):
    """No existe ninguna tarea con ese identificador en la cola."""

    error_name = "not_found"
    entity_label = "Tarea"
    entity_is_feminine = True
    id_field = "task_id"


class TaskNotCancellableError(EllysiaException):
    """La tarea que se quiere cancelar no existe o ya ha terminado.

    La cola no distingue los dos casos al cancelar, así que el mensaje tampoco.
    """

    default_code = ErrorCode.ENTITY_NOT_FOUND
    default_status_code = 404
    default_severity = ErrorSeverity.LOW
    error_name = "not_found"

    def __init__(self, task_id: str):
        """Construye el error.

        Args:
            task_id: Identificador de la tarea; solo va al log.
        """
        super().__init__(
            message=f"La tarea {task_id} no existe o ya ha terminado",
            user_message="La tarea no existe o ya ha terminado.",
            message_key="taskNotCancellable",
        )
