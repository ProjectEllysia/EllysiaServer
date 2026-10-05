"""Qué métodos de autenticación ofrece un servidor SSH, sin aportar ninguna credencial.

``fingerprinting.ssh`` lee el primer mensaje del servidor (banner y ``KEXINIT``)
y se detiene ahí: ese mensaje da producto, versión y los algoritmos que acepta,
pero no dice qué métodos de autenticación ofrece. Para saberlo hace falta
completar el intercambio de claves y llegar a la fase de autenticación —un
diálogo de varios pasos que no vale la pena reconstruir a mano cuando ya existe
una implementación de referencia del protocolo de transporte.

Por eso este módulo, a diferencia del resto de ``fingerprinting/``, no
reimplementa el protocolo: usa el transporte de **paramiko** (``Transport``),
la misma clase de dependencia con la que ``cryptography`` ya cubre TLS en el
resto del motor. Lo único que se pregunta es ``auth_none``: una
``USERAUTH_REQUEST`` con el método ``none``, que por definición no lleva
ninguna credencial. El servidor contesta de dos formas:

* **La acepta** (``USERAUTH_SUCCESS``): deja entrar sin nada. Es el mismo
  hallazgo que PostgreSQL en modo ``trust``.
* **La rechaza** (``BadAuthenticationType``), y de propina enumera qué
  métodos sí acepta (``publickey``, ``password``, ``keyboard-interactive``).

No se prueba ninguna contraseña ni ninguna clave: se pregunta qué métodos
existen, que es lo que hace cualquier cliente SSH antes de pedirle nada al
usuario. Aun así es un intento de autenticación real, que el servidor puede
dejar en su registro — por eso los checks que usan esta sonda sólo corren en
modo agresivo (ver ``checks_feed.yaml``).
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

#: El nombre de usuario con el que se pregunta. No es una credencial —
#: ``auth_none`` no lleva ninguna—, sólo el campo que el mensaje exige.
_PROBE_USERNAME = "lybra-auth-probe"


@dataclass(frozen=True)
class SshAuthMethods:
    """Lo que un servidor SSH contestó a una petición de autenticación ``none``.

    Attributes:
        methods: Los métodos que el servidor anunció como válidos
            (``("publickey", "password")``...). Vacía cuando ``is_none_accepted``
            es ``True``: un servidor que deja entrar sin nada no necesita
            anunciar ningún método.
        is_none_accepted: ``True`` si el servidor contestó con éxito al método
            ``none`` — acceso sin ninguna credencial.
    """
    methods: Tuple[str, ...]
    is_none_accepted: bool


class SshAuthProbe:
    """Abre una conexión SSH y pregunta ``auth_none``, con el transporte de paramiko.

    Args:
        timeout: El plazo de conexión y del intercambio de claves, en segundos.
            Por defecto 5.
        connect: Callable ``(address, timeout) -> socket`` inyectable, para que
            un test use un socket falso o apunte a un servidor de prueba en
            loopback. Por defecto, ``socket.create_connection``.
        transport_factory: Callable ``socket -> paramiko.Transport`` inyectable,
            para que un test sustituya el transporte real. Por defecto,
            ``paramiko.Transport``.
    """

    def __init__(self, timeout: float = 5.0, connect: Optional[Callable] = None,
                transport_factory: Optional[Callable] = None) -> None:
        self._timeout = timeout
        self._connect = connect or socket.create_connection
        self._transport_factory = transport_factory or paramiko.Transport

    def fetch(self, host: str, port: int = 22) -> Optional[SshAuthMethods]:
        """Completa el intercambio de claves y pregunta ``auth_none``.

        Args:
            host: El objetivo.
            port: El puerto SSH. Por defecto 22.

        Returns:
            SshAuthMethods | None: El resultado, o ``None`` si no hubo
            conexión, el intercambio de claves no llegó a completarse o el
            servidor cerró antes de contestar — «no concluyente», nunca un
            hallazgo.
        """
        try:
            sock = self._connect((host, port), self._timeout)
        except OSError as err:
            logger.debug("SSH auth: conexión fallida a %s:%s: %s", host, port, err)
            return None
        transport = self._transport_factory(sock)
        try:
            transport.start_client(timeout=self._timeout)
            try:
                transport.auth_none(_PROBE_USERNAME)
                return SshAuthMethods((), True)
            except paramiko.ssh_exception.BadAuthenticationType as err:
                return SshAuthMethods(tuple(err.allowed_types), False)
        except (paramiko.ssh_exception.SSHException, OSError, EOFError) as err:
            logger.debug("SSH auth: intercambio fallido con %s:%s: %s", host, port, err)
            return None
        finally:
            transport.close()
