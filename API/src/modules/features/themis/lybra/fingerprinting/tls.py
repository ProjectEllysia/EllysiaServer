"""The TLS dissector: a single-handshake hygiene check, not identification.

Reads the negotiated protocol version and the self-signed/expiry status of the
certificate. Aparte, :meth:`TlsProbe.fetch_accepts_protocol` y
:meth:`TlsProbe.fetch_accepted_tls12_cipher` preguntan por lo que el servidor
acepta sin elegirlo (versiones obsoletas, familias de cifrado débiles), con un
saludo que sólo ofrece eso.

**JARM: archivado, no pendiente** (2026-09-02). Este módulo hace **un**
handshake, y de ahí salen la versión de protocolo, el autofirmado y la
caducidad. JARM haría diez saludos deliberadamente distintos y hashearía el
conjunto para identificar la *pila* TLS, no el producto.

No se va a construir, y la razón de fondo cabe en una frase: **el valor de JARM
es comparativo**. Un hash que no coincida bit a bit con el de la implementación
de referencia no es una identificación peor, es ninguna — un número que no se
puede buscar en ningún catálogo. Y comprobar esa coincidencia exige un
laboratorio con varias pilas TLS distintas (OpenSSL, BoringSSL, Schannel,
JSSE), que no existe aquí.

A eso se suma que nada del fingerprinting depende de él —su medida de éxito es
la concordancia frente a Nmap, no JARM—, que es de lo menos prioritario que hay
pendiente, y que diez saludos por servicio TLS es la sonda más cara del
catálogo a cambio de un dato que nadie consultaría.

Qué haría falta para reabrirlo: un laboratorio con al menos cuatro pilas TLS
distintas contra el que comprobar que el hash coincide con el de la
implementación de referencia, y alguien que de verdad vaya a consumir el hash
—un catálogo de JARMs conocidos, o la necesidad de reconocer infraestructura
que no dice nada de sí misma—. No es un "todavía no": es un "no, y por esto".
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import dsa, ec, rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TlsInfo:
    """The result of a single TLS handshake, read for hygiene, not identity.

    Attributes:
        protocol: The negotiated protocol version, e.g. ``"TLSv1.2"``.
        cipher: The negotiated cipher suite name.
        subject_cn: The certificate's subject common name, or ``None``.
        issuer_cn: The certificate's issuer common name, or ``None``.
        self_signed: Whether the certificate's issuer equals its subject.
        expired: Whether the certificate's ``notAfter`` is in the past.
        days_until_expiry: Days remaining before expiry (negative if expired),
            or ``None`` if the certificate could not be parsed.
        names: Los nombres para los que el certificado es válido: el CN y los
            DNS del SAN, en minúsculas. Por defecto vacío.
        requested_name: El nombre que se pidió en el SNI, o ``None`` si se
            conectó por IP (y entonces no hay nombre con el que comparar).
        public_key_type: El tipo de la clave pública: ``"rsa"``, ``"dsa"``,
            ``"ec"``, otro nombre en minúsculas para los demás (``"ed25519"``),
            o ``None`` si no se pudo leer. Por defecto ``None``.
        public_key_bits: El tamaño de la clave pública en bits, o ``None`` si
            el tipo no lo tiene (Ed25519) o no se pudo leer. Por defecto ``None``.
        signature_hash: El resumen con el que está firmado el certificado, en
            minúsculas (``"sha256"``, ``"sha1"``, ``"md5"``), o ``None`` si la
            firma no usa uno aparte (Ed25519) o no se pudo leer. Por defecto
            ``None``.
    """
    protocol: Optional[str]
    cipher: Optional[str]
    subject_cn: Optional[str]
    issuer_cn: Optional[str]
    self_signed: bool
    expired: bool
    days_until_expiry: Optional[int]
    names: tuple = ()
    requested_name: Optional[str] = None
    public_key_type: Optional[str] = None
    public_key_bits: Optional[int] = None
    signature_hash: Optional[str] = None

    @property
    def is_name_mismatch(self) -> bool:
        """Si se pidió un nombre y el certificado no lo cubre (comodines de un nivel incluidos)."""
        if not self.requested_name or not self.names:
            return False
        requested = self.requested_name.lower().rstrip(".")
        for name in self.names:
            if name == requested:
                return False
            if name.startswith("*.") and requested.count(".") == name.count(".") \
                    and requested.endswith(name[1:]):
                return False
        return True


def _common_name(name: "x509.Name") -> Optional[str]:
    """Extract the common name from an X.509 ``Name``, best-effort."""
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(attrs[0].value) if attrs else None


def _public_key_facts(cert) -> tuple:
    """El tipo y el tamaño en bits de la clave pública de un certificado.

    Args:
        cert: El certificado ya cargado (``x509.Certificate``).

    Returns:
        tuple: ``(tipo, bits)``. El tipo es ``"rsa"``, ``"dsa"``, ``"ec"`` o
            el nombre de la clase en minúsculas para los demás; los bits son
            ``None`` si el tipo no tiene tamaño variable. ``(None, None)`` si
            la clave no se pudo leer.
    """
    try:
        key = cert.public_key()
    except (ValueError, UnsupportedAlgorithm):
        return None, None
    if isinstance(key, rsa.RSAPublicKey):
        return "rsa", key.key_size
    if isinstance(key, dsa.DSAPublicKey):
        return "dsa", key.key_size
    if isinstance(key, ec.EllipticCurvePublicKey):
        return "ec", key.curve.key_size
    return type(key).__name__.lower().replace("publickey", "").lstrip("_"), None


def _signature_hash(cert) -> Optional[str]:
    """El resumen con el que está firmado un certificado, o ``None`` si no usa uno aparte.

    Args:
        cert: El certificado ya cargado (``x509.Certificate``).

    Returns:
        Optional[str]: El nombre del resumen en minúsculas (``"sha256"``),
            o ``None`` para firmas sin resumen aparte (Ed25519) o ilegibles.
    """
    try:
        algorithm = cert.signature_hash_algorithm
    except UnsupportedAlgorithm:
        return None
    return algorithm.name.lower() if algorithm is not None else None


def _is_ip_literal(host: str) -> bool:
    """Si ``host`` es una IP escrita tal cual, y no un nombre."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _certificate_names(cert) -> tuple:
    """El CN y los nombres DNS del SAN de un certificado, en minúsculas y sin repetir."""
    names = []
    common_name = _common_name(cert.subject)
    if common_name:
        names.append(common_name.lower())
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names.extend(name.lower() for name in san.get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound:
        pass
    return tuple(dict.fromkeys(names))


def _read_status_reply(sock) -> str:
    """Lee una respuesta completa de FTP o SMTP, incluidas las multilínea (``220-...`` hasta ``220 ...``).

    Los dos protocolos comparten la forma: un código de tres cifras seguido de
    ``-`` en las líneas que continúan y de un espacio en la que cierra.

    Args:
        sock: El socket, ya conectado.

    Returns:
        str: Las líneas de la respuesta, unidas por saltos de línea; lo que
            haya llegado si el servidor cierra antes.
    """
    buffer = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return buffer.decode("latin-1", "ignore")
        buffer += chunk
        lines = buffer.decode("latin-1", "ignore").splitlines()
        if lines and buffer.endswith(b"\n") and len(lines[-1]) >= 4 and lines[-1][3] == " ":
            return "\n".join(lines)


def _upgrade_ftp(sock) -> bool:
    """Pide ``AUTH TLS`` tras el saludo FTP; ``True`` si el servidor acepta (``234``)."""
    try:
        _read_status_reply(sock)
        sock.sendall(b"AUTH TLS\r\n")
        return _read_status_reply(sock).rsplit("\n", 1)[-1].startswith("234")
    except OSError:
        return False


#: Tope de una línea de texto leída durante el paso a TLS: un servidor roto no
#: puede hacer que se lea para siempre.
_MAX_UPGRADE_LINE_BYTES = 4096

#: Cuántas líneas sin etiqueta de IMAP se toleran antes de la respuesta.
_MAX_UNTAGGED_LINES = 16


def _upgrade_smtp(sock) -> bool:
    """Pide ``STARTTLS`` tras el saludo y el ``EHLO`` de SMTP (RFC 3207).

    Args:
        sock: El socket, recién conectado.

    Returns:
        bool: ``True`` si el servidor acepta pasar a TLS (``220``); ``False``
            si lo rechaza o la conexión falla.
    """
    try:
        _read_status_reply(sock)
        sock.sendall(b"EHLO lybra.local\r\n")
        _read_status_reply(sock)
        sock.sendall(b"STARTTLS\r\n")
        return _read_status_reply(sock).rsplit("\n", 1)[-1].startswith("220")
    except OSError:
        return False


def _read_text_line(sock) -> str:
    """Lee una línea de texto (hasta LF) de un socket, sin leer más allá de ella.

    Byte a byte a propósito: tras la respuesta al paso a TLS empieza el
    saludo TLS, y un ``recv`` más largo se comería sus primeros bytes.

    Args:
        sock: El socket, ya conectado.

    Returns:
        str: La línea, sin el salto; lo que haya llegado si el servidor cierra.
    """
    line = b""
    while not line.endswith(b"\n") and len(line) < _MAX_UPGRADE_LINE_BYTES:
        byte = sock.recv(1)
        if not byte:
            break
        line += byte
    return line.decode("latin-1", "ignore").rstrip("\r\n")


def _upgrade_imap(sock) -> bool:
    """Pide ``STARTTLS`` tras el saludo de IMAP (RFC 3501 §6.2.1).

    Las líneas sin etiqueta (``* ...``) que el servidor mande antes de la
    respuesta se descartan; la que decide es la que empieza por la etiqueta.

    Args:
        sock: El socket, recién conectado.

    Returns:
        bool: ``True`` si el servidor acepta pasar a TLS (``a1 OK``);
            ``False`` si lo rechaza o la conexión falla.
    """
    try:
        _read_text_line(sock)
        sock.sendall(b"a1 STARTTLS\r\n")
        for _ in range(_MAX_UNTAGGED_LINES):
            line = _read_text_line(sock)
            if not line:
                return False
            if line.startswith("a1 "):
                return line[3:].upper().startswith("OK")
        return False
    except OSError:
        return False


def _upgrade_pop3(sock) -> bool:
    """Pide ``STLS`` tras el saludo de POP3 (RFC 2595 §4).

    Args:
        sock: El socket, recién conectado.

    Returns:
        bool: ``True`` si el servidor acepta pasar a TLS (``+OK``); ``False``
            si lo rechaza o la conexión falla.
    """
    try:
        _read_text_line(sock)
        sock.sendall(b"STLS\r\n")
        return _read_text_line(sock).startswith("+OK")
    except OSError:
        return False


#: Cómo pasar a TLS cada protocolo que cifra a mitad de sesión. Las claves son
#: las que devuelve ``checks.starttls_protocol_for``.
_STARTTLS_UPGRADES: Dict[str, Callable] = {
    "ftp": _upgrade_ftp,
    "smtp": _upgrade_smtp,
    "imap": _upgrade_imap,
    "pop3": _upgrade_pop3,
}


#: Las versiones de protocolo obsoletas por las que se pregunta una a una, con
#: el nombre que da ``SSLSocket.version()``. SSLv2 no está: ningún OpenSSL de
#: los últimos diez años sabe hablarlo.
LEGACY_TLS_PROTOCOLS = ("SSLv3", "TLSv1", "TLSv1.1")

_LEGACY_TLS_VERSIONS = {
    "SSLv3": ("HAS_SSLv3", "SSLv3"),
    "TLSv1": ("HAS_TLSv1", "TLSv1"),
    "TLSv1.1": ("HAS_TLSv1_1", "TLSv1_1"),
}

#: Motivos de ``ssl.SSLError`` con los que OpenSSL se niega a saludar por una
#: limitación propia, antes de que el servidor diga nada.
_LOCAL_REFUSAL_REASONS = {"NO_PROTOCOLS_AVAILABLE", "NO_CIPHERS_AVAILABLE",
                          "UNSUPPORTED_PROTOCOL"}


def _legacy_protocol_context(protocol: str) -> Optional[ssl.SSLContext]:
    """Construye un contexto cliente que sólo ofrece ``protocol``, si la build local lo permite.

    Args:
        protocol: Una clave de ``_LEGACY_TLS_VERSIONS`` (``"SSLv3"``,
            ``"TLSv1"`` o ``"TLSv1.1"``).

    Returns:
        Optional[ssl.SSLContext]: El contexto, sin verificación de certificado
            y con ``@SECLEVEL=0``; ``None`` si la versión es desconocida o el
            OpenSSL local no la tiene compilada o no deja fijarla.
    """
    names = _LEGACY_TLS_VERSIONS.get(protocol)
    if names is None or not getattr(ssl, names[0], False):
        return None
    try:
        version = getattr(ssl.TLSVersion, names[1])
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = version
        context.maximum_version = version
        context.set_ciphers("ALL:@SECLEVEL=0")
    except (AttributeError, ValueError, ssl.SSLError):
        return None
    return context


class TlsProbe:
    """Performs a single, unverified TLS handshake to read protocol and cert.

    We are scanning arbitrary hosts whose certificates we do not control, so
    verification is deliberately disabled — a self-signed or expired cert is
    exactly the kind of thing this probe exists to report, not reject.

    Args:
        timeout: The connection timeout, in seconds.
        connect: An injectable ``(address, timeout) -> socket`` callable, same
            pattern as :class:`~.ssh.SshProbe`.
    """

    def __init__(self, timeout: float = 8.0, connect: Optional[Callable] = None) -> None:
        self._timeout = timeout
        self._connect = connect or socket.create_connection

    def fetch(self, host: str, port: int, starttls: Optional[str] = None) -> Optional[TlsInfo]:
        """Handshake with ``host:port`` and return the certificate's hygiene facts.

        Args:
            host: The target host.
            port: The target port.
            starttls: El protocolo en claro que hay que hablar antes de pasar a
                TLS, para los servicios que cifran a mitad de sesión en vez de
                desde el primer byte: ``"ftp"`` (``AUTH TLS``), ``"smtp"``
                (``STARTTLS``), ``"imap"`` (``STARTTLS``) o ``"pop3"``
                (``STLS``). Por defecto ``None``: TLS desde el primer byte.

        Returns:
            A :class:`TlsInfo`, or ``None`` on any connection/handshake failure
            — incluido un servidor que rechaza el paso a TLS.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            sock = self._connect((host, port), self._timeout)
        except OSError as err:
            logger.debug("TLS connect failed for %s:%s: %s", host, port, err)
            return None
        if starttls is not None and not _STARTTLS_UPGRADES[starttls](sock):
            logger.debug("STARTTLS (%s) rejected by %s:%s", starttls, host, port)
            sock.close()
            return None
        try:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                der = tls_sock.getpeercert(binary_form=True)
                protocol = tls_sock.version()
                cipher = tls_sock.cipher()
        except (OSError, ssl.SSLError) as err:
            logger.debug("TLS handshake failed for %s:%s: %s", host, port, err)
            return None
        if der is None:
            return None
        info = self._parse_cert(der, protocol, cipher[0] if cipher else None)
        if info is None or _is_ip_literal(host):
            return info
        return replace(info, requested_name=host)

    def fetch_accepted_tls12_cipher(self, host: str, port: int, ciphers: str) -> Optional[str]:
        """Qué conjunto de ``ciphers`` acepta el servidor en TLS 1.2, si acepta alguno.

        Un servidor suele aceptar muchos conjuntos de cifrado y un cliente
        moderno elige el mejor, así que el saludo de :meth:`fetch` casi nunca
        enseña los débiles. Aquí se ofrece **sólo** una familia concreta: si el
        servidor completa el saludo, la acepta. Se fija TLS 1.2 porque en TLS
        1.3 no se pueden ofrecer conjuntos débiles.

        Args:
            host: El objetivo. Si es un nombre, viaja en el SNI.
            port: El puerto TLS.
            ciphers: La familia a ofrecer, en la sintaxis de cadenas de cifrado
                de OpenSSL (``"kRSA:!aNULL:!eNULL"``).

        Returns:
            Optional[str]: El nombre del conjunto que el servidor eligió si
                aceptó la familia; ``""`` si la rechazó; ``None`` si no se
                pudo saber (la conexión falló o el OpenSSL local no tiene
                ningún conjunto de la familia, o no puede ofrecerlo).
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        try:
            context.set_ciphers(ciphers)
        except ssl.SSLError:
            return None
        try:
            sock = self._connect((host, port), self._timeout)
        except OSError as err:
            logger.debug("TLS connect failed for %s:%s: %s", host, port, err)
            return None
        server_hostname = None if _is_ip_literal(host) else host
        try:
            with context.wrap_socket(sock, server_hostname=server_hostname) as tls_sock:
                cipher = tls_sock.cipher()
        except ssl.SSLError as err:
            if err.reason in _LOCAL_REFUSAL_REASONS:
                return None
            return ""
        except OSError as err:
            logger.debug("TLS handshake failed for %s:%s: %s", host, port, err)
            return None
        return cipher[0] if cipher else ""

    def fetch_accepts_protocol(self, host: str, port: int, protocol: str,
                               starttls: Optional[str] = None) -> Optional[bool]:
        """Pregunta al servidor si acepta una versión concreta de TLS, aunque no sea la que elegiría.

        Un cliente moderno ofrece TLS 1.2 y 1.3 y el servidor elige la más alta
        que tengan en común, así que el saludo de :meth:`fetch` nunca enseña que
        el servidor **también** acepta TLS 1.0. Aquí se ofrece sólo
        ``protocol`` —mínimo y máximo fijados a esa versión— con el nivel de
        seguridad de OpenSSL rebajado a 0 (``@SECLEVEL=0``), que es lo justo
        para que OpenSSL 3 vuelva a permitir esas versiones y sus cifrados. Se
        cierra la conexión tras el saludo, sin enviar datos de aplicación.

        El resultado depende de la build de OpenSSL local: si no se compiló con
        la versión pedida (el SSLv3 no existe en las de Debian, por ejemplo), no
        se puede ofrecer, y eso se detecta aquí y se contesta «no se sabe»,
        nunca «no la acepta».

        Args:
            host: El objetivo. Si es un nombre, viaja en el SNI.
            port: El puerto TLS.
            protocol: La versión a ofrecer, con el nombre que da
                ``SSLSocket.version()``: ``"SSLv3"``, ``"TLSv1"`` o
                ``"TLSv1.1"`` (ver :data:`LEGACY_TLS_PROTOCOLS`).
            starttls: Igual que en :meth:`fetch`: el protocolo en claro que hay
                que hablar antes de pasar a TLS (``"ftp"``, ``"smtp"``,
                ``"imap"`` o ``"pop3"``). Por defecto ``None``, TLS desde el
                primer byte.

        Returns:
            Optional[bool]: ``True`` si el servidor completó el saludo en esa
                versión; ``False`` si lo rechazó; ``None`` si no se pudo
                saber: la build local no puede ofrecer la versión, la conexión
                falló o el servidor rechazó el paso a TLS.
        """
        context = _legacy_protocol_context(protocol)
        if context is None:
            logger.debug("La build local de OpenSSL no puede ofrecer %s", protocol)
            return None
        try:
            sock = self._connect((host, port), self._timeout)
        except OSError as err:
            logger.debug("TLS connect failed for %s:%s: %s", host, port, err)
            return None
        if starttls is not None and not _STARTTLS_UPGRADES[starttls](sock):
            sock.close()
            return None
        server_hostname = None if _is_ip_literal(host) else host
        try:
            with context.wrap_socket(sock, server_hostname=server_hostname) as tls_sock:
                return tls_sock.version() == protocol
        except ssl.SSLError as err:
            # OpenSSL se niega antes de escribir nada si, pese a todo, no le
            # queda ninguna versión que ofrecer: eso es una limitación local,
            # no una respuesta del servidor.
            if err.reason in _LOCAL_REFUSAL_REASONS:
                return None
            return False
        except OSError as err:
            logger.debug("TLS handshake failed for %s:%s: %s", host, port, err)
            return None

    @staticmethod
    def _parse_cert(der: bytes, protocol: Optional[str], cipher: Optional[str]) -> Optional[TlsInfo]:
        """Parse a DER certificate into a :class:`TlsInfo`, best-effort."""
        try:
            cert = x509.load_der_x509_certificate(der)
        except ValueError as err:
            logger.debug("TLS certificate parse failed: %s", err)
            return None
        # not_valid_after_utc (tz-aware) landed in cryptography 42; requirements.txt
        # only pins >=41.0.4, so fall back to the naive attribute on older installs.
        not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=timezone.utc)
        days_until_expiry = (not_after - datetime.now(timezone.utc)).days
        public_key_type, public_key_bits = _public_key_facts(cert)
        return TlsInfo(
            protocol=protocol,
            cipher=cipher,
            subject_cn=_common_name(cert.subject),
            issuer_cn=_common_name(cert.issuer),
            self_signed=cert.issuer == cert.subject,
            expired=days_until_expiry < 0,
            days_until_expiry=days_until_expiry,
            names=_certificate_names(cert),
            public_key_type=public_key_type,
            public_key_bits=public_key_bits,
            signature_hash=_signature_hash(cert),
        )
