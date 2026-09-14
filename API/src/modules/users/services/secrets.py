"""
Password hashing and verification using Argon2id.

Provides forward-compatible verification: hashes starting with '$argon2'
are verified with Argon2, while legacy SHA-256+salt hashes are verified
with hmac.compare_digest and transparently migrated to Argon2 on next login.

Functions:
    hash_password         — Hash a password with Argon2id (includes salt).
    verify_password       — Verify a password; returns (valid, needs_rehash).
    generate_salt         — Legacy helper kept for DB compatibility during migration.
    hash_password_with_salt — Legacy SHA-256 helper kept for migration path only.
"""

import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

import src.modules.system.config_reading as CR


_HASHER = PasswordHasher(**CR.argon2_config().as_kwargs())
"""
Instancia del hasher de Argon2 para la ocultación de las
contraseñas.

La configuración de Argon2 se transmite a la librería a través
de la configuración registrada en ``SecOpsConfig.json``. 
"""


def hash_password(password: str) -> str:
    """Hash a password with Argon2id. The salt is embedded in the returned string."""
    return _HASHER.hash(password)

def verify_password(
    stored_hash: str,
    password: str,
    legacy_salt: str = "",
) -> tuple[bool, bool]:
    """
    Verifica una contraseña contra su dato hash almacenado en la base
    de datos.

    Tiene soporte para tanto Argon2id (la nueva implementación de
    almacenamiento de contraseñas) como el legacy SHA-256+salt.

    Args:
        stored_hash:    El hash alacenado en la base de datos.
        password:       La contraseña en texto **plano**.
        legacy_salt:    La salt usada para el almacenamiento legacy (ignorado
                        si el hash es de tipo Argon2id)

    Returns:
        is_valid: ``True`` si la contraseña en texto plano es correcta; falso,
            en caso contrario
        needs_rehash: ``True``, si la configuración de Argon2 cambió con respecto
            a la configuración la que se hasheó la contraseña por última vez; ``False``
            en caso contrario (es decir, si la configuración no cambió)

    """
    if stored_hash.startswith("$argon2"):
        try:
            _HASHER.verify(stored_hash, password)

            # Comprueba si necesita rehash comparando los valores con los
            # que fue hasheada la contraseña comprobada
            # y los valores actuales de la configuración de Argon2
            # (que se pasaron anteriormente por parámetro al
            # construir el hasher)
            needs_rehash = _HASHER.check_needs_rehash(stored_hash)
            return True, needs_rehash

        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False

    # Legacy SHA-256+salt path
    expected = hash_password_with_salt(password, legacy_salt)
    is_valid = hmac.compare_digest(expected, stored_hash)
    return is_valid, is_valid  # needs_rehash == is_valid (upgrade on success)


# ---------------------------------------------------------------------------
# Legacy helpers — kept only for the migration path (SHA-256 verification).
# Do NOT use for new passwords.
# ---------------------------------------------------------------------------

def generate_salt() -> str:
    """
    Return an empty string. Argon2 embeds its own salt; kept for API compat.
    """
    return ""

def hash_password_with_salt(password: str, salt: str) -> str:
    """SHA-256 hash of salt+password. Used only to verify legacy stored hashes."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


# =========================================================================
# TOKENS OPACOS DE UN SOLO USO (verificación de correo, invitaciones)
# =========================================================================

def generate_opaque_token() -> str:
    """Token aleatorio para enlaces de un solo uso.

    32 bytes de ``secrets.token_urlsafe`` — el mismo criterio que la clave de
    agente de Hygeia o el token del quiz de Aegis: entropía suficiente para que
    el token sea, por sí solo, la identidad de quien pulsa el enlace.
    """
    import secrets as _secrets

    return _secrets.token_urlsafe(32)

def hash_opaque_token(token: str) -> str:
    """SHA-256 del token, que es lo único que se guarda.

    A diferencia de las contraseñas y de los códigos de recuperación de MFA,
    aquí NO se usa Argon2: un KDF lento existe para encarecer la fuerza bruta
    sobre secretos que un humano podría adivinar, y esto son 256 bits
    aleatorios. Lo que sí importa es no guardar el token en claro, para que una
    lectura de la base de datos no permita verificar cuentas ajenas.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def verify_opaque_token(token: str, stored_hash: str) -> bool:
    """Comparación en tiempo constante del token contra su hash guardado."""
    return hmac.compare_digest(hash_opaque_token(token), stored_hash or "")
