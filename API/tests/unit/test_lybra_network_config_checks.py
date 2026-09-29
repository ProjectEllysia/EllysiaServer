"""Los checks de configuración de red.

Cubren la parte de la superficie que no se resuelve escribiendo dissectors: una
configuración insegura no tiene CVE y no aparece por la vía de la versión.

Aquí van cinco: Telnet activo, VNC sin autenticación (plugins
script), y relay/STARTTLS de SMTP y FTP sin cifrado (checks network, sobre el
``NetworkSession`` real — la misma regla del resto del fichero: un doble por
encima de la sesión se inventaría capacidades que el transporte real no tiene).
"""

import pytest

from src.modules.features.themis.lybra.checks import (
    CheckRuntime,
    NetworkProbe,
    Service,
    load_checks,
)
from src.modules.features.themis.lybra.fingerprinting.telnet import TelnetProbe
from src.modules.features.themis.lybra.fingerprinting.vnc import VncProbe

pytestmark = pytest.mark.unit

_SMTP = Service(25, "tcp", "smtp", "", "", None)
_FTP = Service(21, "tcp", "ftp", "", "", None)
_TELNET = Service(23, "tcp", "telnet", "", "", None)
_VNC = Service(5900, "tcp", "vnc", "", "", None)
_CHECKS = load_checks()


class _FakeNetSocket:
    """Socket falso a nivel de bytes: saludo en el buffer, respuestas tras cada
    escritura (el mismo modelo que ``test_lybra_checks``)."""

    def __init__(self, greeting=b"", replies=()):
        self._buffer = greeting
        self._replies = list(replies)
        self.sent = b""

    def recv(self, size):
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def sendall(self, data):
        self.sent += data
        if self._replies:
            self._buffer += self._replies.pop(0)

    def close(self):
        pass


def _fired(check_id, sock, service):
    # Sólo el check bajo prueba: los checks del mismo servicio comparten la
    # sesión de red (la caché de sondas), así que ejecutar el feed
    # entero dejaría a otro check consumiendo el socket antes que éste. Aislarlo
    # es lo que se quiere medir aquí — el comportamiento de un check, no la
    # orquestación.
    plain_id = check_id.split(":")[1].split("@")[0]
    only = [c for c in _CHECKS if c.id == plain_id]
    runtime = CheckRuntime(
        only, lambda *a: None,
        network_open=NetworkProbe(connect=lambda address, timeout: sock).open)
    return [f for f in runtime.run("h", [service]) if f["check_id"] == check_id]


# =============================================================== Telnet


def _telnet_plugin(reply):
    from src.modules.features.themis.lybra.script_checks import TelnetEnabledPlugin

    class _Sock:
        def settimeout(self, _t):
            pass

        def recv(self, _n):
            return reply

        def close(self):
            pass

    probe = TelnetProbe(connect=lambda address, timeout: _Sock())
    return TelnetEnabledPlugin(probe=probe)


class _Ctx:
    def __init__(self, service):
        self.target = "10.0.0.5"
        self.service = service
        self.sibling_services = ()

    def acquire(self):
        pass


def test_telnet_is_flagged_when_the_service_opens_with_iac():
    """Un servidor Telnet abre negociando opciones: el primer byte es IAC
    (0xFF). Esa firma es lo que dispara."""
    assert _telnet_plugin(b"\xff\xfb\x01").run(_Ctx(_TELNET)) is True


def test_a_mute_or_non_telnet_port_23_is_not_flagged():
    """Un puerto 23 abierto no basta: podría ser cualquier servicio mudo en un
    puerto reutilizado. Sin la firma del protocolo, no hay hallazgo."""
    assert _telnet_plugin(b"").run(_Ctx(_TELNET)) is False
    assert _telnet_plugin(b"SSH-2.0-x").run(_Ctx(_TELNET)) is False


def test_the_telnet_check_is_registered_and_wired():
    from src.modules.features.themis.lybra.script_checks import default_script_plugins

    check = next(c for c in _CHECKS if c.id == "telnet-enabled")
    assert check.service == "telnet" and check.severity == "HIGH"
    assert check.script in default_script_plugins()


# ================================================================== VNC


