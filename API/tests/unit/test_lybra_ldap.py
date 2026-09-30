"""El dissector de LDAP.

En una red corporativa con Active Directory el 389 está abierto siempre, y
LDAP tiene una consulta estándar y anónima diseñada para esto: el rootDSE.

La codificación es BER, la misma familia que el GetRequest de SNMP que ya se
construyó a mano. La diferencia práctica —y la que más tests tiene aquí— es
que hay que **leer** longitudes en forma larga, no sólo escribirlas en forma
corta: una lista de atributos pasa de 127 bytes con facilidad.
"""

import pytest

from src.modules.features.themis.lybra.checks import LDAPS_PORTS, is_ldap_service
from src.modules.features.themis.lybra.engine import Service
from src.modules.features.themis.lybra.fingerprinting.ldap import (
    RESULT_INAPPROPRIATE_AUTHENTICATION,
    RESULT_SUCCESS,
    ROOTDSE_ATTRIBUTES,
    TAG_BIND_RESPONSE,
    TAG_SEARCH_DONE,
    TAG_SEARCH_ENTRY,
    LdapDissector,
    LdapProbe,
    ber,
    build_anonymous_bind,
    build_naming_context_search,
    build_rootdse_search,
    encode_length,
    fingerprint_ldap,
    parse_bind_response,
    parse_search_entry,
    read_length,
    read_tlv,
    search_returned_entries,
)

pytestmark = pytest.mark.unit


def _message(message_id, operation_tag, operation_body):
    return ber(0x30, ber(0x02, bytes((message_id,))) + ber(operation_tag, operation_body))


def _bind_reply(result_code):
    body = ber(0x0A, bytes((result_code,))) + ber(0x04, b"") + ber(0x04, b"")
    return _message(1, TAG_BIND_RESPONSE, body)


def _attribute(name, values):
    return ber(0x30, ber(0x04, name.encode()) + ber(
        0x31, b"".join(ber(0x04, value.encode()) for value in values)))


def _search_reply(attributes):
    body = ber(0x04, b"") + ber(0x30, b"".join(
        _attribute(name, values) for name, values in attributes.items()))
    return _message(2, TAG_SEARCH_ENTRY, body)


def _search_done(result_code=RESULT_SUCCESS):
    """Un ``SearchResultDone`` sin ninguna entrada antes: la búsqueda no
    encontró nada que devolver (rechazada o simplemente vacía)."""
    body = ber(0x0A, bytes((result_code,))) + ber(0x04, b"") + ber(0x04, b"")
    return _message(3, TAG_SEARCH_DONE, body)


def _search_entry_reply(naming_context="DC=empresa,DC=local"):
    """Una respuesta con exactamente una entrada bajo ``naming_context`` —lo
    que confirma que la búsqueda anónima expone el directorio."""
    body = ber(0x04, naming_context.encode()) + ber(0x30, _attribute("objectClass", ["top"]))
    return _message(3, TAG_SEARCH_ENTRY, body) + _search_done()


OPENLDAP_ROOTDSE = _search_reply({
    "vendorName": ["Apache Software Foundation"],
    "vendorVersion": ["2.0.0"],
    "namingContexts": ["DC=empresa,DC=local"],
    "supportedSASLMechanisms": ["GSSAPI", "DIGEST-MD5"],
})

# Active Directory no publica vendorName ni vendorVersion: se identifica por
# sus contextos de nombres y por sus mecanismos.
ACTIVE_DIRECTORY_ROOTDSE = _search_reply({
    "namingContexts": ["DC=corp,DC=empresa,DC=com",
                       "CN=Configuration,DC=corp,DC=empresa,DC=com"],
    "supportedSASLMechanisms": ["GSSAPI", "GSS-SPNEGO", "EXTERNAL", "DIGEST-MD5"],
    "supportedLDAPVersion": ["3", "2"],
})


# ====================================================================== BER


