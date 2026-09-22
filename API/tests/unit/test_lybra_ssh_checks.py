"""Checks SSH sobre el ``KEXINIT``: algoritmos débiles y Terrapin.

El servidor SSH envía en claro, al conectar, la lista de algoritmos que acepta.
Estos tests construyen ese mensaje byte a byte (el mismo formato que parsea
``fingerprinting.ssh.parse_kexinit``) y comprueban qué concluye cada plugin,
cómo viaja la evidencia y cómo una refutación desmiente un hallazgo por versión.
"""

import struct

import pytest

from src.modules.features.themis.lybra import apply_refutations, split_refutations
from src.modules.features.themis.lybra.checks import (
    Check,
    CheckRuntime,
    ScriptContext,
    Service,
    load_checks,
    validate_checks,
)
from src.modules.features.themis.lybra.script_checks import (
    SshTerrapinPlugin,
    SshWeakAlgorithmsPlugin,
    _KexinitCache,
    default_script_plugins,
    is_vulnerable_to_terrapin,
    weak_ssh_algorithms,
)

pytestmark = pytest.mark.unit

_SSH = Service(22, "tcp", "ssh", "OpenSSH", "9.6p1", None)
_TERRAPIN = "CVE-2023-48795"

# Lo que anunciaba el OpenSSH 9.6p1 de Ubuntu 24.04 del contraste de campo:
# strict kex activado y umac-64 entre los MACs.
_UBUNTU_24_04 = {
    "kex_algorithms": [
        "sntrup761x25519-sha512@openssh.com", "curve25519-sha256", "ecdh-sha2-nistp256",
        "diffie-hellman-group-exchange-sha256", "diffie-hellman-group14-sha256",
        "ext-info-s", "kex-strict-s-v00@openssh.com"],
    "server_host_key_algorithms": ["rsa-sha2-512", "rsa-sha2-256", "ecdsa-sha2-nistp256", "ssh-ed25519"],
    "encryption_algorithms_client_to_server": [
        "chacha20-poly1305@openssh.com", "aes128-ctr", "aes256-gcm@openssh.com"],
    "encryption_algorithms_server_to_client": [
        "chacha20-poly1305@openssh.com", "aes128-ctr", "aes256-gcm@openssh.com"],
    "mac_algorithms_client_to_server": [
        "umac-64-etm@openssh.com", "hmac-sha2-256-etm@openssh.com", "umac-64@openssh.com", "hmac-sha1"],
    "mac_algorithms_server_to_client": [
        "umac-64-etm@openssh.com", "hmac-sha2-256-etm@openssh.com", "umac-64@openssh.com", "hmac-sha1"],
}
_FIELDS = (
    "kex_algorithms", "server_host_key_algorithms",
    "encryption_algorithms_client_to_server", "encryption_algorithms_server_to_client",
    "mac_algorithms_client_to_server", "mac_algorithms_server_to_client",
    "compression_algorithms_client_to_server", "compression_algorithms_server_to_client",
    "languages_client_to_server", "languages_server_to_client",
)


def _kexinit_payload(lists):
    """Un ``SSH_MSG_KEXINIT`` en crudo: código, cookie, diez name-lists y cola."""
    payload = bytes([20]) + b"\x00" * 16
    for field in _FIELDS:
        text = ",".join(lists.get(field, [])).encode("ascii")
        payload += struct.pack(">I", len(text)) + text
    return payload + b"\x00" + b"\x00\x00\x00\x00"


class _FakeSshProbe:
    """Sonda que devuelve un ``KEXINIT`` fijo y cuenta las conexiones."""

    def __init__(self, lists):
        self.calls = 0
        self._payload = _kexinit_payload(lists)

    def fetch(self, host, port):
        self.calls += 1
        return "SSH-2.0-OpenSSH_9.6p1", self._payload


def _without_strict_kex(lists):
    return {**lists, "kex_algorithms": [k for k in lists["kex_algorithms"]
                                        if k != "kex-strict-s-v00@openssh.com"]}


