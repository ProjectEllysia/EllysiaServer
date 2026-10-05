"""Qué métodos de autenticación ofrece un servidor SSH (L115).

Dos capas de prueba. La primera es de integración ligera: un servidor SSH de
verdad, servido por el propio paramiko en modo servidor sobre loopback (el
mismo patrón que ya usan los tests de aiosmtpd, permitido por la red sellada —
ver CLAUDE.md § «cosas que muerden»), que demuestra que :class:`SshAuthProbe`
completa de verdad el intercambio de claves y lee lo que el servidor contesta.
La segunda, más rápida, ejercita los dos plugins con una sonda fija: no hace
falta repetir el protocolo entero para probar la lógica de «qué hallazgo
corresponde a qué respuesta».
"""

import socket
import threading
from contextlib import contextmanager

import paramiko
import pytest

from src.modules.features.themis.lybra.checks import Service
from src.modules.features.themis.lybra.fingerprinting.ssh_auth import (
    SshAuthMethods,
    SshAuthProbe,
)
from src.modules.features.themis.lybra.script_checks import (
    SshNoneAuthenticationAcceptedPlugin,
    SshPasswordOnlyAuthenticationPlugin,
    _SshAuthCache,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

# Una sola clave de equipo para todo el módulo: generarla es lo único lento
# del test, y no hace falta una distinta por servidor.
_HOST_KEY = paramiko.RSAKey.generate(1024)


class _Server(paramiko.ServerInterface):
    """Un servidor SSH mínimo: decide si acepta ``none`` y qué anuncia si no."""

    def __init__(self, allow_none: bool, methods: str) -> None:
        self._allow_none = allow_none
        self._methods = methods

    def check_auth_none(self, _username):
        return paramiko.AUTH_SUCCESSFUL if self._allow_none else paramiko.AUTH_FAILED

    def get_allowed_auths(self, _username):
        return self._methods

    def check_channel_request(self, _kind, _chanid):
        return paramiko.OPEN_SUCCEEDED


def _serve_once(listener, allow_none, methods):
    client_sock, _addr = listener.accept()
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(_HOST_KEY)
    try:
        transport.start_server(server=_Server(allow_none, methods))
        transport.accept(timeout=5)
    except Exception:  # pylint: disable=broad-except
        pass
    finally:
        transport.close()


@contextmanager
def _ssh_server(allow_none: bool = False, methods: str = "publickey,password"):
    """Levanta un servidor SSH real en ``127.0.0.1`` y cede ``(host, port)``."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()
    thread = threading.Thread(target=_serve_once, args=(listener, allow_none, methods), daemon=True)
    thread.start()
    try:
        yield host, port
    finally:
        listener.close()
        thread.join(timeout=5)


# ======================================================================
# La sonda contra un servidor real
# ======================================================================

def test_a_server_that_accepts_none_is_reported_as_open():
    with _ssh_server(allow_none=True) as (host, port):
        result = SshAuthProbe(timeout=5).fetch(host, port)
    assert result == SshAuthMethods((), True)


def test_a_server_that_requires_publickey_lists_it_and_rejects_none():
    with _ssh_server(allow_none=False, methods="publickey") as (host, port):
        result = SshAuthProbe(timeout=5).fetch(host, port)
    assert result == SshAuthMethods(("publickey",), False)


def test_a_server_offering_several_methods_lists_them_all():
    with _ssh_server(allow_none=False, methods="publickey,password,keyboard-interactive") as (host, port):
        result = SshAuthProbe(timeout=5).fetch(host, port)
    assert set(result.methods) == {"publickey", "password", "keyboard-interactive"}
    assert not result.is_none_accepted


def test_a_refused_connection_is_inconclusive():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    host, port = listener.getsockname()
    listener.close()  # nada escuchando: la conexión se rechaza
    assert SshAuthProbe(timeout=2).fetch(host, port) is None


def test_something_that_is_not_ssh_is_inconclusive_not_a_crash():
    """Un servicio que acepta la conexión pero no habla SSH (p. ej. HTTP) no
    debe nunca interpretarse como `none` aceptado: la sonda debe rendirse."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    def serve_garbage():
        client_sock, _addr = listener.accept()
        try:
            client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        finally:
            client_sock.close()

    thread = threading.Thread(target=serve_garbage, daemon=True)
    thread.start()
    try:
        assert SshAuthProbe(timeout=3).fetch(host, port) is None
    finally:
        listener.close()
        thread.join(timeout=5)


# ======================================================================
# Los dos plugins, con una sonda fija
# ======================================================================

class _FixedProbe:
    def __init__(self, result):
        self._result = result

    def fetch(self, _host, _port):
        return self._result


class _Context:
    def __init__(self, port=22):
        self.target = "10.0.0.5"
        self.service = Service(port, "tcp", "ssh")

    def acquire(self):
        pass


def test_the_none_check_fires_only_when_the_server_accepts_it():
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods((), True)))
    assert SshNoneAuthenticationAcceptedPlugin(cache).run(_Context()) is True