def _vnc_plugin(types):
    from src.modules.features.themis.lybra.script_checks import VncNoAuthenticationPlugin

    class _Probe(VncProbe):
        def security_types(self, host, port=5900):
            return types

    return VncNoAuthenticationPlugin(probe=_Probe())


def test_vnc_without_authentication_is_flagged():
    """El tipo de seguridad 1 es None (RFC 6143): entrar sin contraseña."""
    assert _vnc_plugin([1, 2]).run(_Ctx(_VNC)) is True


def test_vnc_that_only_offers_authentication_is_not_flagged():
    assert _vnc_plugin([2]).run(_Ctx(_VNC)) is False


def test_a_vnc_that_rejected_or_was_unreadable_is_not_flagged():
    assert _vnc_plugin([]).run(_Ctx(_VNC)) is False       # recuento 0: rechazo
    assert _vnc_plugin(None).run(_Ctx(_VNC)) is False      # no era RFB


# ================================================================= SMTP


_SMTP_BANNER = b"220 mail.example.com ESMTP Postfix\r\n"


def test_an_open_relay_is_flagged_when_the_external_rcpt_is_accepted():
    sock = _FakeNetSocket(
        greeting=_SMTP_BANNER,
        replies=[
            b"250-mail.example.com\r\n250 STARTTLS\r\n",   # EHLO
            b"250 2.1.0 Ok\r\n",                           # MAIL FROM
            b"250 2.1.5 Ok\r\n",                           # RCPT TO externo aceptado
        ],
    )
    assert _fired("lybra:smtp-open-relay@1", sock, _SMTP)


def test_a_closed_relay_that_rejects_the_external_rcpt_is_not_flagged():
    sock = _FakeNetSocket(
        greeting=_SMTP_BANNER,
        replies=[
            b"250-mail.example.com\r\n250 STARTTLS\r\n",
            b"250 2.1.0 Ok\r\n",
            b"554 5.7.1 Relay access denied\r\n",          # rechaza el relay
        ],
    )
    assert not _fired("lybra:smtp-open-relay@1", sock, _SMTP)


def test_a_server_without_starttls_is_flagged():
    sock = _FakeNetSocket(
        greeting=_SMTP_BANNER,
        replies=[b"250-mail.example.com\r\n250 SIZE 10240000\r\n250 HELP\r\n"],
    )
    assert _fired("lybra:smtp-no-starttls@1", sock, _SMTP)


def test_a_server_that_announces_starttls_is_not_flagged():
    sock = _FakeNetSocket(
        greeting=_SMTP_BANNER,
        replies=[b"250-mail.example.com\r\n250-STARTTLS\r\n250 HELP\r\n"],
    )
    assert not _fired("lybra:smtp-no-starttls@1", sock, _SMTP)


# ================================================================== FTP


def test_ftp_without_tls_is_flagged_when_auth_tls_is_refused():
    sock = _FakeNetSocket(
        greeting=b"220 (vsFTPd 3.0.3)\r\n",
        replies=[b"500 Unknown command.\r\n"],             # AUTH TLS rechazado
    )
    assert _fired("lybra:ftp-no-tls@1", sock, _FTP)


def test_ftp_with_ftps_support_is_not_flagged():
    sock = _FakeNetSocket(
        greeting=b"220 (vsFTPd 3.0.3)\r\n",
        replies=[b"234 Proceed with negotiation.\r\n"],    # AUTH TLS aceptado
    )
    assert not _fired("lybra:ftp-no-tls@1", sock, _FTP)


# ============================================= la brecha G1, contada entera


def test_at_least_five_network_config_findings_are_reachable():
    """El criterio de cierre: un host con SMB, FTP, SMTP y una base de datos
    abiertos alcanza al menos cinco hallazgos de configuración de red. Aquí se
    comprueba el inventario —que los checks existen, en su familia— no la red."""
    network_config = {c.id for c in _CHECKS if c.category in ("network_config",)}
    expected = {"smbv1-enabled", "smb-signing-not-required",
                "telnet-enabled", "smtp-open-relay", "smtp-no-starttls", "ftp-no-tls",
                "ftp-cleartext-login-allowed",
                "dns-open-resolver", "ntp-monlist-enabled"}
    assert expected <= network_config
    assert len(network_config) >= 5


