"""Checks de tipo ``script`` — el cuarto tipo del runtime.

Un check declarativo compara texto: pide algo y mira si la respuesta contiene
un patrón. Eso cubre el 90 % de lo web, pero deja fuera todo lo que exige
lógica: un protocolo binario, una negociación de varios pasos cuyo resultado
hay que interpretar, o un hecho que ya se dedujo pero que ningún matcher de
texto puede expresar. Para eso está este tipo.

**Un caso concreto, que es el que motiva el módulo.** Los checks "SMB sin
firma" y "SMBv1 habilitado" no se pueden expresar como un check declarativo,
porque el runtime declarativo sólo compara texto decodificado y una respuesta
SMB2 es binaria. Pero el dissector de SMB ya negocia con el servidor y ya lee
su ``SecurityMode``: el hecho está observado, sólo faltaba un vehículo para
convertirlo en un hallazgo. Un plugin de primera parte es ese vehículo.

**Por qué los plugins se inyectan y no se importan.** ``checks.py`` no importa
``fingerprinting`` a propósito — lo dice su propio comentario en ``_TLS_RULES``:
importarlo crearía un ciclo, porque los dissectors importan de ``checks`` sus
predicados de aplicabilidad (``is_smb_service`` y compañía). Este módulo sí
puede importar ambos, y el runtime recibe el registro ya construido por el
mismo mecanismo de inyección con el que ya recibe ``tls_fetch`` y
``network_open``. El runtime sigue sin conocer ningún protocolo concreto.

El reparto es el mismo que ya existe para los dissectors: la clase base
(:class:`~.checks.ScriptPlugin`) y su contexto viven junto al runtime, igual que
``Dissector`` vive en ``dispatch.py``; los plugins concretos viven aquí, igual
que ``SmbDissector`` vive en ``smb.py``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from .checks import (
    is_ike_service,
    ScriptContext,
    ScriptPlugin,
    LDAPS_PORTS,
    is_ldap_service,
    is_dns_service,
    is_mongodb_service,
    is_ntp_service,
    is_rdp_service,
    is_postgres_service,
    is_smb_service,
    is_snmp_service,
    is_ssh_service,
    is_telnet_service,
    is_tls_service,
    is_vnc_service,
)
from .engine import Service
from .fingerprinting.smb import SIGNING_REQUIRED_BIT, SmbProbe, fingerprint_smb
from .fingerprinting.ldap import LdapProbe, fingerprint_ldap
from .fingerprinting.mongo import MongoProbe, fingerprint_mongo
from .fingerprinting.postgres import PostgresProbe, fingerprint_postgres
from .fingerprinting.rdp import RdpProbe, fingerprint_rdp
from .fingerprinting.snmp import SnmpProbe
from .fingerprinting.ssh import SshProbe, parse_kexinit
from .fingerprinting.telnet import TelnetProbe
from .fingerprinting.tls import TlsProbe
from .fingerprinting.vnc import VncProbe
from .transport import tcp_timestamps_enabled
from .fingerprinting.udp_services import (
    DnsProbe,
    IkeProbe,
    NtpProbe,
    monlist_is_answered,
    parse_dns_version_response,
    parse_ike_response,
)

logger = logging.getLogger(__name__)


class SmbSigningNotRequiredPlugin(ScriptPlugin):
    """Detecta un servicio SMB que no exige firma de mensajes.

    Sin firma obligatoria, un atacante en posición de intermediario puede
    manipular el tráfico SMB (la familia de ataques de relay). El dato no se
    infiere: sale del ``SecurityMode`` que el propio servidor devuelve en su
    respuesta NEGOTIATE, así que el hallazgo nace ``confirmed``.

    **La decisión se toma sobre el bit, no sobre la etiqueta.** Este plugin
    llegó a resolverse buscando la subcadena ``"firma no requerida"`` dentro
    del texto legible que produce ``fingerprint_smb``. Eso ataba una decisión
    de seguridad a una cadena de interfaz: traducir esa etiqueta, corregirle
    una tilde o cambiarle el fraseo apagaba el check **en silencio** —seguía
    ejecutándose, seguía devolviendo ``False``, y nadie se enteraba de que
    había dejado de detectar nada—. El dato crudo estaba dos líneas más
    arriba, en la misma tupla.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso — mismo
            patrón que :class:`~.fingerprinting.smb.SmbDissector`.
    """

    plugin_id = "smb-signing-not-required"

    def __init__(self, probe: Optional[SmbProbe] = None) -> None:
        self._probe = probe or SmbProbe()

    def applies(self, service: Service) -> bool:
        return is_smb_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        result = self._probe.fetch(context.target, context.service.port or 445)
        if result is None:
            # Sin negociación no hay evidencia, y sin evidencia no hay hallazgo.
            return False
        dialect_revision, security_mode = result
        if fingerprint_smb(dialect_revision, security_mode).version is None:
            # Respuesta no reconocible: se ignora en vez de asumir lo peor. Un
            # dialecto desconocido no es prueba de que la firma no se exija.
            # Se consulta ``version`` —un campo con tipo— y no el texto del
            # producto: lo que hace falta saber aquí es si la respuesta se
            # entendió, y eso es justo lo que ese campo significa.
            return False
        return not security_mode & SIGNING_REQUIRED_BIT


class SmbV1EnabledPlugin(ScriptPlugin):
    """Detecta un servidor que todavía acepta negociar **SMBv1**.

    Es el hallazgo clásico del protocolo, el que WannaCry convirtió en
    historia: SMB1 no tiene firma obligatoria utilizable, no cifra, y arrastra
    una familia de vulnerabilidades pre-autenticación (EternalBlue y sus
    parientes) que no se han corregido porque el protocolo entero está
    retirado desde 2014. Microsoft lo desactiva por defecto desde Windows 10
    1709; encontrarlo activo significa o bien un sistema viejo o bien alguien
    que lo reactivó a mano por un dispositivo heredado.

    **El NEGOTIATE de SMB2 no puede verlo**, y por eso este check tiene su
    propia sonda: son dos protocolos distintos con dos saludos distintos, así
    que un servidor con SMB1 activo contesta con toda normalidad al SMB2 y no
    dice ni una palabra sobre el otro.

    La evidencia es una aceptación explícita: el servidor contesta un
    ``NEGOTIATE`` de SMB1 con estado correcto y eligiendo un dialecto. El
    silencio, un error o una respuesta de SMB2 **no** cuentan — un servidor
    que no habla SMB1 no tiene por qué contestar de ninguna forma concreta.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "smbv1-enabled"

    def __init__(self, probe: Optional[SmbProbe] = None) -> None:
        self._probe = probe or SmbProbe()

    def applies(self, service: Service) -> bool:
        return is_smb_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        return self._probe.speaks_smb1(context.target, context.service.port or 445)


