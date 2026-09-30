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
import re
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm

from .checks import (
    Baseline,
    HttpProbe,
    Response,
    baseline_path,
    is_http_service,
    is_ike_service,
    ScriptContext,
    ScriptPlugin,
    LDAPS_PORTS,
    is_ldap_service,
    is_dns_service,
    is_mongodb_service,
    is_mssql_service,
    is_ntp_service,
    is_rdp_service,
    is_postgres_service,
    is_smb_service,
    is_snmp_service,
    is_ssh_service,
    is_telnet_service,
    is_tls_certificate_service,
    is_tls_service,
    is_vnc_service,
    is_winrm_service,
    starttls_protocol_for,
)
from .engine import Service
from .fingerprinting.smb import SIGNING_REQUIRED_BIT, SmbProbe, fingerprint_smb
from .fingerprinting.ldap import LdapProbe, fingerprint_ldap, search_returned_entries
from .fingerprinting.mongo import MongoProbe, fingerprint_mongo
from .fingerprinting.mssql import MssqlProbe, fingerprint_mssql
from .fingerprinting.postgres import PostgresProbe, fingerprint_postgres
from .fingerprinting.rdp import RdpProbe, fingerprint_rdp
from .fingerprinting.snmp import SnmpProbe
from .fingerprinting.ssh import SshProbe, parse_kexinit
from .fingerprinting.telnet import TelnetProbe
from .fingerprinting import windows_rpc
from .fingerprinting.tls import LEGACY_TLS_PROTOCOLS, TlsProbe
from .fingerprinting.tls_hello import (
    HANDSHAKE_CERTIFICATE,
    HANDSHAKE_SERVER_KEY_EXCHANGE,
    VERSION_TLS_1_2,
    TlsHelloProbe,
    parse_certificate_message,
    parse_dhe_server_key_exchange,
)
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


class PostgresPasswordWithoutTlsPlugin(ScriptPlugin):
    """Detecta un PostgreSQL que pide contraseña pero no ofrece cifrar la conexión.

    El dissector ya hace las dos preguntas que lo deciden: si el servidor
    acepta el ``SSLRequest`` (``accepts_tls``) y qué método de autenticación
    anuncia (``auth_method``). Un servidor que contesta ``N`` al primero y pide
    una contraseña en el segundo obliga a todo cliente a mandarla por un canal
    en claro: en texto plano con ``password``, o como un resumen MD5 que se
    puede atacar sin conexión con ``md5``. Con SCRAM la contraseña no viaja,
    pero todo lo que venga después —consultas y datos— sí, sin cifrar.

    Ningún dato nuevo: las mismas dos conexiones que el dissector, con un
    usuario inexistente y sin mandar nunca una contraseña. El modo ``trust``
    queda fuera: no pide contraseña, y ya lo avisa
    :class:`PostgresTrustAuthenticationPlugin` con más severidad.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``PostgresProbe()``.
    """

    plugin_id = "postgres-password-without-tls"

    def __init__(self, probe: Optional[PostgresProbe] = None) -> None:
        self._probe = probe or PostgresProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es PostgreSQL.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_postgres_service``.
        """
        return is_postgres_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Hace los dos intercambios y cruza la respuesta al ``SSLRequest`` con el método anunciado.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de conectar. El método anunciado va a la evidencia
                (``authMethod``).

        Returns:
            bool: ``True`` si el servidor rechazó TLS y pide una contraseña;
                ``False`` si acepta TLS, si no pide contraseña, si no contestó
                o si alguno de los dos datos no se pudo leer.
        """
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 5432)
        if replies is None:
            return False
        fingerprint = fingerprint_postgres(*replies)
        if not fingerprint.asks_for_password or fingerprint.accepts_tls is not False:
            return False
        context.evidence.update({"authMethod": fingerprint.auth_method})
        return True


#: Los dos avisos de cifrado de SQL Server, por la postura que los dispara.
#: Son dos checks y no uno porque su gravedad es distinta: sin cifrado
#: posible viajan en claro también las credenciales; con cifrado opcional,
#: el login va cifrado y lo que viaja en claro son las consultas y los datos.
_MSSQL_ENCRYPTION_POSTURES = {
    "mssql-encryption-not-supported": "is_encryption_unsupported",
    "mssql-encryption-not-required": "is_encryption_optional",
}