# ============================================================ algoritmos débiles


def test_umac_64_is_the_only_weak_family_of_a_modern_openssh():
    """Es lo que OpenVAS reportó sobre ese servidor, y nada más."""
    assert weak_ssh_algorithms(_UBUNTU_24_04, "mac") == ["umac-64-etm@openssh.com", "umac-64@openssh.com"]
    assert weak_ssh_algorithms(_UBUNTU_24_04, "encryption") == []
    assert weak_ssh_algorithms(_UBUNTU_24_04, "kex") == []
    assert weak_ssh_algorithms(_UBUNTU_24_04, "host-key") == []


def test_legacy_algorithms_are_flagged_family_by_family():
    legacy = {
        "kex_algorithms": ["diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1", "curve25519-sha256"],
        "server_host_key_algorithms": ["ssh-dss", "ssh-rsa", "ssh-ed25519"],
        "encryption_algorithms_client_to_server": ["aes128-cbc", "3des-cbc", "arcfour256", "aes128-ctr"],
        "mac_algorithms_client_to_server": ["hmac-md5", "hmac-sha1-96", "hmac-sha2-256"],
    }
    assert weak_ssh_algorithms(legacy, "kex") == ["diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1"]
    assert weak_ssh_algorithms(legacy, "host-key") == ["ssh-dss", "ssh-rsa"]
    assert weak_ssh_algorithms(legacy, "encryption") == ["aes128-cbc", "3des-cbc", "arcfour256"]
    assert weak_ssh_algorithms(legacy, "mac") == ["hmac-md5", "hmac-sha1-96"]


def test_the_plugin_puts_the_weak_algorithms_in_the_evidence():
    plugin = SshWeakAlgorithmsPlugin("mac", _KexinitCache(_FakeSshProbe(_UBUNTU_24_04)))
    context = ScriptContext(target="h", service=_SSH)

    assert plugin.run(context) is True
    assert context.evidence == {"family": "mac",
                                "weak_algorithms": ["umac-64-etm@openssh.com", "umac-64@openssh.com"]}


def test_every_ssh_plugin_shares_a_single_connection():
    probe = _FakeSshProbe(_UBUNTU_24_04)
    cache = _KexinitCache(probe)
    for family in ("mac", "encryption", "kex", "host-key"):
        SshWeakAlgorithmsPlugin(family, cache).run(ScriptContext(target="h", service=_SSH))
    SshTerrapinPlugin(False, cache).run(ScriptContext(target="h", service=_SSH))

    assert probe.calls == 1


def test_no_kexinit_means_no_finding():
    class _Down:
        def fetch(self, host, port):
            return None

    plugin = SshWeakAlgorithmsPlugin("mac", _KexinitCache(_Down()))
    assert plugin.run(ScriptContext(target="h", service=_SSH)) is False


# ===================================================================== Terrapin


def test_strict_kex_rules_out_terrapin():
    assert is_vulnerable_to_terrapin(_UBUNTU_24_04) is False


def test_chacha20_without_strict_kex_is_vulnerable():
    assert is_vulnerable_to_terrapin(_without_strict_kex(_UBUNTU_24_04)) is True


def test_etm_with_cbc_without_strict_kex_is_vulnerable():
    lists = {"kex_algorithms": ["curve25519-sha256"],
             "encryption_algorithms_client_to_server": ["aes128-cbc"],
             "mac_algorithms_client_to_server": ["hmac-sha2-256-etm@openssh.com"]}
    assert is_vulnerable_to_terrapin(lists) is True


def test_without_an_affected_mode_there_is_no_terrapin():
    lists = {"kex_algorithms": ["curve25519-sha256"],
             "encryption_algorithms_client_to_server": ["aes256-gcm@openssh.com"],
             "mac_algorithms_client_to_server": ["hmac-sha2-256"]}
    assert is_vulnerable_to_terrapin(lists) is False