class SnmpDefaultCommunityPlugin(ScriptPlugin):
    """Detecta un servicio SNMP que acepta la comunidad por defecto ``public``.

    Comparte la sonda con el dissector SNMP a
    propósito: que ``sysDescr`` conteste a ``public`` ES la evidencia del
    hallazgo, no una comprobación aparte — no tiene sentido mandar el mismo
    datagrama dos veces con dos sondas distintas.

    Args:
        probe: Sonda inyectable, mismo patrón que
            :class:`~.fingerprinting.snmp.SnmpDissector`.
    """

    plugin_id = "snmp-default-community"

    def __init__(self, probe: Optional[SnmpProbe] = None) -> None:
        self._probe = probe or SnmpProbe()

    def applies(self, service: Service) -> bool:
        return is_snmp_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        sysdescr = self._probe.fetch(context.target, context.service.port or 161)
        return sysdescr is not None


class PostgresTrustAuthenticationPlugin(ScriptPlugin):
    """Detecta un PostgreSQL que acepta conexiones de red **sin contraseña**.

    El modo ``trust`` de PostgreSQL no es una autenticación débil: es la
    ausencia completa de autenticación. Un servidor con ``trust`` en su
    ``pg_hba.conf`` para direcciones de red da acceso total a cualquiera que
    alcance el puerto — sin exploit, sin fuerza bruta y sin credenciales.

    La evidencia no se infiere: es el propio servidor contestando
    ``AuthenticationOk`` a un ``StartupMessage`` con un usuario que **no
    existe**. Por eso el hallazgo nace ``confirmed``, y por eso el plugin no
    intenta autenticarse en ningún momento: no manda contraseña ninguna, sólo
    lee la política que el servidor anuncia.

    Comparte sonda con el dissector por el mismo criterio que el de SNMP: el
    dato que responde a la pregunta es el mismo, y mandar dos veces el mismo
    intercambio no lo haría más cierto.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "postgres-trust-authentication"

    def __init__(self, probe: Optional[PostgresProbe] = None) -> None:
        self._probe = probe or PostgresProbe()

    def applies(self, service: Service) -> bool:
        return is_postgres_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 5432)
        if replies is None:
            # Sin intercambio no hay evidencia, y sin evidencia no hay hallazgo.
            return False
        return fingerprint_postgres(*replies).is_unauthenticated


class MongoUnauthenticatedAccessPlugin(ScriptPlugin):
    """Detecta un MongoDB que sirve su catálogo **sin credenciales**.

    Es el hallazgo clásico del producto: durante años las instalaciones por
    defecto escuchaban en todas las interfaces sin autenticación, y de ahí
    salió una de las mayores oleadas de fuga de datos y de ransomware de bases
    de datos que se recuerdan.

    **La evidencia no es que el servidor conteste.** El comando ``hello``
    responde siempre, con ``--auth`` y sin él —es el handshake del protocolo, y
    tiene que hacerlo para que el cliente sepa con quién habla—, así que un
    check construido sobre "ha contestado" marcaría como expuesto todo MongoDB
    alcanzable. La evidencia es que ``listDatabases``, que sí exige permisos,
    devuelva la lista: un servidor cerrado responde ``ok: 0`` con el código 13.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "mongodb-unauthenticated-access"

    def __init__(self, probe: Optional[MongoProbe] = None) -> None:
        self._probe = probe or MongoProbe()

    def applies(self, service: Service) -> bool:
        return is_mongodb_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 27017)
        if replies is None:
            return False
        return fingerprint_mongo(*replies).allows_unauthenticated_access