class MssqlEncryptionPlugin(ScriptPlugin):
    """Detecta un SQL Server que no exige cifrar la conexión.

    El primer intercambio del protocolo (``PRELOGIN``), sin autenticar, ya trae
    la postura del servidor sobre el cifrado del canal; el dissector la lee
    para identificar el producto y aquí se convierte en aviso. Una instancia
    por postura, igual que las familias de algoritmos de SSH.

    Args:
        plugin_id: Una clave de :data:`_MSSQL_ENCRYPTION_POSTURES`.
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``MssqlProbe()``.
    """

    def __init__(self, plugin_id: str, probe: Optional[MssqlProbe] = None) -> None:
        self.plugin_id = plugin_id
        self._posture = _MSSQL_ENCRYPTION_POSTURES[plugin_id]
        self._probe = probe or MssqlProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es SQL Server.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_mssql_service``.
        """
        return is_mssql_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Hace el ``PRELOGIN`` y mira si la postura de cifrado es la de este check.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de conectar. El modo anunciado va a la evidencia
                (``encryption``).

        Returns:
            bool: ``True`` si el servidor anunció la postura de este check;
                ``False`` si anunció otra, no contestó o no era SQL Server.
        """
        context.acquire()
        response = self._probe.fetch(context.target, context.service.port or 1433)
        if response is None:
            return False
        fingerprint = fingerprint_mssql(response)
        if not getattr(fingerprint, self._posture):
            return False
        context.evidence.update({"encryption": fingerprint.encryption})
        return True


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
    """Detecta un servidor de directorio que expone contenido con un bind **anónimo**.

    Que el servidor acepte el bind anónimo no es, por sí solo, el hallazgo:
    todo servidor LDAP conforme al estándar —y en particular cualquier
    controlador de dominio de Active Directory— lo acepta para servir el
    rootDSE público (RFC 4511 §4.2), y eso no expone nada. El hallazgo real es
    que una búsqueda anónima bajo el dominio que el propio servidor publica
    (``namingContexts``) devuelva entradas del directorio: ahí sí hay
    información que debería requerir credenciales y no las pide.

    Por eso el check encadena dos sondas: primero el bind más el rootDSE
    (:meth:`LdapProbe.fetch`, para leer el primer ``namingContexts``) y sólo
    si hay un dominio publicado, una búsqueda de una sola entrada bajo ese
    dominio (:meth:`LdapProbe.fetch_naming_context_entries`). Sin dominio
    publicado no hay base sobre la que buscar, y sin entradas no hay nada que
    el bind anónimo esté exponiendo.

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
        port = context.service.port or 389
        replies = self._probe.fetch(context.target, port)
        if replies is None:
            return False
        naming_contexts = fingerprint_ldap(*replies).naming_contexts
        if not naming_contexts:
            # Sin un dominio publicado no hay base sobre la que buscar, así
            # que no hay forma de confirmar que el bind anónimo expone algo.
            return False
        context.acquire()
        entries_reply = self._probe.fetch_naming_context_entries(
            context.target, naming_contexts[0], port)
        if entries_reply is None:
            return False
        return search_returned_entries(entries_reply)


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


class LdapDomainFunctionalLevelPlugin(ScriptPlugin):
    """Detecta un dominio de Active Directory en un nivel funcional de un Windows Server sin soporte.

    El nivel funcional del dominio fija qué versión de Windows Server es la
    más antigua que puede hacer de controlador de dominio. Uno antiguo suele
    significar que la organización mantiene, por compatibilidad,
    controladores con versiones ya sin parches del fabricante, y deja fuera
    protecciones que sólo existen desde niveles posteriores (como el grupo
    Protected Users, desde 2012 R2).

    Todo controlador de dominio lo publica en su rootDSE sin credenciales
    (``domainFunctionality``). Un directorio que no es Active Directory no lo
    publica y no dispara.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``LdapProbe()``.
    """

    plugin_id = "ldap-domain-functional-level-unsupported"

    def __init__(self, probe: Optional[LdapProbe] = None) -> None:
        self._probe = probe or LdapProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es LDAP.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_ldap_service``.
        """
        return is_ldap_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Lee el rootDSE y dispara si el nivel funcional es de un Windows sin soporte.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de conectar. El nivel y su versión van a la evidencia.

        Returns:
            bool: ``True`` si el nivel es de Windows Server 2012 R2 o anterior;
                ``False`` si es más reciente, no se publica o no hubo respuesta.
        """
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 389)
        if replies is None:
            return False
        fingerprint = fingerprint_ldap(*replies)
        if not fingerprint.is_domain_level_unsupported:
            return False
        context.evidence.update({
            "domainFunctionality": fingerprint.domain_functional_level,
            "windowsVersion": fingerprint.domain_windows_version,
        })
        return True


class LdapNoEncryptedChannelPlugin(ScriptPlugin):
    """Detecta un directorio que no ofrece ninguna vía cifrada: ni LDAPS ni StartTLS.

    Sin ninguna de las dos, todo bind con contraseña —el de cualquier usuario
    o aplicación que se autentique contra el directorio— viaja en claro, y no
    hay configuración de cliente que lo evite.

    Es el complemento de ``ldap-cleartext-with-ldaps``, no su duplicado: aquél
    avisa de un 389 en claro **habiendo** LDAPS en el mismo host; éste sólo
    dispara cuando el host no publica LDAPS **y** el servidor no anuncia
    StartTLS en su rootDSE. Si el rootDSE no trae la lista de extensiones, no
    se sabe si ofrece StartTLS y no dispara.
    """

    plugin_id = "ldap-no-encrypted-channel"

    def __init__(self, probe: Optional[LdapProbe] = None) -> None:
        self._probe = probe or LdapProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es LDAP en claro (no un puerto LDAPS).

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` si es LDAP y su puerto no es de LDAPS.
        """
        return is_ldap_service(service) and service.port not in LDAPS_PORTS

    def run(self, context: ScriptContext) -> bool:
        """Mira si hay LDAPS en el host y, si no, si el servidor anuncia StartTLS.

        Args:
            context: El contexto del check; los servicios hermanos dicen si
                hay LDAPS, y su control de tasa se consulta antes de conectar.

        Returns:
            bool: ``True`` si no hay LDAPS en el host y el servidor publica
                sus extensiones sin StartTLS; ``False`` en cualquier otro caso.
        """
        if any(sibling.port in LDAPS_PORTS for sibling in context.sibling_services):
            return False
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 389)
        if replies is None:
            return False
        return fingerprint_ldap(*replies).supports_starttls is False