def test_the_none_check_stays_quiet_when_a_method_is_required():
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods(("publickey",), False)))
    assert SshNoneAuthenticationAcceptedPlugin(cache).run(_Context()) is False


def test_the_none_check_stays_quiet_without_evidence():
    cache = _SshAuthCache(probe=_FixedProbe(None))
    assert SshNoneAuthenticationAcceptedPlugin(cache).run(_Context()) is False


def test_the_password_only_check_fires_when_password_is_offered_without_publickey():
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods(("password",), False)))
    assert SshPasswordOnlyAuthenticationPlugin(cache).run(_Context()) is True


def test_the_password_only_check_also_fires_for_keyboard_interactive_alone():
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods(("keyboard-interactive",), False)))
    assert SshPasswordOnlyAuthenticationPlugin(cache).run(_Context()) is True


def test_the_password_only_check_stays_quiet_when_publickey_is_also_offered():
    """Señuelo: el servidor exige clave pública además de aceptar contraseña."""
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods(("publickey", "password"), False)))
    assert SshPasswordOnlyAuthenticationPlugin(cache).run(_Context()) is False


def test_the_password_only_check_stays_quiet_when_none_is_accepted():
    """El hallazgo del método `none` es el más grave; este no se duplica encima."""
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods((), True)))
    assert SshPasswordOnlyAuthenticationPlugin(cache).run(_Context()) is False


def test_the_password_only_check_stays_quiet_when_only_publickey_is_offered():
    """Señuelo del propio issue: un servidor que exige clave pública y rechaza
    tanto `none` como contraseña no debe disparar ningún aviso nuevo."""
    cache = _SshAuthCache(probe=_FixedProbe(SshAuthMethods(("publickey",), False)))
    assert SshNoneAuthenticationAcceptedPlugin(cache).run(_Context()) is False
    assert SshPasswordOnlyAuthenticationPlugin(cache).run(_Context()) is False


def test_the_two_plugins_share_one_query_per_service():
    """La misma razón que ya vale para los cuatro de algoritmos débiles: no
    abrir dos sesiones SSH para dos preguntas sobre la misma respuesta."""
    calls = []

    class _CountingProbe:
        def fetch(self, host, port):
            calls.append((host, port))
            return SshAuthMethods(("password",), False)

    cache = _SshAuthCache(probe=_CountingProbe())
    context = _Context()
    SshNoneAuthenticationAcceptedPlugin(cache).run(context)
    SshPasswordOnlyAuthenticationPlugin(cache).run(context)
    assert calls == [("10.0.0.5", 22)]


# ======================================================================
# Registro y modo
# ======================================================================

def test_the_two_checks_are_registered_and_run_in_aggressive_mode():
    from src.modules.features.themis.lybra.checks import load_checks

    for check_id in ("ssh-none-authentication-accepted", "ssh-password-only-authentication"):
        check = next(c for c in load_checks() if c.id == check_id)
        assert check.mode == "aggressive" and check.service == "ssh"
        assert check.script in default_script_plugins()
