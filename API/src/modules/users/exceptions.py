from typing import Optional

from src.modules.shared._exceptions import (
    EllysiaException,
    EntityNotFoundError,
    ErrorCode,
    ErrorSeverity,
    SurfaceDisabledError,
    DatabaseError,  # noqa: F401  — re-exportada: users/managers.py la importa desde aquí
)


class AuthenticationError(EllysiaException):
    default_code = ErrorCode.AUTHENTICATION_ERROR
    default_status_code = 401
    default_severity = ErrorSeverity.MEDIUM

    def __init__(self, message: str = "Error de autenticación", **kwargs):
        if "user_message" not in kwargs:
            kwargs["user_message"] = "No se pudo verificar tu identidad."
        super().__init__(message=message, **kwargs)


class AuthorizationError(EllysiaException):
    default_code = ErrorCode.AUTHORIZATION_ERROR
    default_status_code = 403
    default_severity = ErrorSeverity.MEDIUM

    def __init__(self, message: str = "Error de autorización", **kwargs):
        if "user_message" not in kwargs:
            kwargs["user_message"] = "No tienes permisos para realizar esta acción."
        super().__init__(message=message, **kwargs)


class PermissionsError(AuthorizationError):
    default_code = ErrorCode.AUTHORIZATION_ERROR

    def __init__(self, message: str = "Permisos insuficientes", **kwargs):
        if "user_message" not in kwargs:
            kwargs["user_message"] = message
        super().__init__(message=message, **kwargs)


class InvalidCredentialsError(AuthenticationError):
    default_code = ErrorCode.INVALID_CREDENTIALS

    def __init__(self):
        super().__init__(
            message="Credenciales inválidas",
            user_message="Usuario o contraseña incorrectos.",
            message_key="invalidCredentials"
        )


class PasswordChangedError(AuthenticationError):
    """La sesión/token quedó obsoleto porque la contraseña de acceso cambió.

    Se distingue de ``InvalidCredentialsError`` para que el cliente pueda mostrar
    una pantalla dedicada ("tu contraseña ha cambiado; inicia sesión de nuevo")
    en lugar de un error genérico. Se identifica por ``code == 1609``.
    """
    default_code = ErrorCode.PASSWORD_CHANGED
    error_name = "password_changed"

    def __init__(self):
        super().__init__(
            message="La contraseña fue cambiada; el token/sesión ya no es válido",
            user_message="Tu contraseña ha cambiado. Inicia sesión de nuevo.",
            message_key="passwordChanged",
        )


class InvalidAuthorizationHeaderError(AuthenticationError):
    """La petición no trae la cabecera ``Authorization`` o no es ``Bearer <token>``.

    El ``error`` es ``unauthorized``, el código de OAuth 2.0 que ya esperan los
    clientes para una petición sin credenciales utilizables.
    """

    error_name = "unauthorized"

    def __init__(self, message: str):
        """Construye el error.

        Args:
            message: Qué le pasa a la cabecera, para el log («falta la
                cabecera», «no es Bearer»…). No llega al usuario.
        """
        super().__init__(
            message=message,
            user_message="Tu sesión no es válida. Inicia sesión de nuevo.",
            message_key="invalidAuthorizationHeader",
        )


class InvalidAccessTokenError(AuthenticationError):
    """El access token no es válido o ha caducado.

    El ``error`` es ``invalid_token``, el código de RFC 6750 con el que el
    cliente sabe que debe renovar el token o volver a iniciar sesión.
    """

    default_code = ErrorCode.TOKEN_EXPIRED
    error_name = "invalid_token"

    def __init__(self):
        """Construye el error; no distingue caducado de manipulado a propósito."""
        super().__init__(
            message="El access token no es válido o ha caducado",
            user_message="Tu sesión ha caducado. Inicia sesión de nuevo.",
            message_key="invalidAccessToken",
        )


class InsufficientPermissionsError(AuthorizationError):
    """El usuario está identificado, pero su rol o sus permisos no alcanzan.

    El ``error`` es ``forbidden``: la interfaz lo usa para distinguir «no
    tienes permiso» de cualquier otro 403.
    """

    error_name = "forbidden"

    def __init__(self, message: str):
        """Construye el error.

        Args:
            message: Qué faltaba (el rol mínimo, los permisos concretos), para
                el log. No llega al usuario: decirle qué permisos existen no le
                ayuda y describe el modelo de permisos a quien no los tiene.
        """
        super().__init__(
            message=message,
            user_message="No tienes permisos suficientes para realizar esta acción.",
            message_key="insufficientPermissions",
        )