def _is_reporting_service(context: ScriptContext, is_same_kind, preferred_ports: Tuple[int, ...]) -> bool:
    """Si este servicio es el que informa de un dato que varios servicios del host repiten.

    El nombre de un equipo sale igual por el 139 que por el 445, y el dominio
    de un directorio igual por el 389 que por el 3268: un aviso por servicio
    repetiría el mismo dato. Informa uno solo: el del primer puerto de
    ``preferred_ports`` que esté abierto o, si no hay ninguno, el más bajo.

    Args:
        context: El contexto del check; ``sibling_services`` trae los
            servicios del host.
        is_same_kind: Predicado que dice si un servicio es de la misma clase.
        preferred_ports: Los puertos preferidos para informar, por orden.

    Returns:
        bool: ``True`` si este servicio es el elegido.
    """
    def rank(port):
        return (preferred_ports.index(port) if port in preferred_ports else len(preferred_ports), port)

    ports = {sibling.port for sibling in context.sibling_services if is_same_kind(sibling)}
    ports.add(context.service.port)
    return min(ports, key=rank) == context.service.port


def _describe_smb_identity(fingerprint) -> Optional[str]:
    """Compone el texto de identidad de un equipo a partir de lo que dijo por SMB.

    Un equipo fuera de dominio (en un grupo de trabajo) contesta con su propio
    nombre donde iría el dominio; en ese caso no se menciona dominio ninguno,
    para no inventar uno.

    Args:
        fingerprint: El ``SmbFingerprint`` con ``hostname``, ``domain`` y
            ``dns_name``.

    Returns:
        Optional[str]: ``"WIN-SRV01 (win-srv01.corp.local, dominio CORP)"`` o
            una parte de eso; ``None`` si el equipo no dijo su nombre.
    """
    if not fingerprint.hostname:
        return None
    details = []
    if fingerprint.dns_name and fingerprint.dns_name.lower() != fingerprint.hostname.lower():
        details.append(fingerprint.dns_name)
    if fingerprint.domain and fingerprint.domain.upper() != fingerprint.hostname.upper():
        details.append(f"dominio {fingerprint.domain}")
    return f"{fingerprint.hostname} ({', '.join(details)})" if details else fingerprint.hostname


def _dns_domain_of(naming_contexts: Tuple[str, ...]) -> Optional[str]:
    """El nombre DNS del primer contexto de nombres que sea sólo ``DC=``.

    ``DC=empresa,DC=local`` es el dominio ``empresa.local``. Los contextos de
    configuración y de esquema (``CN=Configuration,DC=...``) no son el dominio
    y se saltan.

    Args:
        naming_contexts: Los ``namingContexts`` del rootDSE, en su orden.

    Returns:
        Optional[str]: El dominio en minúsculas, o ``None`` si no hay ninguno.
    """
    for context_name in naming_contexts:
        parts = [part.strip() for part in context_name.split(",") if part.strip()]
        if parts and all(part.lower().startswith("dc=") for part in parts):
            return ".".join(part[3:] for part in parts).lower()
    return None


class SmbHostIdentityPlugin(ScriptPlugin):
    """Recoge el nombre de equipo y el dominio que un Windows dice de sí mismo por SMB.

    El dissector de SMB ya los lee, sin credenciales, de la respuesta al inicio
    de sesión; aquí se convierten en un aviso informativo que nombra el activo
    en el informe. No es un riesgo: es contexto (categoría ``host_identity``).

    Args:
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``SmbProbe()``.
    """

    plugin_id = "smb-host-identity"

    def __init__(self, probe: Optional[SmbProbe] = None) -> None:
        self._probe = probe or SmbProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es SMB.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_smb_service``.
        """
        return is_smb_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Negocia SMB, pide la identidad y la deja en la evidencia (``identity``).

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de cada intercambio.

        Returns:
            bool: ``True`` si el equipo dijo su nombre y este servicio es el
                que informa por el host; ``False`` si no.
        """
        if not _is_reporting_service(context, is_smb_service, (445, 139)):
            return False
        port = context.service.port or 445
        context.acquire()
        negotiation = self._probe.fetch(context.target, port)
        if negotiation is None:
            return False
        context.acquire()
        identity = self._probe.fetch_identity(context.target, port)
        description = _describe_smb_identity(fingerprint_smb(*negotiation, identity))
        if description is None:
            return False
        context.evidence.update({"identity": description})
        return True