def _runtime_for(lists):
    """El runtime con el feed real y los plugins SSH sobre un KEXINIT fijo."""
    plugins = default_script_plugins()
    cache = _KexinitCache(_FakeSshProbe(lists))
    plugins["ssh-terrapin-confirm"] = SshTerrapinPlugin(True, cache)
    plugins["ssh-terrapin-refute"] = SshTerrapinPlugin(False, cache)
    ssh_checks = [check for check in load_checks() if check.id.startswith("ssh-terrapin")]
    return CheckRuntime(ssh_checks, lambda *a: None, script_plugins=plugins)


def test_the_refuter_runs_only_when_the_version_proposed_terrapin():
    runtime = _runtime_for(_UBUNTU_24_04)
    assert runtime.run("h", [_SSH], proposed_cves=frozenset()) == []


def test_strict_kex_produces_a_refutation_mark_and_no_confirmation():
    findings = _runtime_for(_UBUNTU_24_04).run("h", [_SSH], proposed_cves=frozenset({_TERRAPIN}))

    assert [f["check_id"] for f in findings] == ["lybra:ssh-terrapin-refute@1"]
    assert findings[0]["_refutes"] == _TERRAPIN


def test_a_vulnerable_configuration_confirms_the_cve():
    findings = _runtime_for(_without_strict_kex(_UBUNTU_24_04)).run(
        "h", [_SSH], proposed_cves=frozenset({_TERRAPIN}))

    assert [f["check_id"] for f in findings] == ["lybra:ssh-terrapin-confirm@1"]
    assert findings[0]["cve_ids"] == [_TERRAPIN]
    assert "_refutes" not in findings[0]


# ================================================================== refutación


def _version_finding(port=22, cve=_TERRAPIN):
    return {"category": "outdated_software", "port": port, "cve_ids": [cve],
            "state": "open", "confirmed": False, "check_id": None}


def test_split_refutations_keeps_marks_out_of_the_findings():
    mark = {"port": 22, "_refutes": _TERRAPIN, "check_id": "lybra:ssh-terrapin-refute@1"}
    other = {"port": 22, "check_id": "lybra:ssh-weak-mac@1"}

    assert split_refutations([mark, other]) == ([other], [mark])


def test_a_refutation_marks_the_version_finding_of_the_same_port_as_fixed():
    same_port, other_port, other_cve = _version_finding(), _version_finding(port=2222), _version_finding(cve="CVE-2024-6387")
    mark = {"port": 22, "_refutes": _TERRAPIN, "check_id": "lybra:ssh-terrapin-refute@1"}

    apply_refutations([same_port, other_port, other_cve], [mark])

    assert same_port["state"] == "fixed"
    assert same_port["check_id"] == "lybra:ssh-terrapin-refute@1"
    assert other_port["state"] == "open"
    assert other_cve["state"] == "open"


# =============================================================== feed y evidencia


def test_a_check_cannot_both_confirm_and_refute():
    check = Check(id="x", version=1, type="script", category="vulnerability", severity="INFO",
                  service="ssh", mode="safe", requests=(), finding={}, script="ssh-weak-mac",
                  confirms=_TERRAPIN, refutes=_TERRAPIN)
    assert any("'confirms' y 'refutes'" in problem for problem in validate_checks([check]))


def test_the_script_evidence_travels_with_a_confirmed_finding():
    plugins = {"ssh-weak-mac": SshWeakAlgorithmsPlugin("mac", _KexinitCache(_FakeSshProbe(_UBUNTU_24_04)))}
    checks = [check for check in load_checks() if check.id == "ssh-weak-mac"]
    runtime = CheckRuntime(checks, lambda *a: None, script_plugins=plugins, capture_evidence=True)

    [finding] = runtime.run("h", [_SSH])

    assert finding["_evidence"]["kind"] == "script"
    assert finding["_evidence"]["payload"]["weak_algorithms"] == ["umac-64-etm@openssh.com", "umac-64@openssh.com"]