@pytest.mark.parametrize("length, encoded", [
    (0, b"\x00"),
    (127, b"\x7f"),
    (128, b"\x81\x80"),
    (255, b"\x81\xff"),
    (256, b"\x82\x01\x00"),
])
def test_lengths_use_the_short_form_up_to_127_and_the_long_form_after(length, encoded):
    assert encode_length(length) == encoded


@pytest.mark.parametrize("length", [0, 1, 127, 128, 300, 70000])
def test_a_written_length_reads_back_the_same(length):
    encoded = encode_length(length)
    assert read_length(encoded, 0) == (length, len(encoded))


def test_a_long_form_value_survives_the_round_trip():
    """El caso que obliga a implementar la forma larga: un valor de más de 127
    bytes, que es lo normal en una respuesta de rootDSE."""
    payload = b"x" * 500
    tag, value, end = read_tlv(ber(0x04, payload), 0)
    assert (tag, value) == (0x04, payload)
    assert end == len(ber(0x04, payload))


@pytest.mark.parametrize("data", [
    b"",
    b"\x04",                       # etiqueta sin longitud
    b"\x04\x05ab",                 # valor truncado
    b"\x04\x82\x01",               # forma larga truncada
    b"\x04\x80",                   # longitud indefinida, no permitida en LDAP
])
def test_a_truncated_tlv_raises_instead_of_returning_garbage(data):
    with pytest.raises(ValueError):
        read_tlv(data, 0)


# ================================================ los mensajes que se envían


def test_the_anonymous_bind_is_the_exact_message_the_rfc_fixes():
    """El artefacto verificable a ojo de este módulo: un bind LDAPv3 anónimo
    son catorce bytes y no admite variantes."""
    assert build_anonymous_bind().hex() == "300c020101600702010304008000"


def test_the_anonymous_bind_carries_no_password():
    """No es un intento de adivinar credenciales: es la forma que el protocolo
    define para preguntar sin identificarse (RFC 4511 §4.2), y lo que se
    observa es si el servidor la acepta."""
    request = build_anonymous_bind()
    assert request.endswith(b"\x04\x00\x80\x00")     # nombre vacío, clave vacía


def test_the_rootdse_search_asks_only_for_the_attributes_it_consumes():
    request = build_rootdse_search()
    for name in ROOTDSE_ATTRIBUTES:
        assert name.encode() in request
    # Base vacía y ámbito baseObject: no se recorre ni una entrada del
    # directorio, sólo se pregunta por la raíz.
    assert b"objectClass" in request


def test_the_rootdse_search_needs_the_long_form_and_declares_it_right():
    """Con cinco atributos el mensaje pasa de 127 bytes, así que este mensaje
    es el que ejercita la forma larga al escribir."""
    request = build_rootdse_search()
    assert len(request) > 127
    tag, value, end = read_tlv(request, 0)
    assert tag == 0x30 and end == len(request) and value


def test_the_naming_context_search_targets_the_given_base_with_no_attributes():
    """Base el dominio publicado, ámbito singleLevel, tamaño 1 y el atributo
    especial ``1.1`` (RFC 4511 §4.5.1): comprobar que hay algo ahí debajo sin
    pedir su contenido."""
    request = build_naming_context_search("DC=empresa,DC=local")
    assert b"DC=empresa,DC=local" in request
    assert b"1.1" in request


def test_the_naming_context_search_is_a_well_formed_message():
    request = build_naming_context_search("DC=empresa,DC=local")
    tag, value, end = read_tlv(request, 0)
    assert tag == 0x30 and end == len(request) and value


# ========================================================== las respuestas


def test_a_successful_bind_is_read_as_success():
    assert parse_bind_response(_bind_reply(RESULT_SUCCESS)) == RESULT_SUCCESS


def test_a_rejected_bind_is_read_as_its_own_code():
    reply = _bind_reply(RESULT_INAPPROPRIATE_AUTHENTICATION)
    assert parse_bind_response(reply) == RESULT_INAPPROPRIATE_AUTHENTICATION