class LdapDirectoryDomainPlugin(ScriptPlugin):
    """Recoge el dominio que un directorio publica en su rootDSE.

    El nombre de dominio de la organización (``DC=empresa,DC=local``) llega en
    los ``namingContexts`` que el dissector ya lee sin credenciales; aquí se
    convierte en un aviso informativo que nombra el directorio en el informe.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``LdapProbe()``.
    """

    plugin_id = "ldap-directory-domain"

    def __init__(self, probe: Optional[LdapProbe] = None) -> None:
        self._probe = probe or LdapProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es LDAP.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_ldap_service``.
        """
        return is_ldap_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Lee el rootDSE y deja el dominio en la evidencia (``domain``).

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de conectar.

        Returns:
            bool: ``True`` si el directorio publica un dominio y este servicio
                es el que informa por el host; ``False`` si no.
        """
        if not _is_reporting_service(context, is_ldap_service, (389, 636, 3268, 3269)):
            return False
        context.acquire()
        replies = self._probe.fetch(context.target, context.service.port or 389)
        if replies is None:
            return False
        domain = _dns_domain_of(fingerprint_ldap(*replies).naming_contexts)
        if domain is None:
            return False
        context.evidence.update({"domain": domain})
        return True


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

    Cubre sólo el caso intermedio —TLS sin NLA—. Un servidor que ni siquiera
    usa TLS es el caso peor y lo avisa :class:`RdpLegacySecurityLayerPlugin`,
    con más severidad; dispararlos juntos repetiría el mismo problema dos
    veces y escondería cuál de los dos servidores urge más.

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
        fingerprint = fingerprint_rdp(response)
        return (fingerprint.requires_network_level_authentication is False
                and fingerprint.uses_legacy_security_layer is False)


class RdpLegacySecurityLayerPlugin(ScriptPlugin):
    """Detecta un RDP que usa la seguridad propia del protocolo, sin TLS ni NLA.

    La seguridad estándar de RDP es anterior a TLS: cifra con RC4 y no
    verifica la identidad del servidor, así que quien se interponga en la red
    puede hacerse pasar por él y leer las credenciales que el usuario teclee.
    Es peor que un RDP con TLS sin NLA, que al menos protege el canal.

    La evidencia sale de la misma negociación de X.224 que usa el dissector:
    el servidor elige esa seguridad, o rechaza con ``ssl-not-allowed-by-server``
    una petición que sólo ofrecía TLS y NLA. Un modo que no se ha podido leer
    no dispara.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``RdpProbe()``.
    """

    plugin_id = "rdp-legacy-security-layer"

    def __init__(self, probe: Optional[RdpProbe] = None) -> None:
        self._probe = probe or RdpProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es RDP.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_rdp_service``.
        """
        return is_rdp_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Negocia una vez y dispara si el servidor sólo tiene la seguridad antigua.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de conectar.

        Returns:
            bool: ``True`` si el servidor usa la seguridad estándar de RDP;
                ``False`` si usa TLS o NLA, si no contestó o si su respuesta
                no permite decidirlo.
        """
        context.acquire()
        response = self._probe.fetch(context.target, context.service.port or 3389)
        if response is None:
            return False
        return fingerprint_rdp(response).uses_legacy_security_layer is True


#: La petición mínima de WinRM: un POST vacío a su ruta SOAP. El servicio
#: contesta 401 con los métodos de autenticación que acepta antes de mirar el
#: cuerpo, así que no hace falta construir un mensaje WS-Management.
_WINRM_PATH = "/wsman"
_WINRM_HEADERS = {"Content-Type": "application/soap+xml;charset=UTF-8"}

#: Un método Basic entre los que anuncia ``WWW-Authenticate``: al principio de
#: un valor o tras una coma, y como palabra entera (no ``BasicAuth``).
_BASIC_SCHEME_RE = re.compile(r"(?:^|,)\s*basic(?:\s|$|,)", re.IGNORECASE | re.MULTILINE)

#: Lo que distingue a WinRM de cualquier otro servidor HTTP que pida Basic: la
#: pila HTTP del núcleo de Windows que lo sirve, o el reino ``WSMAN`` (también
#: el de OMI, la implementación para Linux).
_WINRM_SERVER_MARKER = "microsoft-httpapi"
_WINRM_REALM_RE = re.compile(r'realm\s*=\s*"?wsman', re.IGNORECASE)


def is_winrm_offering_cleartext_basic(response: Response) -> bool:
    """Si una respuesta de WinRM en claro anuncia autenticación Basic.

    Args:
        response: La respuesta al ``POST /wsman`` sin credenciales.

    Returns:
        bool: ``True`` si se habló HTTP sin TLS, el servidor pidió
            credenciales (``401``), es WinRM y ofrece Basic; ``False`` en
            cualquier otro caso.
    """
    if response.status != 401 or response.requested_scheme == "https":
        return False
    authenticate = response.headers.get("www-authenticate", "")
    is_winrm = (_WINRM_SERVER_MARKER in response.headers.get("server", "").lower()
                or bool(_WINRM_REALM_RE.search(authenticate)))
    return is_winrm and bool(_BASIC_SCHEME_RE.search(authenticate))