# ======================================= FTP que ofrece TLS pero no lo exige
#
# El caso que OpenVAS puntuó como MEDIA en el contraste de campo: el servidor
# soporta AUTH TLS, así que `ftp-no-tls` no salta, pero acepta un USER en claro.


def test_ftp_asking_for_a_password_in_cleartext_is_flagged():
    sock = _FakeNetSocket(
        greeting=b"220 ProFTPD Server (ProFTPD) [192.0.2.1]\r\n",
        replies=[b"331 Password required for lybra-cleartext-probe\r\n"],
    )
    assert _fired("lybra:ftp-cleartext-login-allowed@1", sock, _FTP)
    # Nunca se envía la contraseña: el 331 ya es la prueba.
    assert b"PASS" not in sock.sent


def test_ftp_that_enforces_tls_is_not_flagged():
    sock = _FakeNetSocket(
        greeting=b"220 (vsFTPd 3.0.3)\r\n",
        replies=[b"530 Non-anonymous sessions must use encryption.\r\n"],
    )
    assert not _fired("lybra:ftp-cleartext-login-allowed@1", sock, _FTP)


# =========================================== el TLS del FTP, tras AUTH TLS


class _FtpSocket:
    """Socket falso de un FTP: saludo, y la respuesta a AUTH TLS."""

    def __init__(self, auth_reply):
        self._pending = [b"220-Bienvenido\r\n220 ProFTPD\r\n", auth_reply]
        self.sent = b""

    def recv(self, _size):
        return self._pending.pop(0) if self._pending else b""

    def sendall(self, data):
        self.sent += data

    def close(self):
        pass


def test_the_ftp_upgrade_accepts_234_and_rejects_anything_else():
    from src.modules.features.themis.lybra.fingerprinting.tls import _upgrade_ftp

    accepted = _FtpSocket(b"234 AUTH TLS successful\r\n")
    assert _upgrade_ftp(accepted) is True
    assert accepted.sent == b"AUTH TLS\r\n"
    assert _upgrade_ftp(_FtpSocket(b"500 AUTH not understood\r\n")) is False


def test_an_ftp_service_gets_its_tls_audited_through_auth_tls():
    calls = []

    def tls_fetch(host, port, starttls=None):
        calls.append((port, starttls))
        return None

    tls_checks = [c for c in _CHECKS if c.type == "tls"]
    CheckRuntime(tls_checks, lambda *a: None, tls_fetch=tls_fetch).run("h", [_FTP])

    assert calls == [(21, "ftp")]


# ========================================================== IMAP y POP3

_IMAP = Service(143, "tcp", "imap", "", "", None)
_POP3 = Service(110, "tcp", "pop3", "", "", None)
_IMAP_GREETING = b"* OK [CAPABILITY IMAP4rev1 LITERAL+] Dovecot ready.\r\n"
_POP3_GREETING = b"+OK Dovecot ready.\r\n"


def test_an_imap_without_starttls_is_flagged():
    sock = _FakeNetSocket(
        greeting=_IMAP_GREETING,
        replies=[b"* CAPABILITY IMAP4rev1 LITERAL+ AUTH=PLAIN\r\na1 OK Capability completed.\r\n"],
    )
    assert _fired("lybra:imap-no-starttls@1", sock, _IMAP)
    assert sock.sent == b"a1 CAPABILITY\r\n"


def test_an_imap_that_announces_starttls_is_not_flagged():
    sock = _FakeNetSocket(
        greeting=_IMAP_GREETING,
        replies=[b"* CAPABILITY IMAP4rev1 STARTTLS LOGINDISABLED\r\na1 OK Capability completed.\r\n"],
    )
    assert not _fired("lybra:imap-no-starttls@1", sock, _IMAP)


def test_an_imap_that_rejects_capability_is_not_flagged():
    """Sin la lista de capacidades no hay evidencia de que falte STARTTLS."""
    sock = _FakeNetSocket(greeting=_IMAP_GREETING, replies=[b"a1 BAD Unknown command\r\n"])
    assert not _fired("lybra:imap-no-starttls@1", sock, _IMAP)