@pytest.mark.parametrize("data", [b"", b"\x30\x00", b"no es LDAP"])
def test_an_unreadable_bind_reply_yields_nothing(data):
    assert parse_bind_response(data) is None


def test_the_rootdse_attributes_are_read_with_all_their_values():
    attributes = parse_search_entry(ACTIVE_DIRECTORY_ROOTDSE)
    assert attributes["namingContexts"] == [
        "DC=corp,DC=empresa,DC=com", "CN=Configuration,DC=corp,DC=empresa,DC=com"]
    assert "GSSAPI" in attributes["supportedSASLMechanisms"]


def test_a_search_reply_that_is_not_ldap_yields_no_attributes():
    assert parse_search_entry(b"HTTP/1.1 400 Bad Request") == {}


# ========================================================== el fingerprint


def test_an_openldap_style_server_names_itself():
    fingerprint = fingerprint_ldap(_bind_reply(RESULT_SUCCESS), OPENLDAP_ROOTDSE)
    assert fingerprint.product == "Apache Software Foundation"
    assert fingerprint.version == "2.0.0"
    assert fingerprint.naming_contexts == ("DC=empresa,DC=local",)
    assert fingerprint.allows_anonymous_bind


def test_active_directory_is_identified_even_without_a_vendor_name():
    """AD no publica `vendorName` ni `vendorVersion`. Se le reconoce igual como
    servicio LDAP, y lo que aporta —el nombre de dominio— es el mejor
    identificador de activo que puede llegar a un informe."""
    fingerprint = fingerprint_ldap(_bind_reply(RESULT_SUCCESS), ACTIVE_DIRECTORY_ROOTDSE)
    assert fingerprint.product == "LDAP"
    assert fingerprint.version is None
    assert fingerprint.naming_contexts[0] == "DC=corp,DC=empresa,DC=com"


def test_a_server_that_rejects_the_anonymous_bind_is_not_flagged():
    reply = _bind_reply(RESULT_INAPPROPRIATE_AUTHENTICATION)
    fingerprint = fingerprint_ldap(reply, b"")
    assert fingerprint.product == "LDAP"          # contestó LDAP, se identifica
    assert not fingerprint.allows_anonymous_bind  # pero no deja mirar


def test_something_that_is_not_ldap_is_not_identified():
    assert fingerprint_ldap(b"+OK POP3 ready\r\n", b"<html>").product is None


# ==================================================== ¿la búsqueda trajo algo?


def test_a_reply_with_an_entry_returned_something():
    assert search_returned_entries(_search_entry_reply()) is True


def test_a_bare_search_done_returned_nothing():
    assert search_returned_entries(_search_done()) is False


def test_an_unreadable_reply_returned_nothing():
    assert search_returned_entries(b"") is False


# ================================================================ la sonda


class _ScriptedSocket:
    def __init__(self, replies, sent):
        self._replies = list(replies)
        self._sent = sent

    def settimeout(self, _timeout):
        pass

    def sendall(self, payload):
        self._sent.append(payload)

    def recv(self, _size):
        return self._replies.pop(0) if self._replies else b""

    def close(self):
        pass


def _probe_with(replies):
    sent = []
    return LdapProbe(connect=lambda _a, _t: _ScriptedSocket(replies, sent)), sent


def test_the_probe_binds_before_searching():
    """Un SearchRequest sólo tiene sentido sobre una sesión ya vinculada,
    aunque sea anónimamente: el orden lo pide el protocolo."""
    probe, sent = _probe_with([_bind_reply(RESULT_SUCCESS), OPENLDAP_ROOTDSE])
    probe.fetch("10.0.0.5")
    assert sent == [build_anonymous_bind(), build_rootdse_search()]


def test_a_server_that_says_nothing_yields_nothing():
    probe, _sent = _probe_with([b""])
    assert probe.fetch("10.0.0.5") is None


def test_a_refused_connection_yields_nothing():
    def refuse(_address, _timeout):
        raise ConnectionRefusedError("cerrado")

    assert LdapProbe(connect=refuse).fetch("10.0.0.5") is None