class WinrmBasicAuthCleartextPlugin(ScriptPlugin):
    """Detecta un WinRM sin TLS que acepta autenticación Basic.

    WinRM es la administración remota de Windows: ejecuta comandos y consultas
    de gestión sobre el equipo. Con Basic, el cliente manda usuario y
    contraseña en la cabecera ``Authorization`` codificados en Base64, que no
    es cifrado; en el 5985, sin TLS, cualquiera en la red los lee. Da igual
    que el servidor rechace después el mensaje por no ir cifrado: la
    contraseña ya viajó.

    La evidencia es la respuesta del propio servicio a una petición sin
    credenciales: ``401`` con los métodos que acepta en ``WWW-Authenticate``.
    Un WinRM con sólo Kerberos/Negotiate no dispara, ni un servidor HTTP
    cualquiera que pida Basic en ese puerto.

    Args:
        probe: Sonda HTTP inyectable, para que un test no abra conexiones.
            Por defecto, ``HttpProbe()``.
    """

    plugin_id = "winrm-basic-auth-cleartext"

    def __init__(self, probe: Optional[HttpProbe] = None) -> None:
        self._probe = probe or HttpProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio es WinRM sin TLS.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_winrm_service``.
        """
        return is_winrm_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Pide ``/wsman`` sin credenciales y mira qué autenticación se ofrece.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de la petición. Los métodos anunciados van a la
                evidencia (``wwwAuthenticate``).

        Returns:
            bool: ``True`` si el servicio es WinRM en claro y ofrece Basic;
                ``False`` si no, o si no contestó.
        """
        context.acquire()
        response = self._probe.fetch(context.target, context.service.port or 5985, "POST",
                                     _WINRM_PATH, "", dict(_WINRM_HEADERS))
        if response is None or not is_winrm_offering_cleartext_basic(response):
            return False
        context.evidence.update({"wwwAuthenticate": response.headers.get("www-authenticate", "")})
        return True


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
    # Cifrados débiles de verdad: sin cifrado (NULL), 3DES, RC4, DES y
    # exportación. ``@SECLEVEL=0`` hace falta para que OpenSSL 3 los ofrezca.
    # Lo que se ofrece de verdad depende de la build local: OpenSSL ignora las
    # familias que no tiene compiladas, y hoy ninguna build moderna trae RC4,
    # DES ni EXPORT (la de Debian bookworm tampoco), así que en la práctica
    # esta sonda ve NULL y, si la build lo conserva, 3DES. Que un servidor
    # acepte RC4 sólo se vería leyendo su respuesta a un saludo escrito a mano.
    "tls-weak-cipher": "eNULL:3DES:RC4:DES:EXPORT:!aNULL:@SECLEVEL=0",
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


