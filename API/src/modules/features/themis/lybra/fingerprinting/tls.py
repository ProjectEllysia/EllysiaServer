"""The TLS dissector: a single-handshake hygiene check, not identification.

Reads the negotiated protocol version and the self-signed/expiry status of the
certificate.

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


def _read_ftp_reply(sock) -> str:
    """Lee una respuesta FTP completa, incluidas las multilínea (``220-...`` hasta ``220 ...``)."""
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
        _read_ftp_reply(sock)
        sock.sendall(b"AUTH TLS\r\n")
        return _read_ftp_reply(sock).rsplit("\n", 1)[-1].startswith("234")
    except OSError:
        return False


#: Cómo pasar a TLS cada protocolo que cifra a mitad de sesión.
_STARTTLS_UPGRADES: Dict[str, Callable] = {"ftp": _upgrade_ftp}


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
                desde el primer byte. Hoy sólo ``"ftp"`` (``AUTH TLS``, RFC
                4217). Por defecto ``None``: TLS desde el primer byte.

        Returns:
            A :class:`TlsInfo`, or ``None`` on any connection/handshake failure
            — incluido un servidor que rechaza el ``AUTH TLS``.
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
                ningún conjunto de la familia).
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
        except ssl.SSLError:
            return ""
        except OSError as err:
            logger.debug("TLS handshake failed for %s:%s: %s", host, port, err)
            return None
        return cipher[0] if cipher else ""

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
        return TlsInfo(
            protocol=protocol,
            cipher=cipher,
            subject_cn=_common_name(cert.subject),
            issuer_cn=_common_name(cert.issuer),
            self_signed=cert.issuer == cert.subject,
            expired=days_until_expiry < 0,
            days_until_expiry=days_until_expiry,
            names=_certificate_names(cert),
        )