class LdapAnonymousBindPlugin(ScriptPlugin):
    """Detecta un servidor de directorio que acepta un bind **anónimo**.

    Si el rootDSE contesta sin credenciales, la información del directorio es
    pública: quién sirve qué dominio, qué mecanismos de autenticación admite y,
    en muchos despliegues, bastante más si la consulta se amplía.

    Un bind anónimo no es un intento de adivinar credenciales: es la forma que
    el propio protocolo define para preguntar sin identificarse (RFC 4511
    §4.2), y lo que se observa es si el servidor **la acepta**. No se prueba
    ninguna contraseña.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "ldap-anonymous-bind"

    def __init__(self, probe: Optional[LdapProbe] = None) -> None:
        self._probe = probe or LdapProbe()

    def applies(self, service: Service) -> bool:
        return is_ldap_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 389)
        if replies is None:
            return False
        return fingerprint_ldap(*replies).allows_anonymous_bind


class LdapCleartextWithLdapsPlugin(ScriptPlugin):
    """Detecta un LDAP en claro conviviendo con un LDAPS en el mismo host.

    Éste es el primer check del motor que **no es propiedad de un servicio sino
    de la relación entre dos**. Un 389 abierto no dice gran cosa por sí solo:
    hay despliegues donde es la única opción y el cifrado se resuelve con
    STARTTLS. Pero un 389 en un host que además publica el 636 significa que la
    versión cifrada existe, funciona, y aun así el puerto en claro sigue
    aceptando binds — así que basta con que un cliente esté mal configurado
    para que unas credenciales de directorio viajen legibles por la red.

    No hace ninguna petición: la evidencia son dos puertos que el
    descubrimiento ya encontró (ver ``ScriptContext.sibling_services``).
    """

    plugin_id = "ldap-cleartext-with-ldaps"

    def applies(self, service: Service) -> bool:
        return is_ldap_service(service) and service.port not in LDAPS_PORTS

    def run(self, context: ScriptContext) -> bool:
        return any(
            sibling.port in LDAPS_PORTS
            for sibling in context.sibling_services
        )


class RdpNlaNotRequiredPlugin(ScriptPlugin):
    """Detecta un RDP que **no** exige autenticación a nivel de red.

    NLA obliga a autenticarse antes de que exista la sesión gráfica. Sin él,
    cualquiera que alcance el puerto llega a la pantalla de login — lo que
    habilita la fuerza bruta y toda la familia de vulnerabilidades
    pre-autenticación de la que BlueKeep (CVE-2019-0708) es el ejemplo
    canónico. RDP es, además, el vector de entrada de la mayoría de los
    incidentes de ransomware que empiezan por acceso remoto.

    El dato no se infiere: es el protocolo de seguridad que el propio servidor
    **elige** en la negociación de X.224, así que el hallazgo nace
    ``confirmed``.

    **Un servidor cuyo modo no se ha podido leer no dispara el check.** La
    propiedad que se consulta distingue "no exige NLA" de "no se sabe"
    (``None``), y sólo la primera es un hallazgo: afirmar una configuración
    insegura sin haberla observado sería inventarla.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "rdp-nla-not-required"

    def __init__(self, probe: Optional[RdpProbe] = None) -> None:
        self._probe = probe or RdpProbe()

    def applies(self, service: Service) -> bool:
        return is_rdp_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        response = self._probe.fetch(context.target, context.service.port or 3389)
        if response is None:
            return False
        return fingerprint_rdp(response).requires_network_level_authentication is False