def test_a_pop3_without_stls_is_flagged():
    sock = _FakeNetSocket(
        greeting=_POP3_GREETING,
        replies=[b"+OK Capability list follows\r\nTOP\r\nUSER\r\nUIDL\r\n.\r\n"],
    )
    assert _fired("lybra:pop3-no-starttls@1", sock, _POP3)
    assert sock.sent == b"CAPA\r\n"


def test_a_pop3_that_announces_stls_is_not_flagged():
    """Señuelo: STLS está en la lista, pero no en la primera línea; sólo se ve
    si se lee la respuesta entera hasta el punto."""
    sock = _FakeNetSocket(
        greeting=_POP3_GREETING,
        replies=[b"+OK Capability list follows\r\nTOP\r\nUSER\r\nSTLS\r\n.\r\n"],
    )
    assert not _fired("lybra:pop3-no-starttls@1", sock, _POP3)


def test_a_pop3_without_capa_is_not_flagged():
    sock = _FakeNetSocket(greeting=_POP3_GREETING, replies=[b"-ERR Unknown command\r\n"])
    assert not _fired("lybra:pop3-no-starttls@1", sock, _POP3)


@pytest.mark.parametrize("service", [
    Service(993, "tcp", "imaps", "", "", None),
    Service(993, "tcp", "imap", "", "", None),
    Service(995, "tcp", "pop3s", "", "", None),
    Service(995, "tcp", "pop3", "", "", None),
])
def test_the_implicit_tls_mail_ports_are_not_asked_for_starttls(service):
    """El 993 y el 995 cifran desde el primer byte: hablarles en claro sólo
    esperaría hasta el plazo de lectura."""
    sock = _FakeNetSocket(greeting=b"", replies=[])
    checks = [c for c in _CHECKS if c.id in {"imap-no-starttls", "pop3-no-starttls"}]
    runtime = CheckRuntime(
        checks, lambda *a: None,
        network_open=NetworkProbe(connect=lambda address, timeout: sock).open)
    assert runtime.run("h", [service]) == []
    assert sock.sent == b""


def test_the_dot_terminated_read_stops_at_the_lone_dot_and_keeps_the_rest():
    from src.modules.features.themis.lybra.checks import NetworkSession

    sock = _FakeNetSocket(greeting=b"+OK list\r\nUSER\r\n.\r\n+OK next\r\n")
    session = NetworkSession(sock)
    first = session.exchange(None, read="dot-terminated")
    assert first.body.endswith(".")
    assert "next" not in first.body
    assert session.exchange(None, read="line").body == "+OK next"


# ============================== el certificado del correo, tras su paso a TLS


class _ScriptedSocket:
    """Socket falso de un servidor que habla por turnos: el saludo está en el
    buffer al conectar y cada escritura añade la siguiente respuesta, como un
    servidor real que espera a cada comando."""

    def __init__(self, greeting, *replies):
        self._buffer = greeting
        self._replies = list(replies)
        self.sent = b""

    def recv(self, size):
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def sendall(self, data):
        self.sent += data
        if self._replies:
            self._buffer += self._replies.pop(0)

    def close(self):
        pass


def test_the_smtp_upgrade_says_ehlo_then_starttls_and_wants_a_220():
    from src.modules.features.themis.lybra.fingerprinting.tls import _upgrade_smtp

    accepted = _ScriptedSocket(b"220 mail.example.com ESMTP\r\n",
                               b"250-mail.example.com\r\n250 STARTTLS\r\n",
                               b"220 2.0.0 Ready to start TLS\r\n")
    assert _upgrade_smtp(accepted) is True
    assert accepted.sent == b"EHLO lybra.local\r\nSTARTTLS\r\n"
    refused = _ScriptedSocket(b"220 mail.example.com ESMTP\r\n", b"250 mail.example.com\r\n",
                              b"502 5.5.1 Unrecognized command\r\n")
    assert _upgrade_smtp(refused) is False


