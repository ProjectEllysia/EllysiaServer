"""Higiene del DNS de un dominio: lo que publica sobre su correo y sus certificados.

Seis comprobaciones sobre el DNS público de un dominio, ninguna sobre un
servidor del cliente: SPF (quién puede enviar correo en su nombre), DMARC (qué
hacer con el correo que falla esa comprobación), DKIM (si firma sus mensajes),
MTA-STS (si exige cifrado a quien le entrega correo), CAA (qué autoridades
pueden emitirle certificados) y DNSSEC (si su zona está protegida contra la
falsificación).

Como el resto del paquete, no toca la red: el DNS llega por la búsqueda
inyectada :data:`~.osint.RecordLookup`. Una respuesta que no es definitiva
(tiempo agotado, servidor que falla) nunca se convierte en hallazgo: la
comprobación queda ``not_evaluated``.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_der_public_key

from .osint import OSINT_EVIDENCE_KIND, OSINT_FEED_VERSION, RecordLookup, build_provenance


#: Calidad de detección de un hallazgo de higiene DNS. La respuesta del DNS
#: público sí es observación propia y del momento; no llega a la de un check
#: activo confirmado porque un resolutor intermedio puede servir una copia
#: vieja durante el TTL del registro.
QOD_DNS_RECORD = 70

#: Categoría de los hallazgos de higiene del DNS del dominio.
DNS_HYGIENE_CATEGORY = "dns_hygiene"

# Un selector DKIM: una o más etiquetas DNS. Se valida antes de componer el
# nombre ``<selector>._domainkey.<dominio>`` que se consulta.
_DKIM_SELECTOR_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,62})$")

#: Mecanismos de SPF que cuestan una consulta DNS al receptor. El RFC 7208
#: (sección 4.6.4) limita a diez las que puede provocar una evaluación: una
#: más y el resultado es ``permerror``, es decir, un SPF que no protege.
_SPF_LOOKUP_MECHANISMS = ("include:", "a:", "a/", "mx:", "mx/", "ptr:", "exists:", "redirect=")
#: Los mismos mecanismos en su forma desnuda, sin dominio ni máscara.
_SPF_BARE_LOOKUP_MECHANISMS = ("a", "mx", "ptr")
_SPF_MAX_LOOKUPS = 10

#: Tamaño mínimo razonable de una clave RSA de DKIM. El RFC 8301 exige a los
#: firmantes al menos 1024 bits y recomienda 2048; por debajo de 2048 la clave
#: es factorizable con recursos al alcance de un atacante con motivación.
_DKIM_MIN_RSA_BITS = 2048

#: El resultado de una comprobación: su veredicto y los hallazgos que dispara.
CheckOutcome = Tuple["DnsCheckStatus", List[dict]]


class DnsCheckStatus(str, Enum):
    """Resultado de una comprobación de higiene DNS.

    Attributes:
        PASSED: El dominio publica lo que la regla espera.
        FAILED: La regla disparó al menos un hallazgo.
        NOT_EVALUATED: El DNS no dio una respuesta definitiva (tiempo agotado,
            servidor que falla); la regla no se pronuncia antes que acusar sin
            pruebas.
        NOT_APPLICABLE: La regla no tiene sentido para este dominio (MTA-STS
            en un dominio sin servidores de correo, DNSSEC en un nombre que no
            es el vértice de una zona, DKIM sin selectores que consultar).
    """
    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"
    NOT_APPLICABLE = "not_applicable"


def is_valid_dkim_selector(selector: str) -> bool:
    """Si un texto sirve como selector DKIM.

    Args:
        selector: El selector que pidió el usuario (``"google"``, ``"s1"``…).

    Returns:
        bool: ``True`` si está formado por caracteres válidos de etiqueta DNS.
    """
    return bool(_DKIM_SELECTOR_RE.match(selector or ""))


@dataclass(frozen=True)
class DnsCheckResult:
    """El veredicto de una comprobación de higiene DNS.

    Attributes:
        check: La comprobación (``"spf"``, ``"dmarc"``, ``"dkim"``,
            ``"mta_sts"``, ``"caa"`` o ``"dnssec"``).
        status: Su resultado.
    """
    check: str
    status: DnsCheckStatus

    def to_json(self) -> dict:
        """Serializa el veredicto en camelCase.

        Returns:
            dict: ``check`` y ``status``.
        """
        return {"check": self.check, "status": self.status.value}


def _dns_finding(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        domain: str, check_id: str, severity: str, title: str, queried_name: str,
        record_type: str, values: Sequence[str], now: datetime) -> dict:
    """Compone un hallazgo ``dns_hygiene``.

    La respuesta del DNS la observamos nosotros y en este momento: la
    procedencia dice ``dns`` con antigüedad cero, y el hallazgo nace
    confirmado. ``service`` lleva el dominio para que dos dominios distintos no
    compartan clave de deduplicación.

    Args:
        domain: El dominio revisado.
        check_id: El identificador de la regla (``lybra:dns-…@1``).
        severity: La severidad declarada: ``"INFO"``, ``"LOW"``,
            ``"MEDIUM"`` o ``"HIGH"``.
        title: El título para una persona.
        queried_name: El nombre que se consultó.
        record_type: El tipo de registro consultado.
        values: Los valores que devolvió el DNS (vacío si ninguno).
        now: El instante de la consulta.

    Returns:
        dict: El hallazgo con las columnas de ``Finding`` más ``_provenance``
            y ``_evidence``.
    """
    provenance = build_provenance(
        "dns", "DNS público", now, now, now,
        record={"name": queried_name, "type": record_type, "values": list(values)},
    )
    return {
        "title": title,
        "category": DNS_HYGIENE_CATEGORY,
        "port": None,
        "service": domain,
        "protocol": None,
        "cpe": None,
        "source": "lybra",
        "check_id": check_id,
        "feed_version": OSINT_FEED_VERSION,
        "qod": QOD_DNS_RECORD,
        "confirmed": True,
        "cpe_resolved": None,
        "severity": severity,
        "state": "open",
        "_provenance": provenance,
        "_evidence": {"kind": OSINT_EVIDENCE_KIND, "payload": provenance},
    }


def _is_spf_record(value: str) -> bool:
    """Si un TXT es un registro SPF (empieza por la versión ``v=spf1``).

    Args:
        value: El texto de un registro TXT.

    Returns:
        bool: ``True`` si es un registro SPF.
    """
    lowered = value.strip().lower()
    return lowered == "v=spf1" or lowered.startswith("v=spf1 ")


def evaluate_spf_record(record: str) -> List[Tuple[str, str, str]]:
    """Evalúa la política de un registro SPF ya localizado.

    Args:
        record: El texto del registro (``"v=spf1 include:_spf.google.com ~all"``).

    Returns:
        List[Tuple[str, str, str]]: Un problema por tupla ``(sufijo del
            check, severidad, descripción)``. Lista vacía si la política es
            correcta. Los sufijos son ``"permissive"`` (``+all``: cualquiera
            puede enviar en nombre del dominio; o ``?all``: el receptor no
            recibe instrucción alguna), ``"no-all"`` (sin cláusula final ni
            ``redirect``) y ``"lookups"`` (más de diez mecanismos con consulta
            DNS, que el receptor evalúa como error permanente).
    """
    terms = [term.lower() for term in record.split()[1:]]
    problems: List[Tuple[str, str, str]] = []
    all_terms = [term for term in terms if term.lstrip("+-~?") == "all"]
    if any(term in ("all", "+all") for term in all_terms):
        problems.append(("permissive", "HIGH",
                         "termina en «+all»: autoriza a cualquier servidor del mundo a "
                         "enviar correo en nombre del dominio"))
    elif "?all" in all_terms:
        problems.append(("permissive", "MEDIUM",
                         "termina en «?all» (neutral): no dice al receptor qué hacer con el correo "
                         "que no sale de los servidores autorizados"))
    elif not all_terms and not any(term.startswith("redirect=") for term in terms):
        problems.append(("no-all", "LOW",
                         "no termina en una cláusula «all»: el correo de servidores no autorizados "
                         "queda sin política"))
    lookups = sum(1 for term in terms
                  if term.lstrip("+-~?") in _SPF_BARE_LOOKUP_MECHANISMS
                  or term.lstrip("+-~?").startswith(_SPF_LOOKUP_MECHANISMS))
    if lookups > _SPF_MAX_LOOKUPS:
        problems.append(("lookups", "MEDIUM",
                         f"necesita {lookups} consultas DNS y el máximo que admite un receptor es "
                         f"{_SPF_MAX_LOOKUPS}: la comprobación falla y el registro deja de "
                         "proteger"))
    return problems


def _check_spf(domain: str, lookup_records: RecordLookup, now: datetime) -> CheckOutcome:
    """La comprobación SPF: quién puede enviar correo en nombre del dominio.

    Args:
        domain: El dominio, ya normalizado.
        lookup_records: La búsqueda DNS inyectada.
        now: El instante de referencia, naive en UTC.

    Returns:
        CheckOutcome: El veredicto de la comprobación y sus hallazgos
            ``dns_hygiene`` (lista vacía si no disparó ninguno).
    """
    values = lookup_records(domain, "TXT")
    if values is None:
        return DnsCheckStatus.NOT_EVALUATED, []
    records = [value for value in values if _is_spf_record(value)]
    if not records:
        return DnsCheckStatus.FAILED, [_dns_finding(
            domain, "lybra:dns-spf-missing@1", "MEDIUM",
            f"{domain} no publica registro SPF: cualquiera puede enviar correo haciéndose "
            "pasar por el dominio",
            domain, "TXT", values, now)]
    if len(records) > 1:
        return DnsCheckStatus.FAILED, [_dns_finding(
            domain, "lybra:dns-spf-multiple@1", "MEDIUM",
            f"{domain} publica {len(records)} registros SPF: el receptor lo trata como error y "
            "no aplica ninguno", domain, "TXT", records, now)]
    findings = [
        _dns_finding(domain, f"lybra:dns-spf-{suffix}@1", severity,
                     f"El registro SPF de {domain} {description}", domain, "TXT", records, now)
        for suffix, severity, description in evaluate_spf_record(records[0])
    ]
    return (DnsCheckStatus.FAILED if findings else DnsCheckStatus.PASSED), findings


def parse_dmarc_tags(record: str) -> Dict[str, str]:
    """Lee las etiquetas ``clave=valor`` de un registro DMARC.

    Args:
        record: El texto del registro (``"v=DMARC1; p=reject; rua=mailto:…"``).

    Returns:
        Dict[str, str]: Las etiquetas en minúsculas, con su valor sin espacios
            alrededor. Una etiqueta repetida conserva la primera aparición.
    """
    tags: Dict[str, str] = {}
    for part in record.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        tags.setdefault(key.strip().lower(), value.strip())
    return tags


def _check_dmarc(domain: str, lookup_records: RecordLookup, now: datetime) -> CheckOutcome:
    """La comprobación DMARC: qué hacer con el correo que suplanta al dominio.

    Args:
        domain: El dominio, ya normalizado.
        lookup_records: La búsqueda DNS inyectada.
        now: El instante de referencia, naive en UTC.

    Returns:
        CheckOutcome: El veredicto de la comprobación y sus hallazgos
            ``dns_hygiene`` (lista vacía si no disparó ninguno).
    """
    name = f"_dmarc.{domain}"
    values = lookup_records(name, "TXT")
    if values is None:
        return DnsCheckStatus.NOT_EVALUATED, []
    records = [value for value in values if value.strip().lower().startswith("v=dmarc1")]
    if not records:
        return DnsCheckStatus.FAILED, [_dns_finding(
            domain, "lybra:dns-dmarc-missing@1", "MEDIUM",
            f"{domain} no publica política DMARC: los receptores no saben qué hacer con el correo "
            "que suplanta al dominio", name, "TXT", values, now)]
    tags = parse_dmarc_tags(records[0])
    policy = tags.get("p", "").lower()
    if len(records) > 1 or policy not in ("none", "quarantine", "reject"):
        return DnsCheckStatus.FAILED, [_dns_finding(
            domain, "lybra:dns-dmarc-invalid@1", "MEDIUM",
            f"La política DMARC de {domain} no es válida (varios registros o sin una política «p» "
            "reconocible): los receptores la ignoran", name, "TXT", records, now)]
    findings: List[dict] = []
    if policy == "none":
        findings.append(_dns_finding(
            domain, "lybra:dns-dmarc-monitoring@1", "LOW",
            f"La política DMARC de {domain} es «p=none»: sólo observa, no frena el correo que "
            "suplanta al dominio", name, "TXT", records, now))
    percentage = tags.get("pct", "100")
    if policy != "none" and percentage.isdigit() and int(percentage) < 100:
        findings.append(_dns_finding(
            domain, "lybra:dns-dmarc-partial@1", "LOW",
            f"La política DMARC de {domain} sólo se aplica al {int(percentage)} % del correo "
            "(«pct»): el resto pasa sin ella", name, "TXT", records, now))
    return (DnsCheckStatus.FAILED if findings else DnsCheckStatus.PASSED), findings


def _rsa_key_bits(encoded_key: str) -> Optional[int]:
    """El tamaño en bits de una clave pública RSA en base64, o ``None`` si no se lee.

    Args:
        encoded_key: El valor de la etiqueta ``p=`` de un registro DKIM.

    Returns:
        Optional[int]: Los bits de la clave; ``None`` si no se puede leer o
            no es RSA.
    """
    try:
        key = load_der_public_key(base64.b64decode(encoded_key, validate=False))
    except Exception:  # pylint: disable=broad-exception-caught
        # Un base64 roto (``binascii.Error``) o un DER mal formado (las clases
        # propias de ``cryptography``) significan lo mismo aquí: la clave no
        # se puede leer.
        return None
    return key.key_size if isinstance(key, rsa.RSAPublicKey) else None


def _check_dkim(domain: str, selectors: Sequence[str], lookup_records: RecordLookup,
                now: datetime) -> CheckOutcome:
    """La comprobación DKIM de los selectores que indicó el usuario.

    DKIM no tiene un nombre fijo que consultar: la clave vive en
    ``<selector>._domainkey.<dominio>`` y el selector lo elige quien firma.
    Adivinarlo probando nombres sería fuerza bruta contra el DNS del cliente,
    así que sólo se comprueban los selectores que se piden; sin selectores, la
    comprobación no aplica.

    Args:
        domain: El dominio, ya normalizado.
        selectors: Los selectores que pidió el usuario; vacío si ninguno.
        lookup_records: La búsqueda DNS inyectada.
        now: El instante de referencia, naive en UTC.

    Returns:
        CheckOutcome: El veredicto de la comprobación y sus hallazgos
            ``dns_hygiene`` (lista vacía si no disparó ninguno).
    """
    if not selectors:
        return DnsCheckStatus.NOT_APPLICABLE, []
    findings: List[dict] = []
    has_definitive_answer = False
    for selector in selectors:
        name = f"{selector}._domainkey.{domain}"
        values = lookup_records(name, "TXT")
        if values is None:
            continue
        has_definitive_answer = True
        records = [value for value in values if "p=" in value.replace(" ", "")]
        if not records:
            findings.append(_dns_finding(
                domain, "lybra:dns-dkim-missing@1", "LOW",
                f"El selector DKIM «{selector}» de {domain} no tiene clave publicada: el correo "
                "firmado con él no se puede verificar", name, "TXT", values, now))
            continue
        tags = parse_dmarc_tags(records[0])
        public_key = tags.get("p", "").replace(" ", "")
        if not public_key:
            findings.append(_dns_finding(
                domain, "lybra:dns-dkim-revoked@1", "INFO",
                f"El selector DKIM «{selector}» de {domain} está revocado (clave vacía)",
                name, "TXT", records, now))
            continue
        if tags.get("k", "rsa").lower() != "rsa":
            continue
        key_bits = _rsa_key_bits(public_key)
        if key_bits is None:
            findings.append(_dns_finding(
                domain, "lybra:dns-dkim-invalid@1", "LOW",
                f"La clave DKIM del selector «{selector}» de {domain} no se puede leer: las firmas "
                "no se podrán verificar", name, "TXT", records, now))
        elif key_bits < _DKIM_MIN_RSA_BITS:
            findings.append(_dns_finding(
                domain, "lybra:dns-dkim-weak-key@1", "MEDIUM",
                f"La clave DKIM del selector «{selector}» de {domain} es RSA de {key_bits} bits; "
                f"se recomiendan al menos {_DKIM_MIN_RSA_BITS}", name, "TXT", records, now))
    if not has_definitive_answer:
        return DnsCheckStatus.NOT_EVALUATED, []
    return (DnsCheckStatus.FAILED if findings else DnsCheckStatus.PASSED), findings


def _check_mta_sts(domain: str, lookup_records: RecordLookup, now: datetime) -> CheckOutcome:
    """La comprobación MTA-STS: si el dominio exige cifrado a quien le entrega correo.

    Sólo mira el registro ``_mta-sts`` del DNS. La política completa vive en
    ``https://mta-sts.<dominio>/.well-known/mta-sts.txt``, un servidor web del
    cliente: descargarla sería tocar el objetivo, y esta comprobación es
    pasiva.

    Args:
        domain: El dominio, ya normalizado.
        lookup_records: La búsqueda DNS inyectada.
        now: El instante de referencia, naive en UTC.

    Returns:
        CheckOutcome: El veredicto de la comprobación y sus hallazgos
            ``dns_hygiene`` (lista vacía si no disparó ninguno).
    """
    mail_servers = lookup_records(domain, "MX")
    if mail_servers is None:
        return DnsCheckStatus.NOT_EVALUATED, []
    if not mail_servers:
        return DnsCheckStatus.NOT_APPLICABLE, []
    name = f"_mta-sts.{domain}"
    values = lookup_records(name, "TXT")
    if values is None:
        return DnsCheckStatus.NOT_EVALUATED, []
    records = [value for value in values if value.strip().lower().startswith("v=stsv1")]
    if not records:
        return DnsCheckStatus.FAILED, [_dns_finding(
            domain, "lybra:dns-mta-sts-missing@1", "LOW",
            f"{domain} recibe correo pero no publica MTA-STS: otro servidor puede "
            "entregarle correo sin cifrar si alguien interfiere la conexión",
            name, "TXT", values, now)]
    if not parse_dmarc_tags(records[0]).get("id"):
        return DnsCheckStatus.FAILED, [_dns_finding(
            domain, "lybra:dns-mta-sts-invalid@1", "LOW",
            f"El registro MTA-STS de {domain} no lleva identificador de política («id»): los "
            "servidores emisores lo ignoran", name, "TXT", records, now)]
    return DnsCheckStatus.PASSED, []


def _check_caa(domain: str, lookup_records: RecordLookup, now: datetime) -> CheckOutcome:
    """La comprobación CAA: qué autoridades pueden emitir certificados para el dominio.

    Una autoridad busca el CAA subiendo por el árbol (el de
    ``www.example.com`` puede estar en ``example.com``), así que se consulta
    igual, de más concreto a más general, hasta el dominio de dos etiquetas.

    Args:
        domain: El dominio, ya normalizado.
        lookup_records: La búsqueda DNS inyectada.
        now: El instante de referencia, naive en UTC.

    Returns:
        CheckOutcome: El veredicto de la comprobación y sus hallazgos
            ``dns_hygiene`` (lista vacía si no disparó ninguno).
    """
    labels = domain.split(".")
    for start in range(0, len(labels) - 1):
        name = ".".join(labels[start:])
        values = lookup_records(name, "CAA")
        if values is None:
            return DnsCheckStatus.NOT_EVALUATED, []
        if values:
            return DnsCheckStatus.PASSED, []
    return DnsCheckStatus.FAILED, [_dns_finding(
        domain, "lybra:dns-caa-missing@1", "LOW",
        f"{domain} no publica registros CAA: cualquier autoridad de certificación puede emitir "
        "certificados para el dominio", domain, "CAA", [], now)]


def _check_dnssec(domain: str, lookup_records: RecordLookup, now: datetime) -> CheckOutcome:
    """La comprobación DNSSEC: si la zona está firmada y delegada con firma.

    Sólo aplica al vértice de una zona (un nombre con registro SOA propio): un
    subdominio sin delegación hereda la firma de su zona y no tiene registro
    DS que buscar. La prueba de que la zona está firmada es que su zona padre
    publique un registro DS para ella.

    Args:
        domain: El dominio, ya normalizado.
        lookup_records: La búsqueda DNS inyectada.
        now: El instante de referencia, naive en UTC.

    Returns:
        CheckOutcome: El veredicto de la comprobación y sus hallazgos
            ``dns_hygiene`` (lista vacía si no disparó ninguno).
    """
    start_of_authority = lookup_records(domain, "SOA")
    if start_of_authority is None:
        return DnsCheckStatus.NOT_EVALUATED, []
    if not start_of_authority:
        return DnsCheckStatus.NOT_APPLICABLE, []
    delegation_signers = lookup_records(domain, "DS")
    if delegation_signers is None:
        return DnsCheckStatus.NOT_EVALUATED, []
    if delegation_signers:
        return DnsCheckStatus.PASSED, []
    return DnsCheckStatus.FAILED, [_dns_finding(
        domain, "lybra:dns-dnssec-missing@1", "LOW",
        f"La zona {domain} no está firmada con DNSSEC: un atacante en el camino puede falsificar "
        "sus respuestas DNS", domain, "DS", [], now)]


def assess_dns_hygiene(domain: str, lookup_records: RecordLookup, now: datetime,
                       dkim_selectors: Sequence[str] = (),
                       ) -> Tuple[List[dict], List[DnsCheckResult]]:
    """Revisa lo que un dominio publica en el DNS sobre su correo y sus certificados.

    Seis comprobaciones: SPF (quién puede enviar correo en su nombre), DMARC
    (qué hacer con el que falla esa comprobación), DKIM (si firma sus
    mensajes, sólo con los selectores indicados), MTA-STS (si exige cifrado a
    quien le entrega correo), CAA (qué autoridades pueden emitirle
    certificados) y DNSSEC (si su zona está protegida contra la
    falsificación). Todas leen el DNS público; ninguna toca un servidor del
    cliente.

    Args:
        domain: El dominio, ya normalizado.
        lookup_records: La búsqueda DNS inyectada (ver :data:`RecordLookup`).
        now: El instante de referencia, naive en UTC.
        dkim_selectors: Los selectores DKIM que se deben comprobar. Por
            defecto ninguno: DKIM queda ``not_applicable``.

    Returns:
        Tuple[List[dict], List[DnsCheckResult]]: Los hallazgos ``dns_hygiene``
            y el veredicto de cada comprobación, en el orden de arriba.
    """
    checks = (
        ("spf", lambda: _check_spf(domain, lookup_records, now)),
        ("dmarc", lambda: _check_dmarc(domain, lookup_records, now)),
        ("dkim", lambda: _check_dkim(domain, dkim_selectors, lookup_records, now)),
        ("mta_sts", lambda: _check_mta_sts(domain, lookup_records, now)),
        ("caa", lambda: _check_caa(domain, lookup_records, now)),
        ("dnssec", lambda: _check_dnssec(domain, lookup_records, now)),
    )
    findings: List[dict] = []
    results: List[DnsCheckResult] = []
    for check_name, run_check in checks:
        status, check_findings = run_check()
        findings.extend(check_findings)
        results.append(DnsCheckResult(check=check_name, status=status))
    return findings, results