class DnsOpenResolverPlugin(ScriptPlugin):
    """Detecta un servidor DNS que resuelve nombres para cualquiera.

    Un resolutor abierto no es sólo un problema para su dueño: es un
    **amplificador a disposición de quien lo quiera usar**. Una consulta
    pequeña con la dirección de origen falsificada provoca una respuesta mucho
    mayor dirigida a la víctima, y el host del cliente pasa de tener un
    servicio mal configurado a ser un arma contra terceros. Ésa es una
    conversación distinta, y más incómoda, que "tienes un puerto abierto".

    **La evidencia es la bandera que el servidor enciende él solo.** La
    respuesta a ``version.bind`` trae el bit de "recursión disponible", y con
    eso basta: la alternativa —lanzar una consulta recursiva de verdad por un
    nombre externo— haría que el objetivo mandase tráfico a un tercero para
    responderla, que es exactamente el comportamiento que se está midiendo.
    Comprobarlo no debería practicarlo.

    Args:
        probe: Sonda inyectable, para que un test use un emisor falso.
    """

    plugin_id = "dns-open-resolver"

    def __init__(self, probe: Optional[DnsProbe] = None) -> None:
        self._probe = probe or DnsProbe()

    def applies(self, service: Service) -> bool:
        return is_dns_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        reply = self._probe.fetch(context.target, context.service.port or 53)
        if reply is None:
            return False
        return parse_dns_version_response(reply).offers_recursion


class NtpMonlistPlugin(ScriptPlugin):
    """Detecta un servidor NTP que sigue aceptando ``monlist``.

    ``monlist`` devuelve los últimos seiscientos clientes que han hablado con
    el servidor. Es a la vez un problema de privacidad —el inventario de quién
    usa ese NTP— y el vector de amplificación x500 que llenó internet de
    ataques en 2014: ocho bytes de petición provocan kilobytes de respuesta.

    Preguntarlo no amplifica nada contra nadie: la respuesta viene **a
    nosotros**, no a un tercero. Lo que demuestra es que ese servidor serviría
    para hacerlo.

    Args:
        probe: Sonda inyectable, para que un test use un emisor falso.
    """

    plugin_id = "ntp-monlist-enabled"

    def __init__(self, probe: Optional[NtpProbe] = None) -> None:
        self._probe = probe or NtpProbe()

    def applies(self, service: Service) -> bool:
        return is_ntp_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        return monlist_is_answered(
            self._probe.fetch_monlist(context.target, context.service.port or 123))


class TelnetEnabledPlugin(ScriptPlugin):
    """Detecta un servicio Telnet activo.

    Telnet manda credenciales en claro por diseño: usuario y contraseña viajan
    sin cifrar por la red, legibles para cualquiera que escuche. No hay una
    "mala configuración" que arreglar — el hallazgo es que el protocolo esté en
    uso. Por eso este check no identifica producto ni versión: le basta con
    confirmar que al otro lado hay algo que **habla Telnet**, cosa que un
    servidor delata abriendo su negociación de opciones con el byte IAC (ver
    :class:`~.fingerprinting.telnet.TelnetProbe`).

    Un puerto 23 abierto no basta como evidencia: podría ser cualquier servicio
    mudo en un puerto reutilizado. Lo que dispara es la firma del protocolo, no
    la apertura del puerto.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "telnet-enabled"

    def __init__(self, probe: Optional[TelnetProbe] = None) -> None:
        self._probe = probe or TelnetProbe()

    def applies(self, service: Service) -> bool:
        return is_telnet_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        return self._probe.speaks_telnet(context.target, context.service.port or 23)


class VncNoAuthenticationPlugin(ScriptPlugin):
    """Detecta un servidor VNC que ofrece acceso **sin autenticación**.

    El protocolo RFB negocia, tras el saludo de versión, qué tipos de seguridad
    admite el servidor. El tipo 1 es ``None`` (RFC 6143 §7.1.2): entrar sin
    contraseña. Un VNC que lo ofrece deja el escritorio del objetivo a
    disposición de cualquiera que alcance el puerto.

    La evidencia es un hecho observado —el servidor **anuncia** ese tipo en su
    lista—, no una inferencia, así que el hallazgo nace ``confirmed``. Y no se
    cruza la línea: se lee la lista de tipos ofrecidos y ahí acaba, sin
    responder a la negociación y sin abrir sesión (ver
    :meth:`~.fingerprinting.vnc.VncProbe.security_types`).

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    plugin_id = "vnc-no-authentication"
    _SECURITY_NONE = 1

    def __init__(self, probe: Optional[VncProbe] = None) -> None:
        self._probe = probe or VncProbe()

    def applies(self, service: Service) -> bool:
        return is_vnc_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        types = self._probe.security_types(context.target, context.service.port or 5900)
        if types is None:
            return False
        return self._SECURITY_NONE in types