def test_the_naming_context_probe_binds_before_searching():
    probe, sent = _probe_with([_bind_reply(RESULT_SUCCESS), _search_entry_reply()])
    probe.fetch_naming_context_entries("10.0.0.5", "DC=empresa,DC=local")
    assert sent == [build_anonymous_bind(), build_naming_context_search("DC=empresa,DC=local")]


def test_the_naming_context_probe_gives_up_without_a_successful_bind():
    """Si el servidor rechaza el bind anónimo no hay sesión sobre la que
    buscar, así que la sonda ni siquiera manda el SearchRequest."""
    probe, sent = _probe_with([_bind_reply(RESULT_INAPPROPRIATE_AUTHENTICATION)])
    result = probe.fetch_naming_context_entries("10.0.0.5", "DC=empresa,DC=local")
    assert result is None
    assert sent == [build_anonymous_bind()]


def test_the_naming_context_probe_yields_nothing_on_a_refused_connection():
    def refuse(_address, _timeout):
        raise ConnectionRefusedError("cerrado")

    probe = LdapProbe(connect=refuse)
    assert probe.fetch_naming_context_entries("10.0.0.5", "DC=empresa,DC=local") is None


# ============================================================ el dissector


class _NullLimiter:
    def acquire(self, _host):
        pass


def test_the_dissector_claims_the_directory_ports():
    dissector = LdapDissector()
    for port in (389, 636, 3268, 3269):
        assert dissector.applies(Service(port, "tcp", ""))
    assert dissector.applies(Service(1389, "tcp", "ldap"))
    assert not dissector.applies(Service(80, "tcp", "http"))
    assert is_ldap_service(Service(389, "tcp", ""))


def test_the_dissector_reports_what_the_rootdse_published():
    probe, _sent = _probe_with([_bind_reply(RESULT_SUCCESS), OPENLDAP_ROOTDSE])
    result = LdapDissector(probe=probe).probe(
        "10.0.0.5", Service(389, "tcp", "ldap"), _NullLimiter())
    assert (result.product, result.version, result.label) == (
        "Apache Software Foundation", "2.0.0", "LDAP")


# ================================================================ los checks


class _Context:
    def __init__(self, port=389, siblings=()):
        self.target = "10.0.0.5"
        self.service = Service(port, "tcp", "ldap")
        self.sibling_services = siblings

    def acquire(self):
        pass


def _anonymous_plugin(rootdse_replies, naming_search_replies=()):
    """Construye el plugin con una sonda que da respuestas distintas a sus dos
    conexiones: la primera para el bind + rootDSE, la segunda para la
    búsqueda bajo el dominio publicado."""
    from src.modules.features.themis.lybra.script_checks import LdapAnonymousBindPlugin

    connections = [list(rootdse_replies), list(naming_search_replies)]

    def connect(_address, _timeout):
        replies = connections.pop(0) if connections else []
        return _ScriptedSocket(replies, [])

    return LdapAnonymousBindPlugin(probe=LdapProbe(connect=connect))


def test_a_domain_controller_that_only_answers_the_rootdse_is_not_flagged():
    """El falso positivo que este check tenía: todo controlador de dominio
    conforme al estándar acepta el bind anónimo para servir el rootDSE, y eso
    solo no expone nada. Sin una búsqueda que devuelva entradas, no hay
    hallazgo."""
    plugin = _anonymous_plugin(
        [_bind_reply(RESULT_SUCCESS), ACTIVE_DIRECTORY_ROOTDSE],
        [_bind_reply(RESULT_SUCCESS), _search_done()],
    )
    assert plugin.run(_Context()) is False


def test_a_directory_that_returns_entries_to_an_anonymous_search_is_flagged():
    plugin = _anonymous_plugin(
        [_bind_reply(RESULT_SUCCESS), OPENLDAP_ROOTDSE],
        [_bind_reply(RESULT_SUCCESS), _search_entry_reply()],
    )
    assert plugin.run(_Context()) is True