def test_the_imap_upgrade_skips_untagged_lines_and_wants_a_tagged_ok():
    from src.modules.features.themis.lybra.fingerprinting.tls import _upgrade_imap

    accepted = _ScriptedSocket(b"* OK Dovecot ready.\r\n",
                               b"* NOTE ignored\r\na1 OK Begin TLS negotiation now.\r\n")
    assert _upgrade_imap(accepted) is True
    assert accepted.sent == b"a1 STARTTLS\r\n"
    assert _upgrade_imap(_ScriptedSocket(b"* OK ready\r\n", b"a1 BAD Unknown command\r\n")) is False


def test_the_pop3_upgrade_sends_stls_and_wants_ok():
    from src.modules.features.themis.lybra.fingerprinting.tls import _upgrade_pop3

    accepted = _ScriptedSocket(b"+OK Dovecot ready.\r\n", b"+OK Begin TLS negotiation\r\n")
    assert _upgrade_pop3(accepted) is True
    assert accepted.sent == b"STLS\r\n"
    assert _upgrade_pop3(_ScriptedSocket(b"+OK ready\r\n", b"-ERR Unknown command\r\n")) is False


def test_a_text_line_read_stops_before_the_tls_handshake_bytes():
    """Lo que venga tras la respuesta al paso a TLS es del saludo TLS, y no se
    puede consumir aquí."""
    from src.modules.features.themis.lybra.fingerprinting.tls import _read_text_line

    sock = _ScriptedSocket(b"+OK go ahead\r\n\x16\x03\x01")
    assert _read_text_line(sock) == "+OK go ahead"
    assert sock.recv(3) == b"\x16\x03\x01"


@pytest.mark.parametrize("service, starttls", [
    (Service(25, "tcp", "smtp", "", "", None), "smtp"),
    (Service(587, "tcp", "submission", "", "", None), "smtp"),
    (Service(143, "tcp", "imap", "", "", None), "imap"),
    (Service(110, "tcp", "pop3", "", "", None), "pop3"),
    (Service(21, "tcp", "ftp", "", "", None), "ftp"),
    (Service(465, "tcp", "smtps", "", "", None), None),
    (Service(993, "tcp", "imaps", "", "", None), None),
    (Service(995, "tcp", "pop3s", "", "", None), None),
    (Service(990, "tcp", "ftp", "", "", None), None),
    (Service(443, "tcp", "https", "", "", None), None),
])
def test_each_service_gets_its_certificate_audited_the_right_way(service, starttls):
    """Los que empiezan en claro, tras su paso a TLS; los que cifran desde el
    primer byte, directamente."""
    calls = []

    def tls_fetch(host, port, starttls=None):
        calls.append((port, starttls))
        return None

    tls_checks = [c for c in _CHECKS if c.type == "tls"]
    CheckRuntime(tls_checks, lambda *a: None, tls_fetch=tls_fetch).run("h", [service])
    assert calls == [(service.port, starttls)]


def test_ssh_or_a_database_gets_no_certificate_audit():
    calls = []
    tls_checks = [c for c in _CHECKS if c.type == "tls"]
    CheckRuntime(tls_checks, lambda *a: None,
                 tls_fetch=lambda *a, **k: calls.append(a)).run(
        "h", [Service(22, "tcp", "ssh", "", "", None), Service(5432, "tcp", "postgresql", "", "", None)])
    assert calls == []


def _certificate(self_signed):
    from src.modules.features.themis.lybra.fingerprinting.tls import TlsInfo
    return TlsInfo(protocol="TLSv1.3", cipher="TLS_AES_256_GCM_SHA384", subject_cn="mail.example.com",
                   issuer_cn="mail.example.com" if self_signed else "R11", self_signed=self_signed,
                   expired=False, days_until_expiry=200, names=("mail.example.com",))


def test_a_self_signed_smtp_certificate_fires_the_same_check_as_https_and_says_so():
    tls_checks = [c for c in _CHECKS if c.type == "tls"]
    findings = CheckRuntime(tls_checks, lambda *a: None,
                            tls_fetch=lambda host, port, starttls=None: _certificate(True)).run(
        "h", [_SMTP])
    self_signed = [f for f in findings if f["check_id"].startswith("lybra:tls-self-signed-cert@")]
    assert len(self_signed) == 1
    assert "SMTP" in self_signed[0]["title"] and "STARTTLS" in self_signed[0]["title"]