# -------------------------------------------------------------------- SSH
#
# Al conectar, antes de cifrar nada, el servidor SSH envía en claro su
# ``KEXINIT``: la lista completa de algoritmos que acepta. Los plugins de abajo
# la leen y no pasan de ahí —nunca completan el intercambio de claves ni se
# autentican—, así que son checks ``safe`` por construcción.

class _KexinitCache:
    """Una sola lectura del ``KEXINIT`` por servicio, compartida por los plugins SSH.

    Seis plugins miran el mismo mensaje; sin esto, cada uno abriría su propia
    conexión y el objetivo vería seis saludos SSH seguidos para una sola
    pregunta. Vive lo que vive el registro de plugins (un escaneo).

    Args:
        probe: Sonda inyectable, para que un test use un socket falso.
    """

    def __init__(self, probe: Optional[SshProbe] = None) -> None:
        self._probe = probe or SshProbe()
        self._kexinits: Dict[Tuple[str, int], Optional[Dict[str, List[str]]]] = {}

    def kexinit(self, context: ScriptContext) -> Optional[Dict[str, List[str]]]:
        """Devuelve las listas de algoritmos del servicio, sondeándolo la primera vez.

        Args:
            context: El contexto del check, del que salen objetivo, puerto y
                limitador de ritmo.

        Returns:
            Optional[Dict[str, List[str]]]: Las diez listas del ``KEXINIT``
                (ver ``fingerprinting.ssh._KEXINIT_FIELDS``), o ``None`` si no
                hubo conexión o la respuesta no se entendió.
        """
        key = (context.target, context.service.port or 22)
        if key not in self._kexinits:
            context.acquire()
            probed = self._probe.fetch(*key)
            parsed = None
            if probed is not None:
                try:
                    parsed = parse_kexinit(probed[1])
                except ValueError:
                    parsed = None
            self._kexinits[key] = parsed
        return self._kexinits[key]


def _is_weak_mac(name: str) -> bool:
    """MAC basado en MD5, de 96 o de 64 bits, o ``none`` (el mismo criterio que OpenVAS)."""
    return name == "none" or "md5" in name or "-96" in name or name.startswith("umac-64")


def _is_weak_cipher(name: str) -> bool:
    """Cifrado en modo CBC, RC4 (``arcfour``), 3DES/DES, Blowfish, CAST o ``none``."""
    return name == "none" or any(token in name for token in (
        "cbc", "arcfour", "3des", "blowfish", "cast128"))


_WEAK_KEX = frozenset({
    "diffie-hellman-group1-sha1",
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group-exchange-sha1",
    "rsa1024-sha1",
})


def _is_weak_kex(name: str) -> bool:
    """Intercambio de claves con SHA-1 o con el grupo Diffie-Hellman 1 (768 bits)."""
    return name in _WEAK_KEX or (name.startswith("gss-") and "sha1" in name)


def _is_weak_host_key(name: str) -> bool:
    """Clave de host DSA, o RSA firmada con SHA-1 (``ssh-rsa``)."""
    return name.startswith("ssh-dss") or name == "ssh-rsa" or name.startswith("ssh-rsa-cert")