class PermissionCheckError(EllysiaException):
    """Falló la propia comprobación de identidad o de permisos, no el usuario.

    El ``error`` es ``server_error``, el código de OAuth 2.0 para un fallo del
    servidor de autorización.
    """

    default_code = ErrorCode.INTERNAL_SERVER_ERROR
    default_status_code = 500
    default_severity = ErrorSeverity.HIGH
    error_name = "server_error"

    def __init__(self, message: str):
        """Construye el error.

        Args:
            message: Qué comprobación falló, para el log.
        """
        super().__init__(
            message=message,
            user_message="No se pudo comprobar tu acceso. Inténtalo de nuevo.",
            message_key="permissionCheckFailed",
        )


class UserNotFoundError(EntityNotFoundError, AuthenticationError):
    default_code = ErrorCode.USER_NOT_FOUND
    # 401, no el 404 de EntityNotFoundError: se hereda de AuthenticationError
    # y se re-declara para que la mezcla no lo cambie. "Usuario no
    # encontrado" aquí es un fallo de autenticación, no un recurso ausente.
    default_status_code = 401
    default_severity = ErrorSeverity.MEDIUM

    entity_label = "Usuario"
    id_field = "id_usuario"


class UserBindingError(AuthenticationError):
    default_code = ErrorCode.UNBINDABLE_USER

    def __init__(self, username: str):
        super().__init__(
            message=f"No se pudo vincular el usuario '{username}' con una persona existente",
            details={"username": username},
            user_message="No se pudo crear el usuario porque faltan datos.",
            message_key="userBinding"
        )


class DuplicatedUserCredentials(AuthenticationError):
    default_code = ErrorCode.DUPLICATED_CREDENTIALS

    def __init__(self, credentials: str):
        super().__init__(
            message=f"Se ha detectado una credencial duplicada para un usuario",
            user_message=f"Ya hay una cuenta con este dato: {credentials}.",
            message_key="duplicatedUserCredentials",
            params={"value": credentials}
        )


def _describe_existing_user(username: Optional[str], email: Optional[str]) -> tuple[str, str, dict]:
    """Elige el mensaje de ``ExistingUserError`` según qué dato está repetido.

    Args:
        username: Identificador que ya está en uso, o ``None`` si el repetido
            es solo el correo.
        email: Correo que ya está en uso, o ``None`` si el repetido es solo el
            identificador.

    Returns:
        tuple[str, str, dict]: El texto para el usuario, su clave de mensaje y
            los valores de sus huecos.
    """
    if username is None:
        return (
            f"Ya existe una cuenta con el correo {email}.",
            "existingUserByEmail",
            {"email": email},
        )
    if email is None:
        return (
            f"Ya existe una cuenta con el identificador {username}.",
            "existingUserByUsername",
            {"username": username},
        )
    return (
        f"Ya existe una cuenta con el correo {email} o el identificador {username}.",
        "existingUser",
        {"email": email, "username": username},
    )


class ExistingUserError(AuthenticationError):
    default_code = ErrorCode.USER_ALREADY_EXISTS
    # 409, no el 401 que hereda de AuthenticationError: que un nombre de usuario
    # esté cogido no es un fallo de autenticación. Los dos endpoints que la
    # lanzan (sign-up de admin y alta pública) ya documentaban 409 en su
    # alt_response, así que hasta ahora contradecían su propio contrato — y un
    # cliente que trate el 401 como "sesión caducada" echaría al administrador
    # al intentar crear un usuario repetido.
    default_status_code = 409

    def __init__(self, username: Optional[str], email: Optional[str]):
        """Construye el error.

        Args:
            username: Identificador repetido, o ``None`` si solo lo está el correo.
            email: Correo repetido, o ``None`` si solo lo está el identificador.
        """
        user_message, message_key, params = _describe_existing_user(username, email)
        super().__init__(
            message="Se ha intentado crear un usuario con un email o nombre de usuario existentes",
            details={"username": username, "email": email},
            user_message=user_message,
            message_key=message_key,
            params=params,
        )


class ProfileUpdateError(AuthenticationError):
    default_code = ErrorCode.PROFILE_UPDATE_ERROR

    def __init__(self, message: str = "Error al actualizar el perfil"):
        super().__init__(
            message=message,
            user_message="No se pudo actualizar el perfil. Inténtalo de nuevo.",
            message_key="profileUpdate"
        )


class MfaAlreadyEnabledError(AuthenticationError):
    """El usuario ya tiene un método TOTP confirmado; no se puede re-inscribir
    sin desactivarlo antes."""
    default_code = ErrorCode.MFA_ALREADY_ENABLED
    default_status_code = 409

    def __init__(self):
        super().__init__(
            message="El usuario ya tiene MFA (TOTP) activado y confirmado",
            user_message="Ya tienes la verificación en dos pasos activada.",
            message_key="mfaAlreadyEnabled",
        )


