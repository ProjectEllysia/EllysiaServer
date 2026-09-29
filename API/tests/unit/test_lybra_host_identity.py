"""Lo que un equipo cuenta de sí mismo sin credenciales, como hallazgo informativo.

Las sondas de SMB y de LDAP ya leen el nombre de un equipo Windows y el dominio
de un directorio para identificar el servicio. Estos tests cubren los dos avisos
que convierten ese dato en contexto para el informe: que nombran el activo en
el título, que un equipo fuera de dominio no recibe un dominio inventado, que
el mismo dato no se repite por cada puerto del host y que la categoría no entra
en el ciclo de vida de los hallazgos.
"""

import pytest

from src.modules.features.themis.lybra.checks import (
    CHECK_CATEGORIES,
    EVENT_CHECK_CATEGORIES,
    CheckRuntime,
    ScriptContext,
    load_checks,
    render_title,
)
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.script_checks import (
    LdapDirectoryDomainPlugin,
    SmbHostIdentityPlugin,
    default_script_plugins,
)

pytestmark = pytest.mark.unit

_SMB = Service(445, "tcp", "microsoft-ds")
_LDAP = Service(389, "tcp", "ldap")


class _SmbProbe:
    """Sonda SMB falsa: negocia SMB 3.1.1 y contesta con la identidad dada."""

    def __init__(self, identity):
        self.identity = identity
        self.calls = 0

    def fetch(self, host, port=445):
        self.calls += 1
        return 0x0311, 0x01

    def fetch_identity(self, host, port=445):
        return self.identity


class _LdapProbe:
    """Sonda LDAP falsa que devuelve las respuestas ya construidas."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = 0

    def fetch(self, host, port=389):
        self.calls += 1
        return self.replies


def _context(service, siblings=()):
    return ScriptContext(target="10.0.0.5", service=service, sibling_services=(service, *siblings))


# ================================================================== SMB


def test_a_domain_member_is_named_with_its_domain():
    context = _context(_SMB)
    plugin = SmbHostIdentityPlugin(probe=_SmbProbe({
        "netbios_computer_name": "WIN-SRV01", "netbios_domain_name": "CORP",
        "dns_computer_name": "win-srv01.corp.local", "dns_domain_name": "corp.local"}))
    assert plugin.run(context) is True
    assert context.evidence == {"identity": "WIN-SRV01 (win-srv01.corp.local, dominio CORP)"}


def test_a_workgroup_machine_gets_no_invented_domain():
    """Señuelo: fuera de dominio, el equipo contesta con su propio nombre donde
    iría el dominio; el aviso no menciona dominio ninguno."""
    context = _context(_SMB)
    plugin = SmbHostIdentityPlugin(probe=_SmbProbe({
        "netbios_computer_name": "PORTATIL", "netbios_domain_name": "PORTATIL",
        "dns_computer_name": "portatil"}))
    assert plugin.run(context) is True
    assert context.evidence == {"identity": "PORTATIL"}
    assert "dominio" not in context.evidence["identity"]


def test_a_machine_that_did_not_say_its_name_is_not_reported():
    assert SmbHostIdentityPlugin(probe=_SmbProbe({})).run(_context(_SMB)) is False


def test_the_smb_identity_is_reported_once_per_host():
    """El 139 y el 445 dicen lo mismo: informa el 445 y el 139 ni conecta."""
    netbios = Service(139, "tcp", "netbios-ssn")
    probe = _SmbProbe({"netbios_computer_name": "WIN-SRV01"})
    assert SmbHostIdentityPlugin(probe=probe).run(_context(netbios, siblings=(_SMB,))) is False
    assert probe.calls == 0
    assert SmbHostIdentityPlugin(probe=probe).run(_context(_SMB, siblings=(netbios,))) is True


# ================================================================= LDAP


def _ldap_replies(*naming_contexts):
    """Un bind anónimo aceptado y un rootDSE con esos ``namingContexts``, en BER."""
    from src.modules.features.themis.lybra.fingerprinting.ldap import (
        RESULT_SUCCESS,
        TAG_BIND_RESPONSE,
        TAG_SEARCH_ENTRY,
        ber,
    )

    def message(message_id, tag, body):
        return ber(0x30, ber(0x02, bytes((message_id,))) + ber(tag, body))

    bind = message(1, TAG_BIND_RESPONSE,
                   ber(0x0A, bytes((RESULT_SUCCESS,))) + ber(0x04, b"") + ber(0x04, b""))
    values = b"".join(ber(0x04, name.encode()) for name in naming_contexts)
    attribute = ber(0x30, ber(0x04, b"namingContexts") + ber(0x31, values))
    search = message(2, TAG_SEARCH_ENTRY, ber(0x04, b"") + ber(0x30, attribute))
    return bind, search


def test_the_directory_domain_comes_from_the_dc_only_naming_context():
    context = _context(_LDAP)
    plugin = LdapDirectoryDomainPlugin(probe=_LdapProbe(_ldap_replies(
        "CN=Configuration,DC=empresa,DC=local", "DC=Empresa,DC=Local")))
    assert plugin.run(context) is True
    assert context.evidence == {"domain": "empresa.local"}


def test_a_directory_without_a_domain_is_not_reported():
    plugin = LdapDirectoryDomainPlugin(probe=_LdapProbe(_ldap_replies("o=empresa")))
    assert plugin.run(_context(_LDAP)) is False


def test_the_directory_domain_is_reported_once_per_host():
    """Un controlador de dominio abre el 389 y el catálogo global en el 3268:
    informa el 389."""
    global_catalog = Service(3268, "tcp", "globalcatLDAP")
    probe = _LdapProbe(_ldap_replies("DC=empresa,DC=local"))
    assert LdapDirectoryDomainPlugin(probe=probe).run(_context(global_catalog, (_LDAP,))) is False
    assert probe.calls == 0


# ============================================================ el runtime


def test_the_title_names_the_asset():
    plugins = default_script_plugins()
    plugins["smb-host-identity"] = SmbHostIdentityPlugin(probe=_SmbProbe({
        "netbios_computer_name": "WIN-SRV01", "netbios_domain_name": "CORP"}))
    checks = [check for check in load_checks() if check.id == "smb-host-identity"]
    findings = CheckRuntime(checks, lambda *a: None, script_plugins=plugins).run("10.0.0.5", [_SMB])
    assert [finding["title"] for finding in findings] == [
        "SMB: el equipo se identifica como WIN-SRV01 (dominio CORP)"]
    assert findings[0]["severity"] == "INFO"
    assert findings[0]["category"] == "host_identity"


def test_a_placeholder_without_evidence_stays_visible():
    assert render_title("Equipo {identity}", {}) == "Equipo {identity}"
    assert render_title("Sin marcadores", {"identity": "X"}) == "Sin marcadores"


def test_host_identity_is_an_event_category_and_not_a_risk():
    """No es un problema que se abra y se corrija: no entra en el ciclo de vida."""
    from src.modules.features.themis.managers.lybra.engine import LybraEngineManager

    assert "host_identity" in CHECK_CATEGORIES
    assert "host_identity" in EVENT_CHECK_CATEGORIES
    # pylint: disable=protected-access
    assert set(EVENT_CHECK_CATEGORIES) <= LybraEngineManager._EVENT_CATEGORIES
