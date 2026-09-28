"""
Custom exceptions for the Iris email header analysis module.

Hierarchy:
    IrisError (EllysiaException)
    ├── IrisAnalysisNotFoundError   (404)
    ├── IrisAnalysisNotReadyError   (409)
    ├── IrisExecutionError          (500)
    └── IrisInvalidStateError       (400)
"""

from __future__ import annotations

from src.modules.shared._exceptions import EllysiaException, EntityNotFoundError, ErrorCode


class IrisError(EllysiaException):
    """Base exception for all Iris module errors."""
    default_code = ErrorCode.UNKNOWN_ERROR
    default_status_code = 500


class IrisAnalysisNotFoundError(EntityNotFoundError, IrisError):
    """Raised when an analysis ID does not exist or is not owned by the user.

    This also serves as a privacy layer — the same error is returned
    whether the analysis does not exist or belongs to another user.
    """
    entity_label = "Análisis"
    id_field = "analysis_id"


class IrisAnalysisNotReadyError(IrisError):
    """Raised when trying to read results of an unfinished analysis."""
    default_code = ErrorCode.ENTITY_NOT_FOUND
    default_status_code = 409

    def __init__(self, analysis_id: int, status: str) -> None:
        super().__init__(f"Analysis {analysis_id} is not ready (status: {status})")


class IrisRawMessagePurgedError(IrisError):
    """El raw de este análisis ya no existe -- lo purgó la política de
    retención, que conserva el resultado analítico
    (score/veredicto/reglas) pero no el contenido del correo indefinidamente.

    410 Gone y no 404: el análisis existe de verdad y su resultado sigue
    siendo consultable por otras vías (``GET /iris/results/<id>``); es
    específicamente el raw, y solo el raw, lo que ha dejado de estar --
    para siempre, no temporalmente, que es justo la diferencia entre 410 y
    404/503.
    """
    default_code = ErrorCode.ENTITY_NOT_FOUND
    default_status_code = 410

    def __init__(self, analysis_id: int) -> None:
        super().__init__(
            f"El raw del análisis {analysis_id} ya no está disponible: "
            "la política de retención lo ha purgado."
        )


class IrisExecutionError(IrisError):
    """Raised when an analysis fails to start or complete."""
    default_code = ErrorCode.SCAN_ERROR
    default_status_code = 500


class IrisInvalidStateError(IrisError):
    """Raised when an operation is attempted in the wrong lifecycle state.

    For example, cancelling an analysis that is already finished.
    """
    default_code = ErrorCode.SCAN_ERROR
    default_status_code = 400


class IrisInvalidInputError(IrisError):
    """Raised when the submitted headers do not contain enough valid entries
    to perform a meaningful analysis."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400


class IrisMailboxConnectionNotFoundError(EntityNotFoundError, IrisError):
    """Raised when a mailbox connection id does not exist or is not owned
    by the user (same error for both, prevents ID enumeration)."""
    entity_label = "Conexión de buzón"
    entity_is_feminine = True
    id_field = "connection_id"


class IrisTrustedSenderNotFoundError(EntityNotFoundError, IrisError):
    """La excepción de confianza no existe o no es del usuario.

    El mismo error para los dos casos, como el resto de entidades de Iris,
    para que no se puedan enumerar ids ajenos.
    """
    entity_label = "Excepción de confianza"
    entity_is_feminine = True
    id_field = "trusted_sender_id"


class IrisSavedViewNotFoundError(EntityNotFoundError, IrisError):
    """La vista guardada no existe o no es del usuario (mismo error para los dos)."""
    entity_label = "Vista guardada"
    entity_is_feminine = True
    id_field = "view_id"


class IrisCaseNotFoundError(EntityNotFoundError, IrisError):
    """El caso no existe o no es del usuario (mismo error para los dos)."""
    entity_label = "Caso"
    id_field = "case_id"


class IrisCampaignNotFoundError(EntityNotFoundError, IrisError):
    """La campaña no existe o no es del usuario (mismo error para los dos)."""
    entity_label = "Campaña"
    entity_is_feminine = True
    id_field = "campaign_id"


class IrisIndicatorNotFoundError(EntityNotFoundError, IrisError):
    """El indicador no aparece en ningún análisis del usuario.

    Iris solo consulta fuera lo que el usuario ya vio en su correo; lo demás
    responde igual que si no existiera.
    """
    entity_label = "Indicador"
    id_field = "indicator"


class IrisAnalysisUrlNotFoundError(EntityNotFoundError, IrisError):
    """La URL no es de ese análisis (o el análisis no es del usuario).

    Solo se sigue una URL que aparece en un correo del usuario: Iris no es un
    servicio para visitar URLs arbitrarias.
    """
    entity_label = "Enlace"
    id_field = "url"


class IrisBatchNotFoundError(EntityNotFoundError, IrisError):
    """El lote no existe o no es del usuario (mismo error para los dos)."""
    entity_label = "Lote"
    id_field = "batch_id"


class IrisBatchBackpressureError(IrisError):
    """El lote llenaría la cola: el usuario ya tiene demasiados análisis en curso.

    429 y no 400: la petición es válida, pero ahora no se puede atender;
    reenviarla cuando terminen los análisis en marcha funciona.
    """
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 429

    def __init__(self, active: int, requested: int, limit: int) -> None:
        message = (
            f"Tienes {active} análisis en marcha y el lote añadiría {requested}; el máximo a la vez "
            f"es {limit}. Espera a que terminen y vuelve a enviarlo: no se ha creado nada."
        )
        super().__init__(
            message,
            user_message=message,
            message_key="irisBatchBackpressure",
            params={"active": active, "requested": requested, "limit": limit},
        )


class IrisMailboxInvalidProviderError(IrisError):
    """Raised when connecting to an unsupported mailbox provider."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, provider: str) -> None:
        super().__init__(f"Unsupported mailbox provider: {provider}")