def test_a_valid_smtp_certificate_fires_nothing():
    """Señuelo: STARTTLS con un certificado válido no da ningún aviso de certificado."""
    tls_checks = [c for c in _CHECKS if c.type == "tls"]
    findings = CheckRuntime(tls_checks, lambda *a: None,
                            tls_fetch=lambda host, port, starttls=None: _certificate(False)).run(
        "h", [_SMTP])
    assert findings == []


def test_an_https_certificate_keeps_its_plain_title():
    tls_checks = [c for c in _CHECKS if c.id == "tls-self-signed-cert"]
    findings = CheckRuntime(tls_checks, lambda *a: None,
                            tls_fetch=lambda host, port, starttls=None: _certificate(True)).run(
        "h", [Service(443, "tcp", "https", "", "", None)])
    assert findings[0]["title"] == tls_checks[0].finding["title"]


# ============================================ WinRM con Basic y sin TLS


class _WinrmProbe:
    """Sonda HTTP falsa: contesta siempre lo mismo y apunta lo que se le pidió."""

    def __init__(self, response):
        self.response = response
        self.requests = []

    def fetch(self, host, port, method, path, body=None, headers=None):
        self.requests.append((port, method, path))
        return self.response


def _winrm_run(response):
    from src.modules.features.themis.lybra.checks import ScriptContext
    from src.modules.features.themis.lybra.script_checks import WinrmBasicAuthCleartextPlugin

    probe = _WinrmProbe(response)
    context = ScriptContext(target="10.0.0.5", service=Service(5985, "tcp", "wsman", "", "", None))
    return WinrmBasicAuthCleartextPlugin(probe=probe).run(context), context, probe


def _winrm_401(authenticate, server="Microsoft-HTTPAPI/2.0", scheme="http"):
    from src.modules.features.themis.lybra.checks import Response
    return Response(401, "", {"www-authenticate": authenticate, "server": server},
                    requested_scheme=scheme)


def test_a_winrm_offering_basic_without_tls_is_flagged():
    fired, context, probe = _winrm_run(_winrm_401('Negotiate\nBasic realm="WSMAN"'))
    assert fired is True
    assert probe.requests == [(5985, "POST", "/wsman")]
    assert "Basic" in context.evidence["wwwAuthenticate"]


def test_a_winrm_with_only_kerberos_and_negotiate_is_not_flagged():
    """Señuelo: el 5985 sigue abierto, pero Basic está deshabilitado."""
    fired, _context, _probe = _winrm_run(_winrm_401("Negotiate\nKerberos"))
    assert fired is False


def test_another_http_server_asking_for_basic_is_not_winrm():
    """Un servidor web cualquiera en el 5985 que pida Basic no es WinRM."""
    fired, _context, _probe = _winrm_run(_winrm_401('Basic realm="intranet"', server="nginx"))
    assert fired is False


def test_the_linux_implementation_is_recognised_by_its_realm():
    fired, _context, _probe = _winrm_run(_winrm_401('Basic realm="WSMAN"', server="OMI"))
    assert fired is True


def test_basic_over_tls_is_not_flagged():
    fired, _context, _probe = _winrm_run(_winrm_401('Basic realm="WSMAN"', scheme="https"))
    assert fired is False


def test_a_winrm_that_does_not_answer_is_not_flagged():
    fired, _context, _probe = _winrm_run(None)
    assert fired is False


def test_winrm_is_only_asked_on_its_cleartext_port():
    from src.modules.features.themis.lybra.script_checks import WinrmBasicAuthCleartextPlugin

    plugin = WinrmBasicAuthCleartextPlugin(probe=_WinrmProbe(None))
    assert plugin.applies(Service(5985, "tcp", "", "", "", None))
    assert plugin.applies(Service(15985, "tcp", "wsman", "", "", None))
    assert not plugin.applies(Service(5986, "tcp", "", "", "", None))


def test_the_winrm_check_is_registered_and_wired_to_its_feed_entry():
    from src.modules.features.themis.lybra.script_checks import default_script_plugins

    check = next(c for c in _CHECKS if c.id == "winrm-basic-auth-cleartext")
    assert check.mode == "safe" and check.service == "winrm"
    assert check.script in default_script_plugins()
