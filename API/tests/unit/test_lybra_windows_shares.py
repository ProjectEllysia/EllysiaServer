"""Carpetas compartidas de Windows visibles sin ninguna credencial.

Sobre el cliente mínimo de llamadas remotas de Windows (L105) se puede listar
las carpetas que un equipo comparte con una sesión anónima. El hallazgo es
que la lista de nombres es visible sin autenticar — nunca lo que hay dentro
de cada una, que este plugin no abre ni lee.
"""

import pytest

from src.modules.features.themis.lybra.checks import ScriptContext
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.windows_rpc import ShareInfo
from src.modules.features.themis.lybra.script_checks import (
    WindowsSharesUnauthenticatedPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_SMB = Service(port=445, protocol="tcp", name="microsoft-ds")
_HTTP = Service(port=80, protocol="tcp", name="http")


def _fetcher(shares, calls=None):
    """Sonda falsa: devuelve ``shares`` tal cual y registra cómo se la llamó."""
    calls = calls if calls is not None else []

    def fetch_shares(host, port):
        calls.append((host, port))
        return shares
    fetch_shares.calls = calls
    return fetch_shares


def test_a_real_unrestricted_share_fires():
    """El criterio de cierre: una carpeta real, sin restricción, visible sin credenciales."""
    shares = [ShareInfo(name="Publico", share_type=0, remark="Carpeta publica")]
    context = ScriptContext(target="203.0.113.10", service=_SMB)

    plugin = WindowsSharesUnauthenticatedPlugin(fetch_shares=_fetcher(shares))

    assert plugin.run(context) is True
    assert context.evidence == {"shares": ["Publico"]}


def test_shares_restricted_to_authenticated_users_do_not_fire():
    """Señuelo directo del Issue: el mismo equipo con las carpetas restringidas
    no lista nada, así que la sonda inyectada nunca ve una carpeta real."""
    context = ScriptContext(target="203.0.113.10", service=_SMB)

    plugin = WindowsSharesUnauthenticatedPlugin(fetch_shares=_fetcher([]))

    assert plugin.run(context) is False


def test_only_administrative_shares_do_not_fire():
    """ADMIN$, C$ e IPC$ existen en cualquier Windows: no son, por sí solas, un
    hallazgo de este equipo en particular."""
    shares = [
        ShareInfo(name="ADMIN$", share_type=0x80000000, remark="Remote Admin"),
        ShareInfo(name="C$", share_type=0x80000000, remark="Default share"),
        ShareInfo(name="IPC$", share_type=3, remark="Remote IPC"),
    ]
    context = ScriptContext(target="203.0.113.10", service=_SMB)

    plugin = WindowsSharesUnauthenticatedPlugin(fetch_shares=_fetcher(shares))

    assert plugin.run(context) is False


def test_a_real_share_alongside_administrative_ones_still_fires():
    shares = [
        ShareInfo(name="ADMIN$", share_type=0x80000000, remark=""),
        ShareInfo(name="Backups", share_type=0, remark="Copias de seguridad"),
    ]
    context = ScriptContext(target="203.0.113.10", service=_SMB)

    plugin = WindowsSharesUnauthenticatedPlugin(fetch_shares=_fetcher(shares))

    assert plugin.run(context) is True
    assert context.evidence == {"shares": ["Backups"]}


def test_a_share_whose_name_ends_in_dollar_without_the_hidden_bit_is_still_hidden():
    """``is_hidden`` mira el nombre además del bit: un servidor que no marca
    el bit alto pero nombra la compartida acabada en ``$`` tampoco cuenta."""
    shares = [ShareInfo(name="print$", share_type=0, remark="Printer drivers")]
    context = ScriptContext(target="203.0.113.10", service=_SMB)

    plugin = WindowsSharesUnauthenticatedPlugin(fetch_shares=_fetcher(shares))

    assert plugin.run(context) is False


def test_only_smb_services_apply():
    plugin = WindowsSharesUnauthenticatedPlugin()

    assert plugin.applies(_SMB) is True
    assert plugin.applies(_HTTP) is False


def test_the_service_port_reaches_the_client():
    calls = []
    context = ScriptContext(target="203.0.113.10", service=Service(139, "tcp", "netbios-ssn"))

    WindowsSharesUnauthenticatedPlugin(fetch_shares=_fetcher([], calls)).run(context)

    assert calls == [("203.0.113.10", 139)]


def test_the_plugin_is_registered():
    assert "windows-shares-unauthenticated" in default_script_plugins()