class IrisMailboxQuotaExceededError(IrisError):
    """Raised when a user tries to connect more mailboxes than iris.maxConnectionsPerUser."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400


class IrisMailboxOAuthStateError(IrisError):
    """Raised when the OAuth callback's `state` fails to verify — expired,
    tampered, or never issued by start_connect (CSRF protection)."""
    default_code = ErrorCode.AUTHENTICATION_ERROR
    default_status_code = 400


class IrisMailboxInvalidFolderError(IrisError):
    """Raised when ``folder`` doesn't match any real folder/label the
    provider returns for this account — wrong id, typo, or a value
    that belongs to another provider."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self, folder: str) -> None:
        super().__init__(
            f"'{folder}' no es una carpeta válida para esta cuenta.",
            user_message=f"«{folder}» no es una carpeta válida para esta cuenta.",
            message_key="irisMailboxInvalidFolder",
            params={"folder": folder},
        )


class IrisNotInOrganizationError(IrisError):
    """El usuario no pertenece a ninguna organización con la que compartir inteligencia."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="El usuario no pertenece a ninguna organizacion",
            user_message="No perteneces a ninguna organización.",
            message_key="irisNotInOrganization",
        )


class IrisWebhookSubscriptionNotFoundError(EntityNotFoundError, IrisError):
    """El webhook no existe o no es del usuario (mismo error para los dos)."""
    entity_label = "Webhook"
    id_field = "subscription_id"


class IrisWebhookDeliveryNotFoundError(EntityNotFoundError, IrisError):
    """La entrega no existe o no es de ese webhook del usuario (mismo error para los dos)."""
    entity_label = "Entrega"
    entity_is_feminine = True
    id_field = "delivery_id"


class IrisWebhookLimitReachedError(IrisError):
    """El usuario ya tiene tantos webhooks como permite la instalación."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 409

    def __init__(self, limit: int) -> None:
        super().__init__(
            message=f"Limite de {limit} webhooks por usuario alcanzado",
            user_message=f"Ya tienes {limit} webhooks, el máximo. Borra uno para dar de alta otro.",
            message_key="irisWebhookLimitReached",
            params={"limit": limit},
        )


class IrisWebhookInactiveError(IrisError):
    """El webhook está desactivado: no se le puede enviar nada hasta reactivarlo."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="El webhook esta desactivado",
            user_message="Este webhook está desactivado. Actívalo antes de enviarle eventos.",
            message_key="irisWebhookInactive",
        )


class IrisWebhookDeliveryInProgressError(IrisError):
    """La entrega todavía está pendiente o enviándose: reenviarla no tiene sentido aún."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="La entrega sigue pendiente o en curso",
            user_message="Esta entrega todavía está en curso; se podrá reenviar cuando termine.",
            message_key="irisWebhookDeliveryInProgress",
        )


class IrisIntegrationTokenNotFoundError(EntityNotFoundError, IrisError):
    """El token de integración no existe o no es del usuario (mismo error para los dos)."""
    entity_label = "Token de integración"
    id_field = "token_id"


class IrisInvalidIntegrationTokenError(IrisError):
    """El token de integración falta, está mal formado, no existe, está revocado o caducó.

    Una sola respuesta para todos los casos, a propósito: distinguir «no
    existe» de «secreto incorrecto» permitiría averiguar qué ``key_id`` son
    válidos probando.
    """
    default_code = ErrorCode.AUTHENTICATION_ERROR
    default_status_code = 401

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            message=f"Token de integracion rechazado{f': {reason}' if reason else ''}",
            user_message="El token de integración no es válido, está revocado o ha caducado.",
            message_key="irisInvalidIntegrationToken",
        )