class TlsDeprecatedProtocolPlugin(ScriptPlugin):
    """Detecta que un servicio TLS acepta una versión obsoleta del protocolo (SSLv3, TLS 1.0, TLS 1.1).

    El saludo normal negocia la versión más alta que comparten cliente y
    servidor, así que un servidor que acepta TLS 1.0 **y** 1.2 parece sano. Lo
    que importa es lo más bajo que acepta, porque un atacante en medio puede
    forzar la bajada: se pregunta por cada versión obsoleta por separado, con
    un saludo que sólo ofrece esa versión (una conexión por versión).

    Qué versiones se pueden preguntar depende de la build de OpenSSL local: la
    que no se puede ofrecer cuenta como «no se sabe» y nunca como «no la
    acepta», así que el check no dispara por ella. En la imagen Docker
    (Debian bookworm) SSLv3 no existe, y un servidor que sólo hable SSLv3 no
    se detecta; TLS 1.0 y 1.1 sí.

    Los servicios que cifran a mitad de sesión (FTP, SMTP, IMAP y POP3) se
    preguntan tras su paso a TLS; los que cifran desde el primer byte, sin él.

    Args:
        probe: Sonda inyectable, para que un test use otra. Por defecto,
            ``TlsProbe()``.
    """

    plugin_id = "tls-deprecated-protocol"

    def __init__(self, probe: Optional[TlsProbe] = None) -> None:
        self._probe = probe or TlsProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio habla TLS, desde el primer byte o tras su paso a TLS.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` si merece la pregunta.
        """
        return is_tls_certificate_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Pregunta por cada versión obsoleta y dispara si el servidor acepta alguna.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de cada saludo.

        Returns:
            bool: ``True`` si el servidor aceptó al menos una versión
                obsoleta (van en ``acceptedProtocols`` de la evidencia);
                ``False`` si no aceptó ninguna o no se pudo saber.
        """
        service = context.service
        starttls = starttls_protocol_for(service)
        accepted = []
        for protocol in LEGACY_TLS_PROTOCOLS:
            context.acquire()
            if self._probe.fetch_accepts_protocol(context.target, service.port or 443,
                                                  protocol, starttls=starttls):
                accepted.append(protocol)
        if not accepted:
            return False
        context.evidence.update({"acceptedProtocols": accepted})
        return True


def _load_certificate(der: bytes) -> Optional["x509.Certificate"]:
    """Carga un certificado DER, o ``None`` si está corrupto o mal formado.

    Args:
        der: Los bytes del certificado, tal como llegaron en el saludo.

    Returns:
        Optional[x509.Certificate]: El certificado ya parseado, o ``None``
            ante cualquier error de formato — un certificado que no se puede
            leer no es evidencia de nada.
    """
    try:
        return x509.load_der_x509_certificate(der)
    except (ValueError, UnsupportedAlgorithm):
        return None


#: El mínimo de bits del módulo Diffie-Hellman que no se considera débil. 2048
#: es el umbral tras Logjam (CVE-2015-4000): por debajo, romper una sesión con
#: recursos de un atacante con medios es plausible.
_MINIMUM_DH_GROUP_BITS = 2048

#: Los cifrados DHE clásicos (sin curva elíptica) que este check ofrece, para
#: forzar al servidor a elegir uno de ellos si sabe hacer Diffie-Hellman en
#: absoluto — un ECDHE no dice nada del tamaño de un grupo DH que el servidor
#: podría no usar nunca.
_DHE_ONLY_CIPHER_SUITES: Tuple[int, ...] = (0x009E, 0x009F, 0x0033, 0x0039)


def _speaks_immediate_tls(service: Service) -> bool:
    """Si el servicio cifra desde el primer byte (nunca por ``STARTTLS``).

    Los dos plugins de :mod:`tls_hello` de abajo se limitan a esto: el lector
    en crudo no habla todavía el paso a TLS a mitad de sesión (FTP, SMTP,
    IMAP, POP3) que sí sabe :class:`~.fingerprinting.tls.TlsProbe` —añadirlo
    exigiría exponer las sondas de ``STARTTLS`` de ese módulo, que hoy son
    privadas—, así que estos dos checks se quedan fuera de esos protocolos
    hasta que esa pieza exista. Los checks de versión y cifrado ya existentes
    (:class:`TlsDeprecatedProtocolPlugin`, :class:`TlsWeakCipherFamilyPlugin`)
    sí los cubren, porque usan ``TlsProbe``.
    """
    return is_tls_certificate_service(service) and starttls_protocol_for(service) is None


class TlsIncompleteCertificateChainPlugin(ScriptPlugin):
    """Detecta un servidor TLS que no manda el certificado intermedio.

    Un navegador valida el certificado de hoja subiendo la cadena de
    emisores hasta una raíz de confianza ya instalada; si al servidor le
    falta el intermedio, esa subida se corta y la conexión no valida, aunque
    la hoja en sí sea perfectamente válida. Es un descuido de despliegue
    distinto del autofirmado o el caducado —esos ya tienen su propio check—:
    aquí la hoja está bien, lo que falta es lo que la conecta con una raíz.

    **La evidencia es contar certificados, no construir la cadena.** Validar
    de verdad hasta una raíz exigiría traer el almacén de confianza del
    sistema y las reglas de verificación de rutas completas —fuera del
    alcance de un cliente mínimo—. El indicio barato y fiable es que el
    servidor mande **sólo la hoja**: un despliegue sano manda la hoja y al
    menos un intermedio, y uno con la cadena rota manda uno solo. Un
    certificado de hoja autofirmado (``subject == issuer``) se descarta aquí
    a propósito: no le falta nada que completar, y ya lo cubre
    ``tls-self-signed-cert``.

    Args:
        probe: Sonda inyectable, para que un test use un socket falso. Por
            defecto, ``TlsHelloProbe()``.
    """

    plugin_id = "tls-incomplete-certificate-chain"

    def __init__(self, probe: Optional[TlsHelloProbe] = None) -> None:
        self._probe = probe or TlsHelloProbe()

    def applies(self, service: Service) -> bool:
        return _speaks_immediate_tls(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        flight = self._probe.query(
            context.target, context.service.port or 443,
            versions=(VERSION_TLS_1_2,), server_name=context.target)
        if flight is None:
            return False
        certificates = parse_certificate_message(flight.get_message(HANDSHAKE_CERTIFICATE))
        if len(certificates) != 1:
            # Ni el mensaje faltó/vino vacío, ni hay dos o más — sea lo que sea,
            # no es el caso "sólo la hoja" que este check busca.
            return False
        leaf = _load_certificate(certificates[0])
        if leaf is None or leaf.issuer == leaf.subject:
            return False
        context.evidence.update({"chainLength": 1})
        return True


class TlsWeakKeyExchangeGroupPlugin(ScriptPlugin):
    """Detecta un servidor TLS que negocia un grupo Diffie-Hellman débil.

    ``tls-weak-cipher`` ya cubre el cifrado simétrico; esto es otra cosa: el
    tamaño del grupo con el que las dos partes acuerdan la clave de sesión,
    independiente del cifrado que la use después. Un grupo corto (herencia de
    cuando exportar criptografía fuerte estaba restringido) es rompible con
    recursos de un atacante con medios — el ataque Logjam (CVE-2015-4000).

    Se ofrecen sólo cifrados DHE clásicos (:data:`_DHE_ONLY_CIPHER_SUITES`,
    sin curva elíptica) para forzar al servidor a elegir uno si sabe hacer
    Diffie-Hellman en absoluto; un servidor que sólo ofrece ECDHE no tiene
    nada que este check pueda medir, y no dispara.

    Args:
        probe: Sonda inyectable. Por defecto, ``TlsHelloProbe()``.
    """

    plugin_id = "tls-weak-key-exchange-group"

    def __init__(self, probe: Optional[TlsHelloProbe] = None) -> None:
        self._probe = probe or TlsHelloProbe()

    def applies(self, service: Service) -> bool:
        return _speaks_immediate_tls(service)

    def run(self, context: ScriptContext) -> bool:
        context.acquire()
        flight = self._probe.query(
            context.target, context.service.port or 443,
            versions=(VERSION_TLS_1_2,), cipher_suites=_DHE_ONLY_CIPHER_SUITES,
            server_name=context.target)
        if flight is None or flight.server_hello is None:
            return False
        if flight.server_hello.cipher_suite not in _DHE_ONLY_CIPHER_SUITES:
            return False
        bits = parse_dhe_server_key_exchange(flight.get_message(HANDSHAKE_SERVER_KEY_EXCHANGE))
        if bits is None or bits >= _MINIMUM_DH_GROUP_BITS:
            return False
        context.evidence.update({"groupBits": bits})
        return True


# La cabecera de un ``<script src="...">``, para descubrir qué JavaScript sirve
# la página sin ejecutar nada. Simple a propósito — es un descubridor de
# rutas, no un navegador — igual que el ``_HREF_RE`` del rastreador.
_SCRIPT_SRC_RE = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["\']([^"\'#\s]+)["\']""", re.IGNORECASE)

# El comentario que enlaza un JavaScript minificado con su mapa de código
# fuente (fuente: la especificación del propio formato, "Source Map Revision
# 3"). ``//#`` es la forma moderna; ``//@`` es la que usaron las primeras
# herramientas y algunas todavía emiten.
_SOURCE_MAPPING_URL_RE = re.compile(r"//[#@]\s*sourceMappingURL=(\S+)")

# Cuántos ficheros JavaScript de la portada se llegan a pedir, como mucho: un
# tope barato para no convertir este check en un rastreo del sitio entero.
_MAX_SCRIPTS_CHECKED = 8

# Lo que distingue a un mapa de código fuente real de una página de error que
# por casualidad contesta 200 (formato "Source Map Revision 3": ambas claves
# son obligatorias en todo mapa válido).
_SOURCE_MAP_MARKERS = ('"mappings"', '"sources"')


def _reference_response(probe: HttpProbe, target: str, port: int) -> Optional[Baseline]:
    """La respuesta de un servicio HTTP a una ruta que con toda seguridad no existe.

    Función de módulo y no método: no toca más estado que la sonda que recibe
    por parámetro (CONVENCIONES.md §5.1) — la usa
    :class:`SourceMapExposedPlugin`, una sola vez por ejecución.

    Args:
        probe: La sonda HTTP con la que pedir la ruta.
        target: El objetivo.
        port: El puerto del servicio HTTP.

    Returns:
        Optional[Baseline]: La referencia, o ``None`` si el servicio no
            contestó — sin referencia no se descarta nada.
    """
    path = baseline_path()
    response = probe.fetch(target, port, "GET", path)
    return None if response is None else Baseline.from_response(path, response)


def _same_origin_script_urls(base_path: str, body: str) -> List[str]:
    """Las rutas de los ``<script src="...">`` de una página, del mismo origen.

    Un ``src`` absoluto a otro host (``https://cdn.terceros.test/x.js``) se
    descarta: este check sólo audita el JavaScript propio del sitio, nunca el
    de un tercero. Uno relativo se resuelve contra la ruta de la página.

    Args:
        base_path: La ruta de la página que se acaba de leer.
        body: Su cuerpo HTML.

    Returns:
        List[str]: Las rutas, sin repetir, en el orden en que aparecen.
    """
    urls: List[str] = []
    for raw in _SCRIPT_SRC_RE.findall(body):
        split = urllib.parse.urlsplit(raw)
        if split.netloc:
            continue
        resolved = urllib.parse.urljoin(base_path, split.path)
        if resolved and resolved not in urls:
            urls.append(resolved)
    return urls


class SourceMapExposedPlugin(ScriptPlugin):
    """Detecta un mapa de código fuente publicado junto a un JavaScript minificado.

    Una herramienta de empaquetado suele generar, junto al JavaScript que de
    verdad sirve al navegador, un "mapa de código fuente": un fichero que
    traduce ese código minificado de vuelta al original, con nombres de
    variables y comentarios — pensado para depurar en desarrollo. Si se
    publica por error en producción, regala el código fuente completo del
    frontend: lógica de negocio, rutas internas de la API y, a veces, una
    credencial que alguien dejó como constante pensando que sólo existiría
    minificada.

    El propio JavaScript delata el mapa: termina con un comentario
    ``//# sourceMappingURL=archivo.js.map`` que el navegador usa para
    encontrarlo al depurar. Este check lee esa referencia y comprueba si el
    fichero al que apunta existe y de verdad tiene forma de mapa — no basta
    con que conteste 200, porque un sitio que contesta 200 a cualquier ruta
    "tendría" un mapa en todas partes (de ahí la referencia propia, igual que
    L102: no se puede usar la de ``CheckRuntime`` porque un plugin ``script``
    no tiene acceso al runtime que lo invoca).

    Args:
        probe: Sonda HTTP inyectable, para que un test no abra conexiones.
            Por defecto, ``HttpProbe()``.
    """

    plugin_id = "source-map-exposed"

    def __init__(self, probe: Optional[HttpProbe] = None) -> None:
        self._probe = probe or HttpProbe()

    def applies(self, service: Service) -> bool:
        """Si el servicio habla HTTP.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_http_service``.
        """
        return is_http_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Lee la portada, sigue sus scripts propios y comprueba su mapa de código fuente.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de cada petición.

        Returns:
            bool: ``True`` en el primer mapa que se encuentra publicado y con
                forma de mapa real; ``False`` si ninguno de los scripts
                examinados referencia uno, si el que referencian no existe, o
                si la respuesta es la genérica de un sitio que contesta 200 a
                todo.
        """
        port = context.service.port or 80
        context.acquire()
        page = self._probe.fetch(context.target, port, "GET", "/")
        if page is None:
            return False
        reference: Optional[Baseline] = None
        for script_path in _same_origin_script_urls("/", page.body or "")[:_MAX_SCRIPTS_CHECKED]:
            context.acquire()
            script = self._probe.fetch(context.target, port, "GET", script_path)
            if script is None or script.status != 200:
                continue
            match = _SOURCE_MAPPING_URL_RE.search(script.body or "")
            if not match:
                continue
            map_path = urllib.parse.urljoin(script_path, match.group(1))
            if urllib.parse.urlsplit(map_path).netloc:
                continue                                  # el mapa apunta a otro origen
            context.acquire()
            map_response = self._probe.fetch(context.target, port, "GET", map_path)
            if map_response is None or map_response.status != 200:
                continue
            if not all(marker in map_response.body for marker in _SOURCE_MAP_MARKERS):
                continue
            if reference is None:
                # Una sola vez por ejecución del plugin (el primer mapa que
                # parece real la dispara; los siguientes candidatos la
                # reutilizan), no una vez por script examinado.
                reference = _reference_response(self._probe, context.target, port)
            if reference is not None and reference.resembles(map_response, map_path):
                continue
            context.evidence.update({"scriptPath": script_path, "sourceMapPath": map_path})
            return True
        return False


class WindowsSharesUnauthenticatedPlugin(ScriptPlugin):
    """Detecta carpetas compartidas de Windows visibles sin ninguna credencial.

    Lista las carpetas con el cliente mínimo de llamadas remotas de Windows
    (:func:`~.fingerprinting.windows_rpc.fetch_shares`), con una sesión
    anónima — nunca una credencial real. El hallazgo es que la **lista de
    nombres** es visible sin autenticar, no lo que hay dentro de cada una:
    este plugin nunca abre ni lee el contenido de ninguna carpeta.

    **Las compartidas administrativas no cuentan.** ``ADMIN$``, ``C$``,
    ``IPC$``… existen por defecto en cualquier Windows, se listen o no, así
    que su sola presencia no dice nada sobre este equipo en particular —
    dispararía en todos. La evidencia tiene que ser una carpeta real
    (``ShareInfo.is_hidden`` es ``False``): la que alguien creó a propósito y
    dejó visible sin restringir el acceso.

    Args:
        fetch_shares: La función que lista las carpetas, inyectable para que
            un test no abra conexiones. Por defecto,
            :func:`~.fingerprinting.windows_rpc.fetch_shares`.
    """

    plugin_id = "windows-shares-unauthenticated"

    def __init__(self, fetch_shares: Optional[Callable] = None) -> None:
        self._fetch_shares = fetch_shares or windows_rpc.fetch_shares

    def applies(self, service: Service) -> bool:
        """Si el servicio es SMB.

        Args:
            service: El servicio candidato.

        Returns:
            bool: ``True`` para los servicios que reclama ``is_smb_service``.
        """
        return is_smb_service(service)

    def run(self, context: ScriptContext) -> bool:
        """Lista las carpetas compartidas y dispara si alguna no es administrativa.

        Args:
            context: El contexto del check; su control de tasa se consulta
                antes de la llamada.

        Returns:
            bool: ``True`` si al menos una carpeta real (no administrativa)
                es visible sin credenciales; ``False`` si la lista viene
                vacía, si el equipo no permitió la sesión anónima, o si sólo
                aparecen compartidas administrativas.
        """
        context.acquire()
        shares = self._fetch_shares(context.target, context.service.port or 445)
        visible = [share.name for share in shares if not share.is_hidden]
        if not visible:
            return False
        context.evidence.update({"shares": visible})
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
        PostgresPasswordWithoutTlsPlugin(),
        MongoUnauthenticatedAccessPlugin(),
        LdapAnonymousBindPlugin(),
        LdapCleartextWithLdapsPlugin(),
        LdapNoEncryptedChannelPlugin(),
        LdapDomainFunctionalLevelPlugin(),
        LdapDirectoryDomainPlugin(),
        SmbHostIdentityPlugin(),
        RdpNlaNotRequiredPlugin(),
        RdpLegacySecurityLayerPlugin(),
        WinrmBasicAuthCleartextPlugin(),
        TelnetEnabledPlugin(),
        TlsIncompleteCertificateChainPlugin(),
        TlsWeakKeyExchangeGroupPlugin(),
        SourceMapExposedPlugin(),
        WindowsSharesUnauthenticatedPlugin(),
        VncNoAuthenticationPlugin(),
        IkeWeakTransformPlugin(),
        TcpTimestampsPlugin(),
        TlsDeprecatedProtocolPlugin(),
    )
    plugins += tuple(TlsWeakCipherFamilyPlugin(plugin_id) for plugin_id in _TLS12_WEAK_CIPHER_FAMILIES)
    plugins += tuple(MssqlEncryptionPlugin(plugin_id) for plugin_id in _MSSQL_ENCRYPTION_POSTURES)
    ssh_cache = _KexinitCache()
    plugins += tuple(SshWeakAlgorithmsPlugin(family, ssh_cache)
                     for family in _WEAK_ALGORITHM_FAMILIES)
    plugins += (SshTerrapinPlugin(True, ssh_cache), SshTerrapinPlugin(False, ssh_cache))
    return {plugin.plugin_id: plugin for plugin in plugins}
