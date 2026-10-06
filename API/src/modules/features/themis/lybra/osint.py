"""Inteligencia pasiva sobre un dominio: lo que otros ya saben de él.

Todo lo demás del motor aprende del objetivo tocándolo. Este módulo no le manda
un solo paquete: lee lo que ya es público —los registros de Certificate
Transparency y lo que Shodan, Censys o SecurityTrails vieron en su día— y lo
convierte en hallazgos. Por eso es lo único que se puede hacer antes de tener
autorización sobre un objetivo, y por eso el registro de objetivos autorizados
no aplica aquí. Lo que el propio dominio publica en su DNS lo revisa su
módulo hermano, ``dns_hygiene.py``.

Dos reglas guían cada hallazgo que sale de aquí:

* **Procedencia explícita.** Un dato de Shodan no es una observación nuestra:
  puede tener meses. Cada hallazgo dice de qué fuente sale, cuándo vio esa
  fuente el dato (``observedAt``) y cuándo lo recogimos (``retrievedAt``), y su
  título lo cuenta en lenguaje llano. Confundir «lo vimos» con «alguien lo vio»
  sería justo la imprecisión que el resto del motor evita.
* **Calidad de detección baja** (:data:`QOD_THIRD_PARTY`) para todo dato de
  terceros, por debajo incluso de «el puerto está abierto», que sí es
  observación propia. Lo que sí observamos nosotros —la respuesta del DNS
  público, en ``dns_hygiene.py``— lleva ``QOD_DNS_RECORD``.

Como el resto del paquete, este módulo **no toca el ORM ni la red**: las
fuentes llegan por un *fetcher* inyectado (``(fuente, consulta) ->
FetchedDocument``) y el DNS por una búsqueda inyectada (``(nombre, tipo) ->
lista de valores | None``), el mismo patrón que el ``cve_lookup`` de
:class:`~.engine.LybraEngine`. La caché, las claves de API y las peticiones de
verdad viven en ``themis/managers/lybra/osint.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.modules.shared import is_private_target, isoformat_utc

from .kb import normalize_cpe_to_23, parse_cpe23


#: Calidad de detección de todo dato que sale de una fuente de terceros. Por
#: debajo de ``QOD_OPEN_PORT`` (30) a propósito: «el puerto está abierto» lo
#: comprobamos nosotros en este escaneo; «Shodan vio el puerto abierto» es la
#: palabra de otro, con la fecha que otro le puso.
QOD_THIRD_PARTY = 25

#: Categoría de los hallazgos que salen de fuentes de terceros.
PASSIVE_EXPOSURE_CATEGORY = "passive_exposure"

#: Marca de reproducibilidad de los hallazgos de este módulo: dice con qué
#: versión de las reglas se generaron, igual que ``feed_version`` en los checks.
OSINT_FEED_VERSION = "lybra-osint-1"

#: Clase de evidencia con la que viaja la procedencia de un hallazgo pasivo
#: cuando se persiste como ``FindingEvidence``.
OSINT_EVIDENCE_KIND = "osint_record"

# Un nombre de dominio en su forma ASCII: etiquetas de 1 a 63 caracteres, sin
# guion al principio ni al final, y un último nivel alfabético o IDNA. Excluye
# las direcciones IP a propósito: su último "nivel" es numérico.
_DOMAIN_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TOP_LEVEL_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_MAX_DOMAIN_LENGTH = 253


class OsintSource(str, Enum):
    """Las fuentes de terceros que consulta la inteligencia pasiva.

    Hereda de ``str`` para compararse y serializarse como su valor.

    Attributes:
        CERTIFICATE_TRANSPARENCY: Los registros públicos de Certificate
            Transparency, a través de crt.sh. Gratis y sin clave: es la fuente
            que más valor da por euro y la única activa por defecto.
        SHODAN: Lo que el buscador Shodan vio en una dirección (puertos,
            productos, versiones). De pago y con cuota.
        CENSYS: Lo mismo, según Censys. De pago y con cuota.
        SECURITYTRAILS: El histórico DNS de SecurityTrails (subdominios
            conocidos). De pago y con cuota.
    """
    CERTIFICATE_TRANSPARENCY = "crtsh"
    SHODAN = "shodan"
    CENSYS = "censys"
    SECURITYTRAILS = "securitytrails"


#: Nombre de cada fuente tal como se cuenta en el título de un hallazgo.
SOURCE_LABELS: Dict[OsintSource, str] = {
    OsintSource.CERTIFICATE_TRANSPARENCY: "Certificate Transparency (crt.sh)",
    OsintSource.SHODAN: "Shodan",
    OsintSource.CENSYS: "Censys",
    OsintSource.SECURITYTRAILS: "SecurityTrails",
}

#: Fuentes que exigen clave de API; las demás funcionan sin ella.
CREDENTIALED_SOURCES = frozenset({
    OsintSource.SHODAN, OsintSource.CENSYS, OsintSource.SECURITYTRAILS,
})

#: Fuentes que describen una dirección IP (qué servicios expone), frente a las
#: que describen un dominio (qué nombres existen).
HOST_SOURCES = (OsintSource.SHODAN, OsintSource.CENSYS)


class SourceOutcome(str, Enum):
    """Qué pasó con una fuente en una consulta pasiva.

    Attributes:
        OK: La fuente respondió a todas las consultas.
        PARTIAL: Respondió a unas y falló en otras.
        DISABLED: Está apagada en la configuración; no se le preguntó nada.
        SKIPPED: Está encendida pero falta su clave de API; se omite sin
            romper el resto.
        FAILED: Se le preguntó y no respondió (red, cuota, error del servidor).
    """
    OK = "ok"
    PARTIAL = "partial"
    DISABLED = "disabled"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceSetting:
    """Si una fuente se puede consultar en este despliegue.

    Attributes:
        is_enabled: Si el operador la encendió en la configuración.
        has_credentials: Si su clave de API está en el entorno. Irrelevante
            para las fuentes que no la necesitan (crt.sh).
    """
    is_enabled: bool
    has_credentials: bool = False


@dataclass(frozen=True)
class FetchedDocument:
    """La respuesta de una fuente a una consulta, con su fecha.

    Attributes:
        payload: El JSON ya decodificado, o ``None`` cuando la fuente respondió
            que no sabe nada de lo consultado (el 404 de Shodan para una IP
            que nunca vio).
        retrieved_at: Cuándo se descargó, en UTC sin zona. Si viene de la
            caché, es la fecha de la descarga original, no la de ahora: es la
            que dice cuán viejo es el dato.
        was_cached: Si la respuesta salió de la caché en vez de la red. Por
            defecto ``False``.
    """
    payload: Any
    retrieved_at: datetime
    was_cached: bool = False


#: El fetcher inyectado: ``(fuente, consulta) -> FetchedDocument``. La consulta
#: es el dominio para crt.sh y SecurityTrails y la dirección IP para Shodan y
#: Censys. Cualquier excepción cuenta como fuente caída.
SourceFetcher = Callable[[OsintSource, str], FetchedDocument]

#: La búsqueda DNS inyectada: ``(nombre, tipo) -> valores``. Devuelve la lista
#: de valores en texto (un TXT ya con sus trozos unidos), una lista vacía si el
#: nombre no existe o no tiene registros de ese tipo, y ``None`` si el DNS no
#: dio una respuesta definitiva.
RecordLookup = Callable[[str, str], Optional[List[str]]]


@dataclass(frozen=True)
class SourceStatus:
    """El resultado de una fuente en una consulta pasiva, para el informe.

    Attributes:
        source: La fuente.
        outcome: Qué pasó con ella.
        retrieved_at: La fecha del dato más viejo que se usó de ella, o
            ``None`` si no se usó ninguno. Por defecto ``None``.
        was_cached: Si alguna de sus respuestas salió de la caché. Por
            defecto ``False``.
        detail: Motivo corto y estable cuando no fue ``ok``
            (``"missing_api_key"``, el nombre del error…). Nunca el texto del
            error: podría llevar la clave de API dentro de la URL. Por defecto
            ``None``.
    """
    source: OsintSource
    outcome: SourceOutcome
    retrieved_at: Optional[datetime] = None
    was_cached: bool = False
    detail: Optional[str] = None

    def to_json(self) -> dict:
        """Serializa el estado de la fuente en camelCase para la API y el JSONB.

        Returns:
            dict: ``source``, ``label``, ``outcome``, ``retrievedAt`` (ISO 8601
                con ``Z`` o ``None``), ``cached`` y ``detail``.
        """
        return {
            "source": self.source.value,
            "label": SOURCE_LABELS[self.source],
            "outcome": self.outcome.value,
            "retrievedAt": isoformat_utc(self.retrieved_at),
            "cached": self.was_cached,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CertificateRecord:
    """Un certificado visto en Certificate Transparency.

    Attributes:
        certificate_id: El identificador del certificado en crt.sh, o ``None``.
        names: Los nombres que cubre, en minúsculas y sin el ``*.`` de un
            comodín.
        issuer: El emisor, tal como lo da crt.sh.
        not_before: Desde cuándo es válido: la mejor aproximación a cuándo se
            emitió. ``None`` si la fuente no lo dio.
    """
    certificate_id: Optional[int]
    names: Tuple[str, ...]
    issuer: str
    not_before: Optional[datetime]


@dataclass
class SubdomainRecord:
    """Un subdominio del dominio consultado, con quién lo conoce y desde cuándo.

    Es la pieza que otros modos del escaneo pasivo reutilizan (buscar
    almacenamiento en la nube o subdominios secuestrables parte de esta lista).

    Attributes:
        name: El nombre completo, en minúsculas.
        sources: Las fuentes que lo conocen.
        first_seen_at: El dato más antiguo que lo nombra, o ``None`` si
            ninguna fuente fecha sus datos (SecurityTrails no lo hace).
        last_seen_at: El dato más reciente que lo nombra, o ``None``.
    """
    name: str
    sources: set = field(default_factory=set)
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    def observe(self, source: OsintSource, seen_at: Optional[datetime]) -> None:
        """Anota que una fuente conoce el nombre, ampliando su rango de fechas.

        Args:
            source: La fuente que lo nombra.
            seen_at: La fecha de ese dato, o ``None`` si la fuente no fecha.
        """
        self.sources.add(source)
        if seen_at is None:
            return
        if self.first_seen_at is None or seen_at < self.first_seen_at:
            self.first_seen_at = seen_at
        if self.last_seen_at is None or seen_at > self.last_seen_at:
            self.last_seen_at = seen_at

    def to_json(self) -> dict:
        """Serializa el subdominio en camelCase para la API y el JSONB.

        Returns:
            dict: ``name``, ``sources`` (valores ordenados), ``firstSeenAt`` y
                ``lastSeenAt`` (ISO 8601 con ``Z`` o ``None``).
        """
        return {
            "name": self.name,
            "sources": sorted(source.value for source in self.sources),
            "firstSeenAt": isoformat_utc(self.first_seen_at),
            "lastSeenAt": isoformat_utc(self.last_seen_at),
        }


@dataclass(frozen=True)
class ServiceObservation:  # pylint: disable=too-many-instance-attributes
    """Un servicio que una fuente de terceros vio abierto en una dirección.

    Attributes:
        source: Quién lo vio (Shodan o Censys).
        address: La dirección IP.
        port: El puerto.
        protocol: ``"tcp"`` o ``"udp"``.
        product: El producto que la fuente identificó; vacío si ninguno.
        version: Su versión; vacía si ninguna.
        cpe: El CPE 2.3 que la fuente propone, o ``None``. Es una sugerencia
            ajena, nunca una identificación nuestra.
        observed_at: Cuándo lo vio la fuente, o ``None`` si no lo dice.
        retrieved_at: Cuándo recogimos ese dato de la fuente.
    """
    source: OsintSource
    address: str
    port: int
    protocol: str
    product: str
    version: str
    cpe: Optional[str]
    observed_at: Optional[datetime]
    retrieved_at: datetime


@dataclass
class PassiveReport:
    """Todo lo que una consulta pasiva sacó de las fuentes de terceros.

    Attributes:
        subdomains: Los subdominios conocidos, ordenados por nombre.
        observations: Los servicios que Shodan o Censys vieron en las
            direcciones del dominio.
        findings: Los hallazgos ``passive_exposure`` listos para el motor.
        source_statuses: Qué pasó con cada fuente, en el orden de
            :class:`OsintSource`.
    """
    subdomains: List[SubdomainRecord] = field(default_factory=list)
    observations: List[ServiceObservation] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)
    source_statuses: List[SourceStatus] = field(default_factory=list)


# =========================================================================
# NOMBRES
# =========================================================================

def normalize_domain(raw: str) -> Optional[str]:  # pylint: disable=too-many-return-statements
    """Devuelve un nombre de dominio en su forma canónica, o ``None`` si no lo es.

    Acepta mayúsculas, un punto final y nombres internacionalizados (que pasa a
    su forma IDNA). Rechaza direcciones IP, nombres de una sola etiqueta y
    cualquier cosa con esquema, ruta o puerto: la consulta pasiva es sobre un
    dominio, no sobre una URL.

    Args:
        raw: El texto que escribió el usuario.

    Returns:
        Optional[str]: El dominio en minúsculas, ASCII y sin punto final, o
            ``None`` si el texto no es un nombre de dominio válido.
    """
    candidate = (raw or "").strip().rstrip(".")
    if not candidate:
        return None
    try:
        candidate = candidate.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return None
    if len(candidate) > _MAX_DOMAIN_LENGTH:
        return None
    labels = candidate.split(".")
    if len(labels) < 2:
        return None
    if not all(_DOMAIN_LABEL_RE.match(label) for label in labels):
        return None
    if not _TOP_LEVEL_RE.match(labels[-1]):
        return None
    return candidate


def _belongs_to(name: str, domain: str) -> bool:
    """Si ``name`` es el propio dominio o uno de sus subdominios.

    Args:
        name: El nombre que se comprueba, normalizado.
        domain: El dominio de referencia, normalizado.

    Returns:
        bool: ``True`` si ``name`` es ``domain`` o termina en ``.domain``.
    """
    return name == domain or name.endswith("." + domain)


def _clean_certificate_name(raw: str) -> Optional[str]:
    """Pasa un nombre de un certificado a nombre de host, o ``None`` si no lo es.

    Quita el comodín (``*.dev.example.com`` delata que existe
    ``dev.example.com``) y descarta los correos que algunos certificados
    llevan en su lista de nombres.

    Args:
        raw: Un nombre tal como aparece en el certificado.

    Returns:
        Optional[str]: El nombre normalizado, o ``None`` si no es un nombre
            de host (un correo, texto con espacios, un nombre inválido).
    """
    name = (raw or "").strip().lower().rstrip(".")
    if not name or "@" in name or " " in name:
        return None
    if name.startswith("*."):
        name = name[2:]
    return normalize_domain(name)


# =========================================================================
# FECHAS
# =========================================================================

def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Convierte las fechas de las fuentes a ``datetime`` naive en UTC.

    Cubre las formas que se ven en la práctica: ``2024-01-01T12:00:00``, con
    fracción de segundo, con ``Z`` o con desfase explícito, y una fecha sola.
    Devuelve ``None`` ante cualquier otra cosa en vez de lanzar: una fecha
    ilegible deja el dato sin antigüedad, no tumba la consulta entera.

    Args:
        value: La fecha tal como la da la fuente; cualquier cosa que no sea
            texto se trata como ausente.

    Returns:
        Optional[datetime]: La fecha naive en UTC, o ``None``.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def age_in_days(observed_at: Optional[datetime], now: datetime) -> Optional[int]:
    """Días completos entre la observación de un dato y ahora.

    Args:
        observed_at: Cuándo vio la fuente el dato, o ``None``.
        now: El instante de referencia, naive en UTC.

    Returns:
        Optional[int]: Los días (nunca negativos, aunque la fuente fechara el
            dato en el futuro), o ``None`` si no hay fecha de observación.
    """
    if observed_at is None:
        return None
    return max(0, (now - observed_at).days)


def _describe_age(age_days: Optional[int]) -> str:
    """La antigüedad de un dato en lenguaje llano, para el título del hallazgo.

    Args:
        age_days: Los días de antigüedad, o ``None`` si no hay fecha.

    Returns:
        str: «visto hoy», «visto hace N días» o «sin fecha de observación».
    """
    if age_days is None:
        return "sin fecha de observación"
    if age_days == 0:
        return "visto hoy"
    if age_days == 1:
        return "visto hace 1 día"
    return f"visto hace {age_days} días"


def build_provenance(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        source: str, source_label: str, observed_at: Optional[datetime],
        retrieved_at: Optional[datetime], now: datetime,
        record: Optional[dict] = None) -> dict:
    """Compone la procedencia de un hallazgo: de dónde sale y de cuándo es.

    Args:
        source: El identificador estable de la fuente (``"crtsh"``,
            ``"shodan"``… o ``"dns"`` para una observación propia del DNS).
        source_label: El nombre de la fuente para una persona.
        observed_at: Cuándo vio la fuente el dato, o ``None`` si no lo dice.
        retrieved_at: Cuándo lo recogimos, o ``None``.
        now: El instante de referencia para calcular la antigüedad.
        record: El dato concreto que respalda el hallazgo, ya reducido a lo
            que importa. Por defecto ``None``: se guarda ``{}``.

    Returns:
        dict: ``source``, ``sourceLabel``, ``observedAt``, ``retrievedAt``
            (ISO 8601 con ``Z`` o ``None``), ``ageDays`` (``None`` sin fecha de
            observación) y ``record``.
    """
    return {
        "source": source,
        "sourceLabel": source_label,
        "observedAt": isoformat_utc(observed_at),
        "retrievedAt": isoformat_utc(retrieved_at),
        "ageDays": age_in_days(observed_at, now),
        "record": record or {},
    }


# =========================================================================
# PARSERS DE LAS FUENTES
# =========================================================================

def parse_certificate_transparency(payload: Any) -> List[CertificateRecord]:
    """Lee la respuesta JSON de crt.sh.

    crt.sh devuelve una lista de entradas, una por certificado y registro, con
    los nombres cubiertos en ``name_value`` separados por saltos de línea.

    Args:
        payload: La respuesta ya decodificada; cualquier cosa que no sea una
            lista se trata como vacía.

    Returns:
        List[CertificateRecord]: Un registro por entrada con al menos un
            nombre de host válido, sin repetir identificador.
    """
    if not isinstance(payload, list):
        return []
    records: List[CertificateRecord] = []
    seen_ids: set = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        certificate_id = entry.get("id")
        if certificate_id is not None and certificate_id in seen_ids:
            continue
        raw_names = (str(entry.get("name_value") or "").split("\n")
                     + [str(entry.get("common_name") or "")])
        names = tuple(sorted({name for name in map(_clean_certificate_name, raw_names) if name}))
        if not names:
            continue
        if certificate_id is not None:
            seen_ids.add(certificate_id)
        records.append(CertificateRecord(
            certificate_id=certificate_id if isinstance(certificate_id, int) else None,
            names=names,
            issuer=str(entry.get("issuer_name") or ""),
            not_before=(_parse_timestamp(entry.get("not_before"))
                        or _parse_timestamp(entry.get("entry_timestamp"))),
        ))
    return records


def parse_securitytrails_subdomains(payload: Any, domain: str) -> List[str]:
    """Lee la lista de subdominios de SecurityTrails.

    SecurityTrails devuelve las etiquetas relativas al dominio
    (``{"subdomains": ["www", "api"]}``); aquí se completan con el dominio.

    Args:
        payload: La respuesta ya decodificada, o ``None``.
        domain: El dominio consultado, ya normalizado.

    Returns:
        List[str]: Los nombres completos válidos, ordenados y sin repetir.
    """
    if not isinstance(payload, dict):
        return []
    names = set()
    for label in payload.get("subdomains") or []:
        name = normalize_domain(f"{label}.{domain}") if isinstance(label, str) and label else None
        if name and _belongs_to(name, domain):
            names.add(name)
    return sorted(names)


#: Número de componentes de un CPE 2.3 completo (``cpe:2.3:`` más once
#: atributos). Shodan los da recortados (``cpe:2.3:a:f5:nginx:1.18.0``).
_CPE23_COMPONENT_COUNT = 13


def _first_cpe(candidates: Iterable[Any]) -> Optional[str]:
    """El primer CPE legible de una lista, normalizado a CPE 2.3 con sus trece componentes.

    Args:
        candidates: Los CPE que propone la fuente, en su orden; los que no son
            texto con prefijo ``cpe:`` se ignoran.

    Returns:
        Optional[str]: El CPE completo, o ``None`` si ninguno trae vendor y
            producto legibles.
    """
    for candidate in candidates or []:
        if isinstance(candidate, str) and candidate.startswith("cpe:"):
            components = normalize_cpe_to_23(candidate).split(":")
            normalized = ":".join(components + ["*"] * (_CPE23_COMPONENT_COUNT - len(components)))
            parsed = parse_cpe23(normalized)
            if parsed and parsed.get("vendor") and parsed.get("product"):
                return normalized
    return None


def parse_shodan_host(payload: Any, address: str,
                      retrieved_at: datetime) -> List[ServiceObservation]:
    """Lee la ficha de una dirección en Shodan (``/shodan/host/{ip}``).

    Args:
        payload: La respuesta ya decodificada, o ``None`` si Shodan no sabe nada
            de la dirección.
        address: La dirección consultada.
        retrieved_at: Cuándo se recogió la respuesta.

    Returns:
        List[ServiceObservation]: Un servicio por cada entrada de ``data`` con
            puerto; su fecha es la ``timestamp`` de la entrada o, en su
            defecto, la ``last_update`` de la ficha.
    """
    if not isinstance(payload, dict):
        return []
    host_updated_at = _parse_timestamp(payload.get("last_update"))
    observations: List[ServiceObservation] = []
    for banner in payload.get("data") or []:
        if not isinstance(banner, dict) or not isinstance(banner.get("port"), int):
            continue
        observations.append(ServiceObservation(
            source=OsintSource.SHODAN,
            address=address,
            port=banner["port"],
            protocol=str(banner.get("transport") or "tcp").lower(),
            product=str(banner.get("product") or "").strip(),
            version=str(banner.get("version") or "").strip(),
            cpe=_first_cpe(list(banner.get("cpe23") or []) + list(banner.get("cpe") or [])),
            observed_at=_parse_timestamp(banner.get("timestamp")) or host_updated_at,
            retrieved_at=retrieved_at,
        ))
    return observations


def parse_censys_host(payload: Any, address: str,
                      retrieved_at: datetime) -> List[ServiceObservation]:
    """Lee la ficha de una dirección en Censys (``/v2/hosts/{ip}``).

    Args:
        payload: La respuesta ya decodificada (con su envoltorio ``result``), o
            ``None`` si Censys no sabe nada de la dirección.
        address: La dirección consultada.
        retrieved_at: Cuándo se recogió la respuesta.

    Returns:
        List[ServiceObservation]: Un servicio por cada entrada de
            ``services`` con puerto; producto, versión y CPE salen de su
            primer ``software`` identificado.
    """
    if not isinstance(payload, dict):
        return []
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    host_updated_at = _parse_timestamp(result.get("last_updated_at"))
    observations: List[ServiceObservation] = []
    for service in result.get("services") or []:
        if not isinstance(service, dict) or not isinstance(service.get("port"), int):
            continue
        software = next(
            (item for item in service.get("software") or [] if isinstance(item, dict)), {})
        observations.append(ServiceObservation(
            source=OsintSource.CENSYS,
            address=address,
            port=service["port"],
            protocol=str(service.get("transport_protocol") or "tcp").lower(),
            product=str(software.get("product") or "").strip(),
            version=str(software.get("version") or "").strip(),
            cpe=_first_cpe([software.get("uniform_resource_identifier")]),
            observed_at=_parse_timestamp(service.get("observed_at")) or host_updated_at,
            retrieved_at=retrieved_at,
        ))
    return observations


_HOST_PARSERS: Dict[OsintSource, Callable[[Any, str, datetime], List[ServiceObservation]]] = {
    OsintSource.SHODAN: parse_shodan_host,
    OsintSource.CENSYS: parse_censys_host,
}


# =========================================================================
# CONSULTA DE LAS FUENTES
# =========================================================================

def _usable_status(source: OsintSource,
                   source_settings: Mapping[OsintSource, SourceSetting]) -> Optional[SourceStatus]:
    """El estado de una fuente que no se va a consultar, o ``None`` si sí se consulta.

    Una fuente apagada queda ``disabled``; una encendida que necesita clave y
    no la tiene, ``skipped`` con el motivo ``missing_api_key``. Ninguna de las
    dos rompe la consulta: es la degradación limpia que se pide a las fuentes
    de pago.

    Args:
        source: La fuente.
        source_settings: Qué fuentes están encendidas y con clave; una fuente
            ausente cuenta como apagada.

    Returns:
        Optional[SourceStatus]: ``disabled`` o ``skipped``, o ``None`` si la
            fuente se puede consultar.
    """
    setting = source_settings.get(source) or SourceSetting(is_enabled=False)
    if not setting.is_enabled:
        return SourceStatus(source=source, outcome=SourceOutcome.DISABLED)
    if source in CREDENTIALED_SOURCES and not setting.has_credentials:
        return SourceStatus(source=source, outcome=SourceOutcome.SKIPPED, detail="missing_api_key")
    return None


def _combine_status(source: OsintSource, documents: List[FetchedDocument],
                    failures: List[str]) -> SourceStatus:
    """Resume varias consultas a una fuente en un solo estado.

    Args:
        source: La fuente.
        documents: Las respuestas que sí llegaron.
        failures: El nombre del error de cada consulta que falló.

    Returns:
        SourceStatus: ``ok`` si todo llegó, ``failed`` si nada llegó y
            ``partial`` si hubo de las dos cosas. ``retrieved_at`` es la fecha
            de la respuesta más vieja que se usó.
    """
    if failures and not documents:
        return SourceStatus(source=source, outcome=SourceOutcome.FAILED, detail=failures[0])
    retrieved_at = min((document.retrieved_at for document in documents), default=None)
    return SourceStatus(
        source=source,
        outcome=SourceOutcome.PARTIAL if failures else SourceOutcome.OK,
        retrieved_at=retrieved_at,
        was_cached=any(document.was_cached for document in documents),
        detail=failures[0] if failures else None,
    )


def collect_host_observations(
    addresses: Sequence[str],
    fetch: SourceFetcher,
    source_settings: Mapping[OsintSource, SourceSetting],
) -> Tuple[List[ServiceObservation], List[SourceStatus]]:
    """Pregunta a Shodan y Censys qué servicios vieron en unas direcciones.

    Las direcciones privadas se descartan antes de preguntar: ninguna fuente
    pública sabe nada de ellas, y preguntar por una sólo revelaría la
    topología interna del cliente a un tercero.

    Args:
        addresses: Las direcciones IP que consultar.
        fetch: El fetcher inyectado (ver :data:`SourceFetcher`).
        source_settings: Qué fuentes están encendidas y con clave.

    Returns:
        Tuple[List[ServiceObservation], List[SourceStatus]]: Los servicios
            vistos y el estado de cada fuente de direcciones, en el orden de
            :data:`HOST_SOURCES`.
    """
    public_addresses = [address for address in dict.fromkeys(addresses)
                        if not is_private_target(address)]
    observations: List[ServiceObservation] = []
    statuses: List[SourceStatus] = []
    for source in HOST_SOURCES:
        unusable = _usable_status(source, source_settings)
        if unusable is not None:
            statuses.append(unusable)
            continue
        documents: List[FetchedDocument] = []
        failures: List[str] = []
        for address in public_addresses:
            try:
                document = fetch(source, address)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # Una fuente de terceros puede caer por mil motivos (red,
                # cuota, formato); ninguno debe tumbar el resto del análisis.
                failures.append(type(error).__name__)
                continue
            documents.append(document)
            parse_host = _HOST_PARSERS[source]
            observations.extend(parse_host(document.payload, address, document.retrieved_at))
        statuses.append(_combine_status(source, documents, failures))
    return observations, statuses


def _collect_certificates(domain: str, fetch: SourceFetcher,
                          source_settings: Mapping[OsintSource, SourceSetting],
                          ) -> Tuple[List[CertificateRecord], Optional[FetchedDocument],
                                     SourceStatus]:
    """Consulta Certificate Transparency por los certificados del dominio.

    Args:
        domain: El dominio, ya normalizado.
        fetch: El fetcher inyectado.
        source_settings: Qué fuentes están encendidas y con clave.

    Returns:
        Tuple: Los certificados, la respuesta (para su fecha de descarga, o
            ``None`` si no hubo) y el estado de la fuente.
    """
    source = OsintSource.CERTIFICATE_TRANSPARENCY
    unusable = _usable_status(source, source_settings)
    if unusable is not None:
        return [], None, unusable
    try:
        document = fetch(source, domain)
    except Exception as error:  # pylint: disable=broad-exception-caught
        return [], None, SourceStatus(source=source, outcome=SourceOutcome.FAILED,
                                      detail=type(error).__name__)
    records = parse_certificate_transparency(document.payload)
    return records, document, _combine_status(source, [document], [])


def _collect_securitytrails(domain: str, fetch: SourceFetcher,
                            source_settings: Mapping[OsintSource, SourceSetting],
                            ) -> Tuple[List[str], Optional[FetchedDocument], SourceStatus]:
    """Consulta SecurityTrails por los subdominios del dominio.

    Args:
        domain: El dominio, ya normalizado.
        fetch: El fetcher inyectado.
        source_settings: Qué fuentes están encendidas y con clave.

    Returns:
        Tuple: Los nombres, la respuesta (o ``None``) y el estado de la fuente.
    """
    source = OsintSource.SECURITYTRAILS
    unusable = _usable_status(source, source_settings)
    if unusable is not None:
        return [], None, unusable
    try:
        document = fetch(source, domain)
    except Exception as error:  # pylint: disable=broad-exception-caught
        return [], None, SourceStatus(source=source, outcome=SourceOutcome.FAILED,
                                      detail=type(error).__name__)
    return parse_securitytrails_subdomains(document.payload, domain), document, \
        _combine_status(source, [document], [])


def _resolve_addresses(hosts: Sequence[str], lookup_records: RecordLookup) -> List[str]:
    """Las direcciones IPv4 de unos nombres, sin repetir y en orden de aparición.

    Un nombre que no resuelve, o cuya respuesta no es definitiva, simplemente
    no aporta direcciones.

    Args:
        hosts: Los nombres que resolver, en orden de prioridad.
        lookup_records: La búsqueda DNS inyectada.

    Returns:
        List[str]: Las direcciones encontradas.
    """
    addresses: List[str] = []
    for host in hosts:
        for value in lookup_records(host, "A") or []:
            if value not in addresses:
                addresses.append(value)
    return addresses


def collect_passive_intelligence(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    domain: str,
    fetch: SourceFetcher,
    lookup_records: RecordLookup,
    source_settings: Mapping[OsintSource, SourceSetting],
    now: datetime,
    recent_certificate_days: int = 30,
    max_subdomains: int = 500,
    max_host_lookups: int = 10,
) -> PassiveReport:
    """Reúne lo que las fuentes de terceros saben de un dominio y lo convierte en hallazgos.

    Pasos: Certificate Transparency y SecurityTrails dan los subdominios; los
    nombres más relevantes (el propio dominio primero) se resuelven en el DNS
    público y sus direcciones se preguntan a Shodan y Censys. Ninguno de los
    pasos contacta con el objetivo: resolver un nombre es preguntarle al DNS
    público, igual que las comprobaciones de higiene DNS.

    Args:
        domain: El dominio, ya normalizado (:func:`normalize_domain`).
        fetch: El fetcher inyectado (ver :data:`SourceFetcher`).
        lookup_records: La búsqueda DNS inyectada (ver :data:`RecordLookup`).
        source_settings: Qué fuentes están encendidas y con clave.
        now: El instante de referencia (naive en UTC) para las antigüedades.
        recent_certificate_days: Cuántos días atrás cuenta un certificado como
            «emitido recientemente». Por defecto ``30``.
        max_subdomains: Tope de hallazgos de subdominio; la lista completa de
            subdominios se conserva igualmente. Por defecto ``500``.
        max_host_lookups: Cuántos nombres, como mucho, se resuelven para
            preguntar a Shodan y Censys (cada uno gasta cuota). Por defecto
            ``10``.

    Returns:
        PassiveReport: Subdominios, servicios vistos, hallazgos y el estado de
            cada fuente, en el orden de :class:`OsintSource`.
    """
    subdomains_by_name: Dict[str, SubdomainRecord] = {}

    def remember(name: str, source: OsintSource, seen_at: Optional[datetime]) -> None:
        """Anota que ``source`` nombra ``name`` en ``seen_at``, si pertenece al dominio.

        Args:
            name: El nombre que da la fuente.
            source: La fuente.
            seen_at: La fecha del dato, o ``None`` si la fuente no fecha.
        """
        if not _belongs_to(name, domain):
            return
        subdomains_by_name.setdefault(name, SubdomainRecord(name=name)).observe(source, seen_at)

    certificates, certificate_document, certificate_status = _collect_certificates(
        domain, fetch, source_settings)
    # Un certificado que no cubre ningún nombre del dominio no dice nada de él,
    # y de los que sí, sólo cuentan sus nombres del dominio.
    certificates = [
        replace(certificate,
                names=tuple(name for name in certificate.names if _belongs_to(name, domain)))
        for certificate in certificates
        if any(_belongs_to(name, domain) for name in certificate.names)
    ]
    for certificate in certificates:
        for name in certificate.names:
            remember(name, OsintSource.CERTIFICATE_TRANSPARENCY, certificate.not_before)

    trails_names, trails_document, trails_status = _collect_securitytrails(
        domain, fetch, source_settings)
    for name in trails_names:
        remember(name, OsintSource.SECURITYTRAILS, None)

    subdomains = sorted(subdomains_by_name.values(), key=lambda record: record.name)

    observations: List[ServiceObservation] = []
    host_statuses: List[SourceStatus] = []
    if any(_usable_status(source, source_settings) is None for source in HOST_SOURCES):
        hosts = [domain] + [record.name for record in subdomains if record.name != domain]
        addresses = _resolve_addresses(hosts[:max(1, max_host_lookups)], lookup_records)
        observations, host_statuses = collect_host_observations(addresses, fetch, source_settings)
    else:
        host_statuses = [_usable_status(source, source_settings)  # type: ignore[misc]
                         for source in HOST_SOURCES]

    certificates_retrieved_at = certificate_document.retrieved_at if certificate_document else None
    retrieved_by_source = {
        OsintSource.CERTIFICATE_TRANSPARENCY: certificates_retrieved_at,
        OsintSource.SECURITYTRAILS: trails_document.retrieved_at if trails_document else None,
    }
    findings: List[dict] = []
    for record in subdomains[:max(0, max_subdomains)]:
        findings.append(build_subdomain_finding(record, retrieved_by_source, now))
    cutoff = now - timedelta(days=recent_certificate_days)
    for certificate in certificates:
        if certificate.not_before is not None and certificate.not_before >= cutoff:
            findings.append(build_recent_certificate_finding(
                certificate, certificates_retrieved_at, now))
    for observation in observations:
        findings.append(build_exposed_service_finding(observation, now))

    statuses_by_source = {status.source: status
                          for status in [certificate_status, trails_status, *host_statuses]}
    return PassiveReport(
        subdomains=subdomains,
        observations=observations,
        findings=findings,
        source_statuses=[statuses_by_source[source] for source in OsintSource],
    )


# =========================================================================
# HALLAZGOS PASIVOS
# =========================================================================

def _passive_finding(  # pylint: disable=too-many-arguments
        title: str, check_id: str, provenance: dict, *, port: Optional[int] = None,
        protocol: Optional[str] = None, service: Optional[str] = None,
        cpe: Optional[str] = None, cpe_resolved: Optional[bool] = None) -> dict:
    """Compone un hallazgo ``passive_exposure`` con su procedencia.

    La procedencia viaja dos veces, en claves de trabajo que ninguna columna
    guarda: ``_provenance`` para quien serializa el hallazgo a JSON, y
    ``_evidence`` para que ``ScanRepository.persist_findings`` la guarde como
    ``FindingEvidence`` cuando el hallazgo acaba en la tabla ``Finding``.

    Args:
        title: El título, que ya cuenta la fuente y la antigüedad.
        check_id: El identificador de la regla (``lybra:osint-…@1``).
        provenance: La procedencia (ver :func:`build_provenance`).
        port: El puerto al que se refiere, o ``None``. Por defecto ``None``.
        protocol: Su transporte, o ``None``. Por defecto ``None``.
        service: El producto o nombre que distingue el hallazgo. Por defecto
            ``None``.
        cpe: El CPE que sugiere la fuente, o ``None``. Por defecto ``None``.
        cpe_resolved: ``False`` cuando el hallazgo acompaña a un servicio que
            el motor no resolvió; ``None`` (por defecto) si no aplica.

    Returns:
        dict: El hallazgo con las columnas de ``Finding`` más ``_provenance``
            y ``_evidence``.
    """
    return {
        "title": title,
        "category": PASSIVE_EXPOSURE_CATEGORY,
        "port": port,
        "service": service,
        "protocol": protocol,
        "cpe": cpe,
        "source": "lybra",
        "check_id": check_id,
        "feed_version": OSINT_FEED_VERSION,
        "qod": QOD_THIRD_PARTY,
        "confirmed": False,
        "cpe_resolved": cpe_resolved,
        "severity": "INFO",
        "state": "open",
        "_provenance": provenance,
        "_evidence": {"kind": OSINT_EVIDENCE_KIND, "payload": provenance},
    }


def build_subdomain_finding(record: SubdomainRecord,
                            retrieved_by_source: Mapping[OsintSource, Optional[datetime]],
                            now: datetime) -> dict:
    """Hallazgo de un subdominio que fuentes públicas conocen.

    Args:
        record: El subdominio y quién lo conoce.
        retrieved_by_source: Cuándo se recogió la respuesta de cada fuente.
        now: El instante de referencia.

    Returns:
        dict: El hallazgo, con check ``lybra:osint-subdomain@1``. La
            procedencia nombra la fuente con el dato más reciente (la que
            fecha sus datos, si alguna lo hace).
    """
    ordered_sources = sorted(record.sources, key=lambda source: source.value)
    is_dated = OsintSource.CERTIFICATE_TRANSPARENCY in record.sources
    primary = OsintSource.CERTIFICATE_TRANSPARENCY if is_dated else ordered_sources[0]
    labels = ", ".join(SOURCE_LABELS[source] for source in ordered_sources)
    age_days = age_in_days(record.last_seen_at, now)
    provenance = build_provenance(
        primary.value, SOURCE_LABELS[primary], record.last_seen_at,
        retrieved_by_source.get(primary), now,
        record=record.to_json(),
    )
    return _passive_finding(
        f"Subdominio conocido públicamente: {record.name} "
        f"(según {labels}; {_describe_age(age_days)})",
        "lybra:osint-subdomain@1", provenance, service=record.name,
    )


def build_recent_certificate_finding(certificate: CertificateRecord,
                                     retrieved_at: Optional[datetime], now: datetime) -> dict:
    """Hallazgo de un certificado emitido hace poco para el dominio.

    Un certificado nuevo que nadie esperaba es la primera señal de un
    subdominio recién publicado, o de alguien que obtuvo un certificado a
    nombre del dominio sin permiso.

    Args:
        certificate: El certificado.
        retrieved_at: Cuándo se recogió la respuesta de crt.sh.
        now: El instante de referencia.

    Returns:
        dict: El hallazgo, con check ``lybra:osint-recent-certificate@1``.
    """
    age_days = age_in_days(certificate.not_before, now)
    shown_names = ", ".join(certificate.names[:3]) + (" …" if len(certificate.names) > 3 else "")
    provenance = build_provenance(
        OsintSource.CERTIFICATE_TRANSPARENCY.value,
        SOURCE_LABELS[OsintSource.CERTIFICATE_TRANSPARENCY],
        certificate.not_before, retrieved_at, now,
        record={"certificateId": certificate.certificate_id, "names": list(certificate.names),
                "issuer": certificate.issuer},
    )
    issued = "emitido hoy" if age_days == 0 else f"emitido hace {age_days} días"
    return _passive_finding(
        f"Certificado emitido recientemente para {shown_names} ({issued}; emisor: "
        f"{certificate.issuer or 'desconocido'}; según Certificate Transparency)",
        "lybra:osint-recent-certificate@1", provenance, service=certificate.names[0],
    )


def _observation_record(observation: ServiceObservation) -> dict:
    """El dato de una observación de terceros, reducido a lo que respalda el hallazgo.

    Args:
        observation: Lo que vio la fuente.

    Returns:
        dict: Dirección, puerto, protocolo, producto, versión y CPE.
    """
    return {
        "address": observation.address,
        "port": observation.port,
        "protocol": observation.protocol,
        "product": observation.product,
        "version": observation.version,
        "cpe": observation.cpe,
    }


def build_exposed_service_finding(observation: ServiceObservation, now: datetime) -> dict:
    """Hallazgo de un servicio que Shodan o Censys vieron abierto.

    Args:
        observation: Lo que vio la fuente.
        now: El instante de referencia.

    Returns:
        dict: El hallazgo, con check ``lybra:osint-exposed-service@1``. Si la
            fuente propuso un CPE, viaja en ``cpe`` y el título lo marca como
            sugerido: nunca lo resolvió el motor.
    """
    label = SOURCE_LABELS[observation.source]
    product = " ".join(part for part in (observation.product, observation.version) if part)
    age = _describe_age(age_in_days(observation.observed_at, now))
    title = (f"{label} vio el puerto {observation.port}/{observation.protocol} abierto en "
             f"{observation.address}{f' ({product})' if product else ''}; {age}")
    if observation.cpe:
        title += f"; CPE sugerido por {label}: {observation.cpe}"
    provenance = build_provenance(observation.source.value, label, observation.observed_at,
                                  observation.retrieved_at, now,
                                  record=_observation_record(observation))
    return _passive_finding(title, "lybra:osint-exposed-service@1", provenance,
                            port=observation.port, protocol=observation.protocol,
                            service=observation.product or None, cpe=observation.cpe)


def suggest_cpe_findings(  # pylint: disable=too-many-locals
        findings: Iterable[dict], observations: Iterable[ServiceObservation],
        now: datetime) -> List[dict]:
    """Propone un CPE de fuente externa para los servicios que el motor no identificó.

    Cierra, por vía externa, el hueco del fingerprint propio: cuando el motor
    no resolvió un puerto a un producto, Shodan o Censys a menudo sí lo tienen.
    Es deliberadamente conservador:

    * sólo actúa sobre los puertos cuyo hallazgo informativo (``open_port``)
      dice ``cpe_resolved=False``;
    * sólo propone un CPE que la fuente dio explícitamente y que se puede leer
      como vendor/producto;
    * si dos fuentes proponen productos distintos para el mismo puerto, no
      propone nada: la ambigüedad es falta de dato, no un dato;
    * el hallazgo que sale **no** dispara correlación de CVEs: dice «esto
      sugiere Shodan, sin confirmar», nunca «esto tiene tal vulnerabilidad».

    Args:
        findings: Los hallazgos del motor para el objetivo.
        observations: Lo que las fuentes de terceros vieron en su dirección.
        now: El instante de referencia.

    Returns:
        List[dict]: Un hallazgo ``lybra:osint-suggested-cpe@1`` por puerto sin
            resolver con una sugerencia inequívoca; lista vacía si ninguno.
    """
    unresolved_ports = {
        (finding.get("port"), (finding.get("protocol") or "tcp").lower())
        for finding in findings
        if finding.get("category") == "open_port" and finding.get("cpe_resolved") is False
        and finding.get("port") is not None
    }
    observations_by_port: Dict[Tuple[int, str], List[ServiceObservation]] = {}
    for observation in observations:
        key = (observation.port, observation.protocol)
        if key in unresolved_ports and observation.cpe:
            observations_by_port.setdefault(key, []).append(observation)

    suggestions: List[dict] = []
    for (port, protocol), candidates in sorted(observations_by_port.items()):
        identities = {
            tuple((parse_cpe23(candidate.cpe) or {}).get(part) for part in ("vendor", "product"))
            for candidate in candidates
        }
        if len(identities) != 1:
            continue
        newest = max(candidates, key=lambda candidate: candidate.observed_at or datetime.min)
        label = SOURCE_LABELS[newest.source]
        age = _describe_age(age_in_days(newest.observed_at, now))
        provenance = build_provenance(newest.source.value, label, newest.observed_at,
                                      newest.retrieved_at, now, record=_observation_record(newest))
        suggestions.append(_passive_finding(
            f"CPE sugerido por {label} para {port}/{protocol}: {newest.cpe} "
            f"({age}; sin confirmar por Lybra)",
            "lybra:osint-suggested-cpe@1", provenance, port=port, protocol=protocol,
            service=newest.product or None, cpe=newest.cpe, cpe_resolved=False,
        ))
    return suggestions


def finding_to_osint_json(finding: dict) -> dict:
    """Prepara un hallazgo de este módulo para guardarse como JSON.

    Quita las claves de trabajo (las que empiezan por ``_``) y saca la
    procedencia a una clave propia, ``provenance``, que es como la lee quien
    consulta un escaneo pasivo.

    Args:
        finding: Un hallazgo tal como lo producen las funciones de este módulo.

    Returns:
        dict: Las columnas del hallazgo en snake_case más ``provenance``.
    """
    serialized = {key: value for key, value in finding.items() if not key.startswith("_")}
    serialized["provenance"] = finding.get("_provenance") or {}
    return serialized