class IrisIntegrationTokenLimitReachedError(IrisError):
    """El usuario ya tiene tantos tokens vigentes como permite la instalación."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 409

    def __init__(self, limit: int) -> None:
        super().__init__(
            message=f"Limite de {limit} tokens de integracion vigentes alcanzado",
            user_message=f"Ya tienes {limit} tokens de integración vigentes, el máximo. Revoca uno para crear otro.",
            message_key="irisIntegrationTokenLimitReached",
            params={"limit": limit},
        )


class IrisMailboxReauthRequiredError(IrisError):
    """El proveedor ya no acepta la autorización del buzón: hay que volver a conectarlo."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="La conexion de buzon necesita reautorizacion",
            user_message="Este buzón necesita que lo vuelvas a conectar antes de poder actuar sobre él.",
            message_key="irisMailboxReauthRequired",
        )


class IrisMailboxActionNotFoundError(EntityNotFoundError, IrisError):
    """La acción sobre el buzón no existe o no la hizo el usuario (mismo error para los dos)."""
    entity_label = "Acción"
    entity_is_feminine = True
    id_field = "action_id"


#: Por qué no se puede actuar sobre el correo de un análisis: texto para el
#: usuario y clave de su plantilla, por motivo.
_UNAVAILABLE_REASONS = {
    "not_from_mailbox": ("Este correo no llegó por un buzón conectado, así que Iris no puede actuar sobre él.",
                         "irisMailboxActionNotFromMailbox"),
    "connection_gone": ("El buzón por el que llegó este correo ya no está conectado.",
                        "irisMailboxActionConnectionGone"),
    "missing_scope": ("Este buzón se conectó en solo lectura. Vuelve a conectarlo con las acciones activadas.",
                      "irisMailboxActionMissingScope"),
}


class IrisMailboxActionUnavailableError(IrisError):
    """No se puede actuar sobre el correo de este análisis, por un motivo estable."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self, reason: str) -> None:
        """Construye el error.

        Args:
            reason: ``not_from_mailbox``, ``connection_gone`` o ``missing_scope``.
        """
        user_message, message_key = _UNAVAILABLE_REASONS[reason]
        super().__init__(
            message=f"Accion sobre el buzon no disponible: {reason}",
            user_message=user_message,
            message_key=message_key,
        )
        self.reason = reason


class IrisMailboxActionConfirmationRequiredError(IrisError):
    """Una acción que saca el correo de la bandeja se pidió sin confirmarla."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(self) -> None:
        super().__init__(
            message="La accion saca el correo de la bandeja y no se confirmo",
            user_message="Esta acción saca el correo de tu bandeja: confírmala para hacerla.",
            message_key="irisMailboxActionConfirmationRequired",
        )


class IrisMailboxActionInProgressError(IrisError):
    """Ya hay una acción en curso sobre este correo; hay que esperar a que termine."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="Ya hay una accion en curso sobre este correo",
            user_message="Ya hay una acción en curso sobre este correo. Espera a que termine.",
            message_key="irisMailboxActionInProgress",
        )


class IrisMailboxActionNotReversibleError(IrisError):
    """La acción no se puede deshacer: no se llegó a aplicar, ya se deshizo o es ella misma un deshacer."""
    default_code = ErrorCode.CONSTRAINT_VIOLATION
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="La accion no se puede deshacer en su estado actual",
            user_message="Esta acción no se puede deshacer: no llegó a aplicarse o ya se deshizo.",
            message_key="irisMailboxActionNotReversible",
        )


class IrisMailboxEventRejectedError(IrisError):
    """Un aviso de correo nuevo que no trae el secreto que prueba de dónde viene.

    Lo ve el servicio del proveedor, no una persona; la respuesta no dice qué
    falló para no ayudar a quien pruebe secretos.
    """
    default_code = ErrorCode.AUTHENTICATION_ERROR
    default_status_code = 401

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            message=f"Aviso de buzon rechazado{f': {reason}' if reason else ''}",
            user_message="Aviso rechazado.",
            message_key="irisMailboxEventRejected",
        )


class IrisTenantOwnerRequiredError(IrisError):
    """Solo el dueño de la organización decide si se comparte inteligencia y qué se protege."""
    default_code = ErrorCode.AUTHORIZATION_ERROR
    default_status_code = 403

    def __init__(self) -> None:
        super().__init__(
            message="Solo el duenyo de la organizacion cambia la politica de inteligencia de Iris",
            user_message="Solo el dueño de la organización puede cambiar esto.",
            message_key="irisTenantOwnerRequired",
        )