# familia → (listas del KEXINIT que mira, criterio de debilidad)
_WEAK_ALGORITHM_FAMILIES = {
    "mac": (("mac_algorithms_client_to_server", "mac_algorithms_server_to_client"), _is_weak_mac),
    "encryption": (("encryption_algorithms_client_to_server",
                    "encryption_algorithms_server_to_client"), _is_weak_cipher),
    "kex": (("kex_algorithms",), _is_weak_kex),
    "host-key": (("server_host_key_algorithms",), _is_weak_host_key),
}


def weak_ssh_algorithms(kexinit: Dict[str, List[str]], family: str) -> List[str]:
    """Los algoritmos débiles que un servidor SSH acepta en una familia.

    Args:
        kexinit: Las listas del ``KEXINIT``, como las devuelve ``parse_kexinit``.
        family: ``"mac"``, ``"encryption"``, ``"kex"`` o ``"host-key"``.

    Returns:
        List[str]: Los nombres débiles, sin repetir y en el orden en que el
            servidor los anuncia. Vacía si no acepta ninguno.
    """
    fields, is_weak = _WEAK_ALGORITHM_FAMILIES[family]
    weak: List[str] = []
    for field_name in fields:
        for name in kexinit.get(field_name, []):
            if is_weak(name) and name not in weak:
                weak.append(name)
    return weak


class SshWeakAlgorithmsPlugin(ScriptPlugin):
    """Detecta un servidor SSH que acepta algoritmos débiles de una familia.

    Se instancia una vez por familia (MAC, cifrado, intercambio de claves,
    clave de host) para que cada una sea su propio hallazgo con su propia
    severidad, como hace OpenVAS. La lista exacta de algoritmos débiles va en
    la evidencia: «acepta MACs débiles» no se puede corregir sin saber cuáles.

    Args:
        family: ``"mac"``, ``"encryption"``, ``"kex"`` o ``"host-key"``.
        cache: La caché de ``KEXINIT`` compartida con los otros plugins SSH.
    """

    def __init__(self, family: str, cache: _KexinitCache) -> None:
        self.plugin_id = f"ssh-weak-{family}"
        self._family = family
        self._cache = cache

    def applies(self, service: Service) -> bool:
        return is_ssh_service(service)

    def run(self, context: ScriptContext) -> bool:
        kexinit = self._cache.kexinit(context)
        if kexinit is None:
            return False
        weak = weak_ssh_algorithms(kexinit, self._family)
        if weak:
            context.evidence.update({"family": self._family, "weak_algorithms": weak})
        return bool(weak)


# Terrapin (CVE-2023-48795) necesita un modo de cifrado vulnerable —ChaCha20-
# Poly1305, o un MAC encrypt-then-MAC junto a un cifrado CBC— y que el
# servidor no haya activado la contramedida *strict kex*.
_STRICT_KEX_MARKER = "kex-strict-s-v00@openssh.com"


def is_vulnerable_to_terrapin(kexinit: Dict[str, List[str]]) -> bool:
    """Decide si las listas de un servidor SSH lo dejan expuesto a Terrapin.

    Args:
        kexinit: Las listas del ``KEXINIT``.

    Returns:
        bool: ``True`` si ofrece un modo vulnerable y no anuncia *strict kex*;
            ``False`` si anuncia *strict kex* o no ofrece ningún modo
            vulnerable.
    """
    if _STRICT_KEX_MARKER in kexinit.get("kex_algorithms", []):
        return False
    ciphers = (kexinit.get("encryption_algorithms_client_to_server", [])
               + kexinit.get("encryption_algorithms_server_to_client", []))
    macs = (kexinit.get("mac_algorithms_client_to_server", [])
            + kexinit.get("mac_algorithms_server_to_client", []))
    has_chacha = "chacha20-poly1305@openssh.com" in ciphers
    has_etm_with_cbc = (any("-etm@" in mac for mac in macs)
                        and any("cbc" in cipher for cipher in ciphers))
    return has_chacha or has_etm_with_cbc