def test_a_naming_context_search_rejected_outright_is_not_flagged():
    """El segundo bind se acepta pero la búsqueda misma se rechaza (o vuelve
    vacía): sigue sin haber entradas que ver."""
    plugin = _anonymous_plugin(
        [_bind_reply(RESULT_SUCCESS), OPENLDAP_ROOTDSE],
        [_bind_reply(RESULT_INAPPROPRIATE_AUTHENTICATION)],
    )
    assert plugin.run(_Context()) is False


def test_no_naming_context_means_no_search_and_no_finding():
    """Sin un dominio publicado en el rootDSE no hay base sobre la que
    buscar, así que el plugin ni siquiera abre la segunda conexión."""
    plugin = _anonymous_plugin(
        [_bind_reply(RESULT_SUCCESS), _search_done()],
    )
    assert plugin.run(_Context()) is False


def test_the_anonymous_bind_check_stays_quiet_without_evidence():
    from src.modules.features.themis.lybra.script_checks import LdapAnonymousBindPlugin

    def refuse(_address, _timeout):
        raise ConnectionRefusedError("cerrado")

    plugin = LdapAnonymousBindPlugin(probe=LdapProbe(connect=refuse))
    assert plugin.run(_Context()) is False


def _cleartext_plugin():
    from src.modules.features.themis.lybra.script_checks import (
        LdapCleartextWithLdapsPlugin,
    )
    return LdapCleartextWithLdapsPlugin()


def test_the_cleartext_check_needs_an_ldaps_sibling_to_fire():
    """El primer check del motor que no es propiedad de un servicio sino de la
    relación entre dos. Un 389 solo no dice gran cosa; un 389 junto a un 636
    dice que la versión cifrada existe y que la de claro sigue abierta."""
    plugin = _cleartext_plugin()
    alone = _Context(389, siblings=(Service(389, "tcp", "ldap"),))
    with_ldaps = _Context(389, siblings=(Service(389, "tcp", "ldap"),
                                         Service(636, "tcp", "ldaps")))
    assert plugin.run(alone) is False
    assert plugin.run(with_ldaps) is True


def test_the_cleartext_check_never_applies_to_the_encrypted_port_itself():
    plugin = _cleartext_plugin()
    for port in LDAPS_PORTS:
        assert not plugin.applies(Service(port, "tcp", "ldaps"))
    assert plugin.applies(Service(389, "tcp", "ldap"))


def test_the_cleartext_check_makes_no_network_request():
    """La evidencia son dos puertos que el descubrimiento ya encontró: no hay
    ninguna petición que hacer, y por eso el plugin no recibe sonda."""
    plugin = _cleartext_plugin()
    assert not hasattr(plugin, "_probe")


def test_both_ldap_checks_are_registered_and_wired_to_their_feed_entries():
    from src.modules.features.themis.lybra.checks import load_checks
    from src.modules.features.themis.lybra.script_checks import default_script_plugins

    plugins = default_script_plugins()
    for check_id in ("ldap-anonymous-bind", "ldap-cleartext-with-ldaps"):
        check = next(c for c in load_checks() if c.id == check_id)
        assert check.service == "ldap" and check.mode == "safe"
        assert check.script in plugins


# ============================ nivel funcional del dominio y vía cifrada

_STARTTLS_OID = "1.3.6.1.4.1.1466.20037"


class _EvidenceContext(_Context):
    def __init__(self, port=389, siblings=()):
        super().__init__(port, siblings)
        self.evidence = {}


def _rootdse(**attributes):
    return [_bind_reply(RESULT_SUCCESS), _search_reply(attributes)]


def _level_plugin(replies):
    from src.modules.features.themis.lybra.script_checks import LdapDomainFunctionalLevelPlugin
    probe, _sent = _probe_with(replies)
    return LdapDomainFunctionalLevelPlugin(probe=probe)