class MfaNotEnabledError(AuthenticationError):
    """No existe una inscripción TOTP (confirmada o pendiente) para el usuario."""
    default_code = ErrorCode.MFA_NOT_ENABLED
    default_status_code = 400

    def __init__(self):
        super().__init__(
            message="El usuario no tiene MFA (TOTP) activado",
            user_message="No tienes la verificación en dos pasos activada.",
            message_key="mfaNotEnabled",
        )


class InvalidMfaCodeError(AuthenticationError):
    """El código TOTP o de recuperación no coincide."""
    default_code = ErrorCode.INVALID_MFA_CODE

    def __init__(self):
        super().__init__(
            message="Código MFA o de recuperación inválido",
            user_message="El código introducido no es válido.",
            message_key="invalidMfaCode",
        )


class MfaChallengeInvalidError(AuthenticationError):
    """El challenge de MFA no existe, expiró o agotó sus intentos.

    Los dos flujos que lo usan piden al usuario cosas distintas: el de login
    que inicie sesión de nuevo y el de recuperación de contraseña que vuelva a
    solicitarla. Por eso tiene dos mensajes, cada uno con su clave.
    """
    default_code = ErrorCode.MFA_CHALLENGE_INVALID

    def __init__(self, is_password_reset: bool = False):
        """Construye el error.

        Args:
            is_password_reset: ``True`` si el challenge era el de recuperación
                de contraseña; ``False`` (por defecto) si era el de login.
        """
        super().__init__(
            message="El challenge de MFA es inválido, expiró o agotó sus intentos",
            user_message=(
                "La verificación ha caducado. Vuelve a solicitar la recuperación."
                if is_password_reset
                else "La verificación ha caducado. Inicia sesión de nuevo."
            ),
            message_key=(
                "mfaChallengeInvalidPasswordReset" if is_password_reset else "mfaChallengeInvalid"
            ),
        )

# =========================================================================
# ALTA PÚBLICA Y VERIFICACIÓN DE CORREO
# =========================================================================

class RegistrationClosedError(SurfaceDisabledError):
    """Esta instalación no acepta altas públicas.

    Es el cierre de la superficie ``registration`` de ``general.launch``: una
    decisión del despliegue, no del usuario. Un Ellysia en vista previa, o uno
    interno de una empresa, tiene el grifo cerrado y da de alta a su gente
    desde el panel. Conserva su propio código (``REGISTRATION_CLOSED``) y su
    texto, que le dice al usuario qué hacer en lugar de un «no disponible».
    """

    default_code = ErrorCode.REGISTRATION_CLOSED

    def __init__(self) -> None:
        """Construye el error con el texto específico del alta."""
        super().__init__(
            "registration",
            user_message=(
                "Esta instalación de Ellysia no acepta registros. Pide a un administrador que te "
                "cree la cuenta."
            ),
            message_key="registrationClosed",
        )


class InvalidVerificationTokenError(AuthenticationError):
    """Enlace de verificación inexistente, ya usado o caducado.

    Los tres casos dan el mismo error a propósito: distinguirlos permitiría
    averiguar qué tokens existieron.
    """

    default_code = ErrorCode.INVALID_VERIFICATION_TOKEN
    default_status_code = 400

    def __init__(self) -> None:
        super().__init__(
            message="Token de verificacion invalido o caducado",
            user_message=(
                "Este enlace de confirmación no es válido o ha caducado. Puedes pedir uno nuevo "
                "desde tu perfil."
            ),
            message_key="invalidVerificationToken",
        )


class EmailAlreadyVerifiedError(EllysiaException):
    """Se pidió reenviar la confirmación de un correo ya confirmado."""

    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 409

    def __init__(self) -> None:
        super().__init__(
            message="El correo ya esta verificado",
            user_message="Tu correo ya está confirmado.",
            message_key="emailAlreadyVerified",
        )


# =========================================================================
# RECUPERACIÓN DE CONTRASEÑA
# =========================================================================


class PasswordResetTokenInvalidError(AuthenticationError):
    """Enlace de recuperación inexistente, ya usado o caducado.

    Los tres casos dan el mismo error a propósito: distinguirlos permitiría
    averiguar qué enlaces existieron.
    """

    default_code = ErrorCode.PASSWORD_RESET_TOKEN_INVALID
    default_status_code = 400

    def __init__(self) -> None:
        super().__init__(
            message="Token de recuperacion invalido o caducado",
            user_message=(
                "Este enlace de recuperación no es válido o ha caducado. Puedes pedir uno nuevo "
                "desde la pantalla de acceso."
            ),
            message_key="passwordResetTokenInvalid",
        )