class SshTerrapinPlugin(ScriptPlugin):
    """Confirma o desmiente Terrapin (CVE-2023-48795) con las listas del propio servidor.

    La detección por versión sólo puede decir «esta versión estaba afectada»;
    el ``KEXINIT`` dice si **esta configuración** lo está. Se registra dos
    veces: como confirmador (dispara si es vulnerable) y como refutador
    (dispara si no lo es), y el feed ata cada instancia a su conclusión.

    Args:
        expect_vulnerable: ``True`` para la instancia confirmadora, ``False``
            para la refutadora.
        cache: La caché de ``KEXINIT`` compartida con los otros plugins SSH.
    """

    def __init__(self, expect_vulnerable: bool, cache: _KexinitCache) -> None:
        self.plugin_id = "ssh-terrapin-confirm" if expect_vulnerable else "ssh-terrapin-refute"
        self._expect_vulnerable = expect_vulnerable
        self._cache = cache

    def applies(self, service: Service) -> bool:
        return is_ssh_service(service)

    def run(self, context: ScriptContext) -> bool:
        kexinit = self._cache.kexinit(context)
        if kexinit is None:
            # Sin KEXINIT no se puede afirmar nada, ni en un sentido ni en otro.
            return False
        context.evidence.update({
            "strict_kex": _STRICT_KEX_MARKER in kexinit.get("kex_algorithms", []),
            "kex_algorithms": kexinit.get("kex_algorithms", []),
        })
        return is_vulnerable_to_terrapin(kexinit) == self._expect_vulnerable


class IkeWeakTransformPlugin(ScriptPlugin):
    """Detecta un gateway VPN IKE que acepta criptografía retirada.

    Un gateway IKEv1 elige, de entre las transformadas que se le ofrecen, la
    que prefiere, y la anuncia en su respuesta. Si esa elección incluye un
    cifrado DES o 3DES, un hash MD5 o SHA-1, o un grupo Diffie-Hellman 1, 2 o 5
    (roto o de 1024 bits o menos, al alcance de un *logjam*), el propio gateway
    está diciendo que negociaría un túnel débil.

    No hace falta ir más allá de lo que la sonda ya negocia: la elección del
    servidor sobre el abanico estándar de :func:`~..udp_payloads.build_ike_main_mode`
    basta. Ofrecer transformadas débiles una a una (el modo agresivo del issue)
    es otra conversación y no entra aquí.

    Args:
        probe: Sonda inyectable, para que un test use un emisor falso.
    """

    plugin_id = "ike-weak-transform"

    def __init__(self, probe: Optional[IkeProbe] = None) -> None:
        self._probe = probe or IkeProbe()

    def applies(self, service: Service) -> bool:
        return is_ike_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        reply = self._probe.fetch(context.target, context.service.port or 500)
        if reply is None:
            return False
        return parse_ike_response(reply).accepts_weak_cryptography


class _TcpTimestampsCache:
    """Una sola lectura de las marcas de tiempo TCP por host, para un aviso por host.

    Las marcas de tiempo son una propiedad del núcleo del objetivo, no de un
    puerto: preguntarlo en cada servicio daría un hallazgo idéntico por cada
    puerto abierto. Este caché sondea una vez por host y deja que **sólo el
    primer** servicio que pregunta produzca el hallazgo. Vive lo que vive el
    registro de plugins (un escaneo).

    Args:
        connect: ``(address, timeout) -> socket`` inyectable, para el test.
    """

    def __init__(self, connect=None) -> None:
        self._connect = connect
        self._reported: set = set()
        self._result: Dict[str, Optional[bool]] = {}

    def first_positive(self, context: ScriptContext) -> bool:
        """``True`` sólo la primera vez que un host resulta tener marcas de tiempo."""
        host = context.target
        if host not in self._result:
            context.acquire()
            self._result[host] = tcp_timestamps_enabled(
                host, context.service.port or 0, connect=self._connect)
        if self._result[host] and host not in self._reported:
            self._reported.add(host)
            return True
        return False


class TcpTimestampsPlugin(ScriptPlugin):
    """Detecta que el objetivo negocia marcas de tiempo TCP (RFC 7323).

    Con ellas, un contador que avanza a ritmo fijo en los paquetes TCP deja
    estimar cuánto lleva encendido el equipo, y un equipo encendido desde hace
    mucho es uno que no ha reiniciado para aplicar actualizaciones del núcleo.
    Es un aviso de severidad baja, de los que llenan cualquier informe de
    OpenVAS.

    La bandera se lee de ``TCP_INFO`` en una conexión ya abierta: sólo Linux
    (la plataforma de la API), sin socket crudo ni privilegios. En otra
    plataforma el sondeo devuelve «no se sabe» y el check no dispara.

    Warning:
        La **estimación del tiempo encendido** que OpenVAS da junto a este
        aviso no se produce: exige leer los valores del contador de dos
        paquetes, y eso ya es captura cruda, fuera de lo que este camino hace.
        Queda como límite conocido.

    Args:
        cache: El caché por host, que hace que el aviso salga una sola vez.
    """

    plugin_id = "tcp-timestamps-enabled"

    def __init__(self, cache: Optional[_TcpTimestampsCache] = None) -> None:
        self._cache = cache or _TcpTimestampsCache()

    def applies(self, service: Service) -> bool:
        return (service.protocol or "tcp").lower() == "tcp" and service.port is not None

    def run(self, context: ScriptContext) -> bool:
        return self._cache.first_positive(context)


