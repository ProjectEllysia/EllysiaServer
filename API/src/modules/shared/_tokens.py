"""
Tokens opacos de un solo uso: verificación de correo, recuperación de contraseña
e invitaciones a una organización.

Son funciones puras (solo ``secrets``, ``hashlib`` y ``hmac`` de la biblioteca
estándar, sin base de datos ni conceptos de dominio) y las usan varios módulos,
así que viven aquí y no en los ``services`` de ninguno de ellos.
"""

import hashlib
import hmac
import secrets


def generate_opaque_token() -> str:
    """Genera un token aleatorio para enlaces de un solo uso.

    32 bytes de ``secrets.token_urlsafe`` — el mismo criterio que la clave de
    agente de Hygeia o el token del quiz de Aegis: entropía suficiente para que
    el token sea, por sí solo, la identidad de quien pulsa el enlace.

    Returns:
        str: El token en claro, apto para ir en una URL. Es lo que se envía al
            destinatario; lo que se guarda es ``hash_opaque_token(token)``.
    """
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """Calcula el SHA-256 del token, que es lo único que se guarda.

    A diferencia de las contraseñas y de los códigos de recuperación de MFA,
    aquí NO se usa Argon2: un KDF lento existe para encarecer la fuerza bruta
    sobre secretos que un humano podría adivinar, y esto son 256 bits
    aleatorios. Lo que sí importa es no guardar el token en claro, para que una
    lectura de la base de datos no permita verificar cuentas ajenas.

    Args:
        token: El token en claro, tal cual lo devolvió ``generate_opaque_token``.

    Returns:
        str: El SHA-256 del token en hexadecimal (64 caracteres).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_opaque_token(token: str, stored_hash: str) -> bool:
    """Compara en tiempo constante un token contra su hash guardado.

    Args:
        token: El token en claro que presenta quien pulsa el enlace.
        stored_hash: El hash guardado, o ``None``/vacío si no hay ninguno.

    Returns:
        bool: ``True`` si el hash del token coincide con ``stored_hash``;
            ``False`` si no coincide o no hay hash guardado.
    """
    return hmac.compare_digest(hash_opaque_token(token), stored_hash or "")