def _channel_plugin(replies):
    from src.modules.features.themis.lybra.script_checks import LdapNoEncryptedChannelPlugin
    probe, _sent = _probe_with(replies)
    return LdapNoEncryptedChannelPlugin(probe=probe)


def test_the_rootdse_asks_for_the_extensions_and_the_domain_level():
    assert {"supportedExtension", "domainFunctionality"} <= set(ROOTDSE_ATTRIBUTES)


def test_the_extensions_and_the_domain_level_are_read_from_the_rootdse():
    fingerprint = fingerprint_ldap(*_rootdse(
        supportedExtension=[_STARTTLS_OID, "1.3.6.1.4.1.4203.1.11.3"], domainFunctionality=["7"]))
    assert fingerprint.supports_starttls is True
    assert fingerprint.domain_functional_level == 7
    assert fingerprint.domain_windows_version == "Windows Server 2016"


def test_a_rootdse_without_extensions_does_not_say_whether_starttls_exists():
    assert fingerprint_ldap(*_rootdse(vendorName=["OpenLDAP"])).supports_starttls is None


@pytest.mark.parametrize("level, version", [("3", "Windows Server 2008"), ("6", "Windows Server 2012 R2")])
def test_a_domain_in_an_unsupported_level_is_flagged(level, version):
    context = _EvidenceContext()
    assert _level_plugin(_rootdse(domainFunctionality=[level])).run(context) is True
    assert context.evidence == {"domainFunctionality": int(level), "windowsVersion": version}


@pytest.mark.parametrize("level", ["7", "10"])
def test_a_domain_in_a_supported_level_is_not_flagged(level):
    """Señuelo: el mismo controlador en un nivel funcional reciente."""
    assert _level_plugin(_rootdse(domainFunctionality=[level])).run(_EvidenceContext()) is False


def test_a_directory_that_is_not_active_directory_has_no_domain_level():
    assert _level_plugin(_rootdse(vendorName=["OpenLDAP"])).run(_EvidenceContext()) is False


def test_a_directory_without_ldaps_nor_starttls_is_flagged():
    plugin = _channel_plugin(_rootdse(supportedExtension=["1.3.6.1.4.1.4203.1.11.3"]))
    assert plugin.run(_Context()) is True


def test_a_directory_that_offers_starttls_is_not_flagged():
    """Señuelo: sin 636 abierto, pero con StartTLS sobre el 389."""
    plugin = _channel_plugin(_rootdse(supportedExtension=[_STARTTLS_OID]))
    assert plugin.run(_Context()) is False


def test_a_host_with_ldaps_is_left_to_the_cleartext_with_ldaps_check():
    """Con LDAPS en el host el aviso es ``ldap-cleartext-with-ldaps``, y éste
    ni siquiera conecta: los dos nunca disparan juntos."""
    plugin = _channel_plugin([])
    siblings = (Service(636, "tcp", "ldaps"),)
    assert plugin.run(_Context(siblings=siblings)) is False


def test_unknown_extensions_do_not_assert_a_missing_encrypted_channel():
    plugin = _channel_plugin(_rootdse(vendorName=["OpenLDAP"]))
    assert plugin.run(_Context()) is False


def test_the_channel_check_ignores_the_ldaps_ports_themselves():
    from src.modules.features.themis.lybra.script_checks import LdapNoEncryptedChannelPlugin

    plugin = LdapNoEncryptedChannelPlugin(probe=_probe_with([])[0])
    assert plugin.applies(Service(389, "tcp", "ldap"))
    assert not plugin.applies(Service(636, "tcp", "ldaps"))


def test_the_two_directory_checks_are_registered_and_wired():
    from src.modules.features.themis.lybra.checks import load_checks
    from src.modules.features.themis.lybra.script_checks import default_script_plugins

    checks = {c.id: c for c in load_checks()}
    for check_id in ("ldap-no-encrypted-channel", "ldap-domain-functional-level-unsupported"):
        assert checks[check_id].service == "ldap" and checks[check_id].mode == "safe"
        assert check_id in default_script_plugins()