#: Las familias de conjuntos de cifrado TLS 1.2 que se ofrecen por separado,
#: por ``plugin_id``, en la sintaxis de OpenSSL. Sin confidencialidad directa:
#: intercambio de claves RSA estático (``kRSA``), con el que filtrar un día la
#: clave privada del servidor descifra todo el tráfico grabado antes. CBC: los
#: modos de cifrado en bloque encadenado que la guía intermedia de Mozilla ya no
#: admite, por su historial de ataques de relleno (Lucky13, POODLE).
_TLS12_WEAK_CIPHER_FAMILIES = {
    "tls-no-forward-secrecy": "kRSA:!aNULL:!eNULL",
    "tls-cbc-ciphers": ("AES128-SHA:AES256-SHA:AES128-SHA256:AES256-SHA256:"
                        "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:"
                        "ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384:"
                        "ECDHE-ECDSA-AES128-SHA:ECDHE-ECDSA-AES256-SHA:"
                        "ECDHE-ECDSA-AES128-SHA256:ECDHE-ECDSA-AES256-SHA384"),
}


class TlsWeakCipherFamilyPlugin(ScriptPlugin):
    """Detecta que un servicio TLS acepta una familia de cifrados débil.

    Un cliente moderno elige el mejor conjunto que el servidor acepta, así que
    la conexión normal casi nunca enseña los débiles. Lo que importa es lo peor
    que el servidor acepta, porque un atacante en medio puede empujar hacia
    ahí: se ofrece **sólo** la familia y se mira si el servidor la acepta. Una
    conexión por familia y servicio TLS.

    Args:
        plugin_id: Una clave de :data:`_TLS12_WEAK_CIPHER_FAMILIES`.
        probe: Sonda inyectable, para que un test use otra. Por defecto,
            ``TlsProbe()``.
    """

    def __init__(self, plugin_id: str, probe: Optional[TlsProbe] = None) -> None:
        self.plugin_id = plugin_id
        self._ciphers = _TLS12_WEAK_CIPHER_FAMILIES[plugin_id]
        self._probe = probe or TlsProbe()

    def applies(self, service: Service) -> bool:
        return is_tls_service(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        accepted = self._probe.fetch_accepted_tls12_cipher(
            context.target, context.service.port or 443, self._ciphers)
        if not accepted:
            return False
        context.evidence.update({"acceptedCipher": accepted})
        return True


def default_script_plugins() -> Dict[str, ScriptPlugin]:
    """Construye el registro de plugins de primera parte, indexado por ``plugin_id``.

    Returns:
        Un mapa ``plugin_id -> plugin``, que es lo que ``CheckRuntime`` espera
        recibir por inyección. Añadir un plugin es añadir una entrada aquí.
    """
    plugins = (
        SmbSigningNotRequiredPlugin(),
        SmbV1EnabledPlugin(),
        SnmpDefaultCommunityPlugin(),
        DnsOpenResolverPlugin(),
        NtpMonlistPlugin(),
        PostgresTrustAuthenticationPlugin(),
        MongoUnauthenticatedAccessPlugin(),
        LdapAnonymousBindPlugin(),
        LdapCleartextWithLdapsPlugin(),
        RdpNlaNotRequiredPlugin(),
        TelnetEnabledPlugin(),
        VncNoAuthenticationPlugin(),
        IkeWeakTransformPlugin(),
        TcpTimestampsPlugin(),
    )
    plugins += tuple(TlsWeakCipherFamilyPlugin(plugin_id) for plugin_id in _TLS12_WEAK_CIPHER_FAMILIES)
    ssh_cache = _KexinitCache()
    plugins += tuple(SshWeakAlgorithmsPlugin(family, ssh_cache)
                     for family in _WEAK_ALGORITHM_FAMILIES)
    plugins += (SshTerrapinPlugin(True, ssh_cache), SshTerrapinPlugin(False, ssh_cache))
    return {plugin.plugin_id: plugin for plugin in plugins}
