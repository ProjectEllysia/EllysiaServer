"""El spooler de impresión o el localizador de RPC de un controlador de dominio, expuestos.

Un controlador de dominio es el activo de mayor valor de una red Windows.
Que su spooler de impresión (la base de PrintNightmare) o su localizador de
puntos finales de RPC (puerto 135) contesten desde la red es una superficie
que vale la pena señalar por sí sola — pero sólo en un controlador de
dominio: el mismo Windows sin LDAP de Active Directory al lado no dispara.
"""

import pytest

from src.modules.features.themis.lybra.checks import ScriptContext
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.ldap import TAG_BIND_RESPONSE, TAG_SEARCH_ENTRY, ber
from src.modules.features.themis.lybra.script_checks import (
    DomainControllerRpcSurfaceExposedPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_SMB = Service(port=445, protocol="tcp", name="microsoft-ds")
_LDAP = Service(port=389, protocol="tcp", name="ldap")
_LDAPS = Service(port=636, protocol="tcp", name="ldaps")
_HTTP = Service(port=80, protocol="tcp", name="http")


def _message(message_id, operation_tag, operation_body):
    return ber(0x30, ber(0x02, bytes((message_id,))) + ber(operation_tag, operation_body))


def _bind_reply():
    body = ber(0x0A, bytes((0,))) + ber(0x04, b"") + ber(0x04, b"")
    return _message(1, TAG_BIND_RESPONSE, body)


def _attribute(name, values):
    return ber(0x30, ber(0x04, name.encode()) + ber(
        0x31, b"".join(ber(0x04, value.encode()) for value in values)))


def _rootdse_with_naming_context(naming_context="DC=corp,DC=test"):
    """Un rootDSE de Active Directory, con su contexto de nombres propio."""
    body = ber(0x04, b"") + ber(0x30, _attribute("namingContexts", [naming_context]))
    return _message(2, TAG_SEARCH_ENTRY, body)


def _rootdse_without_naming_context():
    """Un directorio (o cualquier cosa) sin namingContexts: no es un dominio."""
    body = ber(0x04, b"") + ber(0x30, _attribute("vendorName", ["Genérico"]))
    return _message(2, TAG_SEARCH_ENTRY, body)


class _FakeLdapProbe:
    def __init__(self, replies):
        self._replies = replies
        self.calls = []

    def fetch(self, host, port):
        self.calls.append((host, port))
        return self._replies


def _plugin(is_domain_controller=True, spooler=None, epmap=None, ldap_calls=None):
    """Un plugin con las tres sondas de red inyectadas."""
    replies = ((_bind_reply(), _rootdse_with_naming_context())
               if is_domain_controller else (_bind_reply(), _rootdse_without_naming_context()))
    ldap_probe = _FakeLdapProbe(replies)
    if ldap_calls is not None:
        ldap_calls.append(ldap_probe)
    pipe_calls = []
    epmap_calls = []

    def probe_named_pipe_rpc(host, pipe, interface_uuid, interface_version, port=445):
        pipe_calls.append((host, pipe, port))
        return spooler

    def probe_endpoint_mapper(host):
        epmap_calls.append(host)
        return epmap

    plugin = DomainControllerRpcSurfaceExposedPlugin(
        ldap_probe=ldap_probe,
        probe_named_pipe_rpc=probe_named_pipe_rpc,
        probe_endpoint_mapper=probe_endpoint_mapper,
    )
    return plugin, ldap_probe, pipe_calls, epmap_calls


def _context(siblings=(_LDAP,)):
    return ScriptContext(target="203.0.113.10", service=_SMB, sibling_services=siblings)


# ============================================================ el criterio de cierre


def test_a_domain_controller_with_both_surfaces_reachable_fires():
    plugin, _ldap, _pipe, _epmap = _plugin(is_domain_controller=True, spooler=True, epmap=True)

    assert plugin.run(_context()) is True


def test_the_evidence_names_which_surfaces_answered():
    plugin, _ldap, _pipe, _epmap = _plugin(is_domain_controller=True, spooler=True, epmap=None)
    context = _context()

    plugin.run(context)

    assert context.evidence == {"exposedSurfaces": ["print-spooler"]}


def test_a_rejected_spooler_bind_still_counts_as_reachable():
    """El hallazgo es que el cortafuegos no lo bloquea, no que la sesión anónima cuele."""
    plugin, _ldap, _pipe, _epmap = _plugin(is_domain_controller=True, spooler=False, epmap=None)

    assert plugin.run(_context()) is True


def test_firewalled_surfaces_do_not_fire():
    """Señuelo directo del Issue: los mismos puntos de acceso restringidos por cortafuegos."""
    plugin, _ldap, _pipe, _epmap = _plugin(is_domain_controller=True, spooler=None, epmap=None)

    assert plugin.run(_context()) is False


# ============================================================ sólo un controlador de dominio


def test_a_non_domain_windows_with_the_same_surfaces_does_not_fire():
    """Señuelo directo del Issue: el mismo Windows sin ser controlador de dominio."""
    plugin, _ldap, _pipe, _epmap = _plugin(is_domain_controller=False, spooler=True, epmap=True)

    assert plugin.run(_context()) is False


def test_a_host_without_any_ldap_sibling_does_not_even_query_ldap():
    plugin, ldap_probe, pipe_calls, epmap_calls = _plugin(spooler=True, epmap=True)

    assert plugin.run(_context(siblings=(_HTTP,))) is False
    assert ldap_probe.calls == []
    assert pipe_calls == [] and epmap_calls == []


def test_the_preferred_ldap_port_is_389_over_the_global_catalog():
    plugin, ldap_probe, _pipe, _epmap = _plugin(is_domain_controller=True, spooler=True)

    plugin.run(_context(siblings=(Service(3268, "tcp", "globalcatldap"), _LDAP)))

    assert ldap_probe.calls == [("203.0.113.10", 389)]


def test_an_ldaps_only_sibling_is_used_when_it_is_the_only_one():
    plugin, ldap_probe, _pipe, _epmap = _plugin(is_domain_controller=True, spooler=True)

    plugin.run(_context(siblings=(_LDAPS,)))

    assert ldap_probe.calls == [("203.0.113.10", 636)]


def test_ldap_that_does_not_answer_does_not_fire():
    ldap_probe = _FakeLdapProbe(None)
    plugin = DomainControllerRpcSurfaceExposedPlugin(
        ldap_probe=ldap_probe, probe_named_pipe_rpc=lambda *a, **k: True,
        probe_endpoint_mapper=lambda *a: True)

    assert plugin.run(_context()) is False


# ============================================================ aplicabilidad y registro


def test_only_smb_services_apply():
    plugin = DomainControllerRpcSurfaceExposedPlugin()

    assert plugin.applies(_SMB) is True
    assert plugin.applies(_HTTP) is False


def test_the_endpoint_mapper_is_always_checked_on_its_own_port_regardless_of_the_smb_port():
    plugin, _ldap, pipe_calls, epmap_calls = _plugin(
        is_domain_controller=True, spooler=True, epmap=True)
    context = ScriptContext(
        target="203.0.113.10", service=Service(139, "tcp", "netbios-ssn"), sibling_services=(_LDAP,))

    plugin.run(context)

    assert pipe_calls == [("203.0.113.10", "spoolss", 139)]
    assert epmap_calls == ["203.0.113.10"]


def test_the_plugin_is_registered():
    assert "domain-controller-rpc-surface-exposed" in default_script_plugins()
