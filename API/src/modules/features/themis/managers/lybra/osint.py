"""OsintManager — la inteligencia pasiva de Lybra: fuentes de terceros, caché y DNS.

La lógica vive en la capa pura (``themis/lybra/osint.py``); aquí está lo que
esa capa no puede tener: las peticiones HTTP a crt.sh, Shodan, Censys y
SecurityTrails, sus claves, la caché en base de datos, las consultas DNS con
``dnspython`` y el ciclo de vida del ``OsintScan`` en la cola de tareas.

**Nada de lo que hay aquí contacta con el objetivo.** Las fuentes son servicios
de terceros y el DNS se pregunta al resolutor configurado, que es lo mismo
que haría cualquier persona que busque el dominio. Por eso ni el registro de
objetivos autorizados ni el rechazo de direcciones privadas (la defensa
anti-SSRF de los escáneres) aplican a un escaneo pasivo: no hay objetivo al que
mandarle paquetes, igual que en el modo de payload externo de
``sources.py`` (``ExternalPayload.probes_target_network = False``). Lo único
que se filtra son las direcciones privadas antes de preguntar a Shodan o
Censys, y no por seguridad de red sino por discreción: preguntar por ellas
sólo revelaría la red interna del cliente a un tercero.

**Privacidad.** Preguntar a una fuente externa por un objetivo le revela que
nos interesa. El escaneo pasivo de un dominio se lanza a propósito, desde su
propio endpoint; el enriquecimiento de un escaneo Lybra normal
(:meth:`OsintManager.build_enrichment_findings`) sólo corre si el usuario lo
pidió para ese escaneo.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
from datetime import timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import dns.exception
import dns.resolver

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.shared._exceptions import ValidationError
from src.modules.system.taskqueue import (
    JobDeadlineExceeded,
    OutboxDispatcher,
    TaskQueue,
    TaskTrackingMixin,
    build_dispatch,
    job_context,
)
from src.modules.system.taskqueue.outbox_repository import TaskDispatchRepository

from ...exceptions import ScanNotFoundError
from ...lybra import (
    FetchedDocument,
    OsintSource,
    SourceSetting,
    assess_dns_hygiene,
    collect_host_observations,
    collect_passive_intelligence,
    fetch_document,
    finding_to_json,
    finding_to_osint_json,
    is_valid_dkim_selector,
    normalize_domain,
    suggest_cpe_findings,
)
from ...model import OsintScan, OsintScanMode, ScanFailureReason, ScanStatus
from ...repositories import OsintScanRepository, OsintSourceCacheRepository
from ...services.parsing import is_hostname


logger = logging.getLogger(__name__)

#: Cuántos selectores DKIM se admiten por escaneo. Cada uno es una consulta
#: DNS; el tope evita que la lista se convierta en la fuerza bruta de
#: selectores que la comprobación rechaza a propósito.
MAX_DKIM_SELECTORS = 10

#: Plazo del job en la cola, en segundos. Holgado a propósito: un escaneo hace
#: varias consultas a cada fuente (una por dirección) y cada una puede agotar
#: sus reintentos, incluida la espera de 30 s ante un límite de ritmo.
_JOB_TIMEOUT_SECONDS = 600

#: Estados en los que un escaneo pasivo todavía puede cambiar.
_ACTIVE_STATES = [ScanStatus.PENDING.value, ScanStatus.RUNNING.value]


# =========================================================================
# RED: FUENTES Y DNS
# =========================================================================

def _source_request(source: OsintSource, query: str) -> tuple:
    """La URL y las cabeceras de la petición a una fuente para una consulta.

    Args:
        source: La fuente.
        query: El dominio (crt.sh, SecurityTrails) o la dirección IP (Shodan,
            Censys).

    Returns:
        tuple: ``(url, cabeceras)``. La clave de Shodan va en la URL porque su
            API no la acepta de otra forma; por eso ningún error de este módulo
            se registra con su texto (ver ``_download_from_source``).
    """
    config = CR.lybra_osint_config()
    base_url = config.source_url(source.value)
    api_key = CR.get_lybra_osint_key(source.value)
    quoted = urllib.parse.quote(query, safe="")
    if source is OsintSource.CERTIFICATE_TRANSPARENCY:
        return f"{base_url}/?q={urllib.parse.quote('%.' + query, safe='')}&output=json", {}
    if source is OsintSource.SHODAN:
        return f"{base_url}/shodan/host/{quoted}?key={urllib.parse.quote(api_key, safe='')}", {}
    if source is OsintSource.CENSYS:
        token = base64.b64encode(api_key.encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        return f"{base_url}/hosts/{quoted}", headers
    return (f"{base_url}/domain/{quoted}/subdomains?children_only=false",
            {"APIKEY": api_key, "Accept": "application/json"})


def _download_from_source(source: OsintSource, query: str) -> Any:
    """Descarga y decodifica la respuesta de una fuente, sin caché.

    Args:
        source: La fuente.
        query: Lo consultado.

    Returns:
        Any: El JSON decodificado, o ``None`` cuando la fuente responde 404
            (Shodan y Censys lo hacen con una dirección que nunca vieron): es
            una respuesta, no un fallo.

    Raises:
        Exception: Cualquier otro error de red o de formato; quien llama lo
            cuenta como fuente caída.
    """
    url, headers = _source_request(source, query)
    timeout = int(CR.lybra_osint_config().request_timeout_seconds)
    try:
        body = fetch_document(url, timeout=timeout, headers=headers)
    except Exception as error:
        response = getattr(error, "response", None)
        if getattr(response, "status_code", None) == 404:
            return None
        raise
    if not body.strip():
        return None
    return json.loads(body)


def _fetch_with_cache(source: OsintSource, query: str,
                      download: Callable[[OsintSource, str], Any]) -> FetchedDocument:
    """Responde una consulta desde la caché si sigue vigente, o la descarga y la guarda.

    Args:
        source: La fuente.
        query: Lo consultado.
        download: La función que descarga de verdad (``(fuente, consulta) ->
            JSON | None``).

    Returns:
        FetchedDocument: La respuesta con su fecha de descarga; ``was_cached``
            dice de dónde salió. Un fallo de la descarga no se cachea: se
            propaga.
    """
    ttl = timedelta(hours=CR.lybra_osint_config().ttl_hours)
    now = utcnow_naive()
    with UnitOfWork() as uow:
        entry = OsintSourceCacheRepository(uow).get_entry(source.value, query)
        if entry is not None and entry.fetched_at + ttl > now:
            return FetchedDocument(payload=entry.payload, retrieved_at=entry.fetched_at,
                                   was_cached=True)

    payload = download(source, query)
    fetched_at = utcnow_naive()
    with UnitOfWork() as uow:
        OsintSourceCacheRepository(uow).save_entry(source.value, query, payload, fetched_at)
    return FetchedDocument(payload=payload, retrieved_at=fetched_at, was_cached=False)


def _build_fetcher(download: Optional[Callable[[OsintSource, str], Any]] = None
                   ) -> Callable[[OsintSource, str], FetchedDocument]:
    """El fetcher que recibe la capa pura: descarga con caché.

    Args:
        download: La descarga real. Por defecto ``None``, que usa
            :func:`_download_from_source` (resuelto al llamar, para que un test
            pueda sustituirlo).

    Returns:
        Callable: ``(fuente, consulta) -> FetchedDocument``.
    """
    def fetch(source: OsintSource, query: str) -> FetchedDocument:
        """Consulta una fuente pasando por la caché.

        Args:
            source: La fuente.
            query: Lo consultado.

        Returns:
            FetchedDocument: La respuesta, de la caché o de la red.
        """
        return _fetch_with_cache(source, query, download or _download_from_source)
    return fetch


def _record_to_text(record_type: str, rdata) -> str:
    """Un registro DNS como texto; un TXT con sus trozos unidos, como lo lee un receptor.

    Args:
        record_type: El tipo de registro consultado.
        rdata: El registro tal como lo da ``dnspython``.

    Returns:
        str: El valor en texto.
    """
    if record_type == "TXT":
        return b"".join(rdata.strings).decode("utf-8", "replace")
    return rdata.to_text()


def _lookup_dns_records(name: str, record_type: str) -> Optional[List[str]]:
    """Consulta el DNS público con ``dnspython``.

    Args:
        name: El nombre consultado.
        record_type: El tipo (``"A"``, ``"TXT"``, ``"MX"``, ``"CAA"``,
            ``"SOA"``, ``"DS"``…).

    Returns:
        Optional[List[str]]: Los valores en texto; lista vacía si el nombre no
            existe o no tiene registros de ese tipo; ``None`` si el DNS no dio
            una respuesta definitiva (tiempo agotado, servidores que fallan).
    """
    resolver = dns.resolver.Resolver()
    resolver.lifetime = float(CR.lybra_osint_config().request_timeout_seconds)
    try:
        answer = resolver.resolve(name, record_type, raise_on_no_answer=False)
    except dns.resolver.NXDOMAIN:
        return []
    except dns.exception.DNSException:
        # Tiempo agotado, servidores que fallan (SERVFAIL, REFUSED) o una
        # respuesta ilegible: nada de eso prueba que el registro no exista.
        return None
    if answer.rrset is None:
        return []
    return [_record_to_text(record_type, rdata) for rdata in answer.rrset]


def _build_lookup(lookup_records: Optional[Callable[[str, str], Optional[List[str]]]] = None
                  ) -> Callable[[str, str], Optional[List[str]]]:
    """La búsqueda DNS que recibe la capa pura.

    Args:
        lookup_records: Una búsqueda ya hecha (la de un test). Por defecto
            ``None``, que usa :func:`_lookup_dns_records` resuelto al llamar.

    Returns:
        Callable: ``(nombre, tipo) -> lista | None``.
    """
    def lookup(name: str, record_type: str) -> Optional[List[str]]:
        """Consulta un registro DNS con la búsqueda elegida.

        Args:
            name: El nombre consultado.
            record_type: El tipo de registro.

        Returns:
            Optional[List[str]]: Los valores, lista vacía o ``None``.
        """
        return (lookup_records or _lookup_dns_records)(name, record_type)
    return lookup


def _source_settings() -> Dict[OsintSource, SourceSetting]:
    """Qué fuentes están encendidas y con clave en este despliegue.

    Returns:
        Dict[OsintSource, SourceSetting]: Una entrada por fuente.
    """
    config = CR.lybra_osint_config()
    return {
        source: SourceSetting(
            is_enabled=config.is_source_enabled(source.value),
            has_credentials=bool(CR.get_lybra_osint_key(source.value)),
        )
        for source in OsintSource
    }


# =========================================================================
# EL JOB DEL ESCANEO PASIVO
# =========================================================================

def _run_osint_scan(  # pylint: disable=too-many-locals
        osint_scan_id: int,
        download: Optional[Callable[[OsintSource, str], Any]] = None,
        lookup_records: Optional[Callable[[str, str], Optional[List[str]]]] = None,
) -> None:
    """Cuerpo del job: consulta las fuentes y el DNS del dominio y guarda el resultado.

    Es repetible: recalcula todo y sobrescribe la fila por id, así que la
    reentrega de la outbox no duplica nada.

    Args:
        osint_scan_id: Clave primaria del ``OsintScan``.
        download: Sustituto de la descarga real, para los tests. Por defecto
            ``None``: la red de verdad.
        lookup_records: Sustituto de la búsqueda DNS, para los tests. Por
            defecto ``None``: ``dnspython``.
    """
    with job_context() as job:
        with UnitOfWork() as uow:
            repository = OsintScanRepository(uow)
            scan = repository.get_by_id(osint_scan_id)
            if scan is None:
                logger.warning("Escaneo pasivo %s no encontrado; se descarta el job", osint_scan_id)
                return
            domain = scan.domain
            dkim_selectors = list((scan.parameters or {}).get("dkim_selectors") or [])
            repository.transition_if_state(osint_scan_id, _ACTIVE_STATES,
                                           status=ScanStatus.RUNNING.value)

        try:
            config = CR.lybra_osint_config()
            fetch = _build_fetcher(download)
            lookup = _build_lookup(lookup_records)
            report = collect_passive_intelligence(
                domain, fetch, lookup, _source_settings(), utcnow_naive(),
                recent_certificate_days=config.recent_certificate_days,
                max_subdomains=config.max_subdomains,
                max_host_lookups=config.max_host_lookups,
            )
            job.progress(60)
            if job.cancelled():
                _finish(osint_scan_id, ScanStatus.CANCELLED)
                return
            dns_findings, dns_checks = assess_dns_hygiene(
                domain, lookup, utcnow_naive(), dkim_selectors)
            job.progress(90)

            with UnitOfWork() as uow:
                OsintScanRepository(uow).transition_if_state(
                    osint_scan_id, _ACTIVE_STATES,
                    status=ScanStatus.FINISHED.value,
                    finished_at=utcnow_naive(),
                    sources=[status.to_json() for status in report.source_statuses],
                    dns_checks=[result.to_json() for result in dns_checks],
                    subdomains=[record.to_json() for record in report.subdomains],
                    findings=[finding_to_osint_json(finding)
                              for finding in report.findings + dns_findings],
                )
            logger.info("Escaneo pasivo %s de %s terminado: %d subdominios, %d hallazgos",
                        osint_scan_id, domain, len(report.subdomains),
                        len(report.findings) + len(dns_findings))
        # Se cierra la fila y se vuelve a lanzar: la cola tiene que seguir viendo
        # el trabajo como fallido por plazo.
        except JobDeadlineExceeded:
            _finish(osint_scan_id, ScanStatus.FAILED, ScanFailureReason.TIMEOUT)
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error("Error en el escaneo pasivo %s: %s", osint_scan_id, type(error).__name__,
                         exc_info=True)
            _finish(osint_scan_id, ScanStatus.FAILED, ScanFailureReason.INTERNAL_ERROR)


def _finish(osint_scan_id: int, status: ScanStatus,
            failure_reason: Optional[ScanFailureReason] = None) -> None:
    """Cierra un escaneo pasivo en un estado terminal, si seguía en curso.

    Args:
        osint_scan_id: Clave primaria del escaneo.
        status: El estado final (``FAILED`` o ``CANCELLED``).
        failure_reason: Por qué falló. Por defecto ``None``.
    """
    with UnitOfWork() as uow:
        OsintScanRepository(uow).transition_if_state(
            osint_scan_id, _ACTIVE_STATES,
            status=status.value, finished_at=utcnow_naive(),
            failure_reason=failure_reason.value if failure_reason else None,
        )


def _format_scan(scan: OsintScan, include_details: bool = True) -> dict:
    """Serializa un escaneo pasivo para la API, en camelCase.

    Args:
        scan: El escaneo.
        include_details: Si se incluyen fuentes, comprobaciones DNS,
            subdominios y hallazgos. Por defecto ``True``; el listado usa
            ``False`` y sólo cuenta.

    Returns:
        dict: ``osintScanId``, ``domain``, ``mode``, ``status``,
            ``startedAt``, ``finishedAt``, ``failureReason``,
            ``subdomainCount`` y ``findingCount``; con detalle, además
            ``dkimSelectors``, ``cloudResources`` y ``checkSubdomains`` (lo
            que pidió el usuario: los dos últimos solo tienen sentido en modo
            cloud), ``sources``, ``dnsChecks``, ``subdomains`` y ``findings``
            (cada uno con la forma común de un hallazgo más su
            ``provenance``).
    """
    findings = scan.findings or []
    subdomains = scan.subdomains or []
    formatted = {
        "osintScanId": scan.id,
        "domain": scan.domain,
        "mode": scan.mode,
        "status": scan.status,
        "startedAt": isoformat_utc(scan.started_at),
        "finishedAt": isoformat_utc(scan.finished_at),
        "failureReason": scan.failure_reason,
        "subdomainCount": len(subdomains),
        "findingCount": len(findings),
    }
    if include_details:
        formatted.update({
            "dkimSelectors": list((scan.parameters or {}).get("dkim_selectors") or []),
            "cloudResources": list((scan.parameters or {}).get("cloud_resources") or []),
            "checkSubdomains": bool((scan.parameters or {}).get("check_subdomains")),
            "sources": scan.sources or [],
            "dnsChecks": scan.dns_checks or [],
            "subdomains": subdomains,
            # Un escaneo pasivo mira un dominio publicado en Internet: su
            # exposición es pública por definición.
            "findings": [
                {**finding_to_json(finding, "public"),
                 "provenance": finding.get("provenance") or {}}
                for finding in findings
            ],
        })
    return formatted


def _normalized_selectors(selectors: Optional[Iterable[str]]) -> List[str]:
    """Valida y limpia los selectores DKIM que pidió el usuario.

    Args:
        selectors: Los selectores tal como llegaron, o ``None``.

    Returns:
        List[str]: Los selectores en minúsculas, sin repetir y en su orden.

    Raises:
        ValidationError: Si hay más de :data:`MAX_DKIM_SELECTORS` o alguno no
            es un nombre DNS válido.
    """
    cleaned = list(dict.fromkeys(
        (selector or "").strip().lower() for selector in (selectors or [])))
    if len(cleaned) > MAX_DKIM_SELECTORS:
        raise ValidationError(
            f"Demasiados selectores DKIM: {len(cleaned)}", field="dkimSelectors",
            user_message=f"Indica como mucho {MAX_DKIM_SELECTORS} selectores DKIM.",
        )
    for selector in cleaned:
        if not is_valid_dkim_selector(selector):
            raise ValidationError(
                f"Selector DKIM no válido: {selector!r}", field="dkimSelectors", value=selector,
                user_message=f"«{selector}» no es un selector DKIM válido.",
            )
    return cleaned


def _resolve_public_address(target: str,
                            lookup: Callable[[str, str], Optional[List[str]]]) -> Optional[str]:
    """La dirección que se pregunta a Shodan y Censys para un objetivo de Lybra.

    Args:
        target: La IP o el nombre de host del escaneo.
        lookup: La búsqueda DNS.

    Returns:
        Optional[str]: La propia IP, o la primera dirección A del nombre;
            ``None`` si el nombre no resuelve.
    """
    if not is_hostname(target):
        return target
    addresses = lookup(target, "A") or []
    return addresses[0] if addresses else None


class OsintManager(TaskTrackingMixin):
    """La inteligencia pasiva de Lybra: escaneos de dominio y enriquecimiento de escaneos.

    Ofrece dos cosas, las dos sin tocar el objetivo:

    * El **escaneo pasivo de un dominio** (:meth:`create_passive_scan`): un
      ``OsintScan`` que se ejecuta en segundo plano con la categoría
      ``themis.osint``.
    * El **enriquecimiento de un escaneo Lybra** que el usuario pidió
      (:meth:`build_enrichment_findings`): CPE sugeridos por Shodan o Censys
      para los puertos que el fingerprint propio no identificó.
    """

    EXTERNAL_ID_PREFIX = "themis-osint:"
    TASK_CATEGORY = "themis.osint"

    def create_passive_scan(self, user_id: int, domain: str,
                            dkim_selectors: Optional[Sequence[str]] = None) -> OsintScan:
        """Crea un escaneo pasivo de un dominio y encola su ejecución.

        No hay comprobación de autorización ni de dirección privada: el
        escaneo no contacta con el objetivo (ver el docstring del módulo).

        Args:
            user_id: Dueño del escaneo.
            domain: El dominio, tal como lo escribió el usuario.
            dkim_selectors: Selectores DKIM que comprobar, como mucho
                :data:`MAX_DKIM_SELECTORS`. Por defecto ninguno: DKIM no se
                comprueba (adivinar selectores sería fuerza bruta).

        Returns:
            OsintScan: El escaneo ya guardado en ``pending``. Si publicar el job
                falla, la fila de la outbox lo reintenta; el escaneo existe
                igualmente.

        Raises:
            ValidationError: Si ``domain`` no es un nombre de dominio o los
                selectores no son válidos.
        """
        normalized = normalize_domain(domain)
        if normalized is None:
            raise ValidationError(
                f"Dominio no válido: {domain!r}", field="domain", value=domain,
                user_message=f"«{domain}» no es un nombre de dominio válido.",
            )
        selectors = _normalized_selectors(dkim_selectors)

        scan = OsintScan(
            user_id=user_id, domain=normalized, mode=OsintScanMode.PASSIVE.value,
            status=ScanStatus.PENDING.value, started_at=utcnow_naive(),
            parameters={"dkim_selectors": selectors},
        )
        with UnitOfWork() as uow:
            OsintScanRepository(uow).save(scan)
            dispatch = TaskDispatchRepository(uow).save(build_dispatch(
                func=OsintManager.execute_osint_scan,
                name=f"OsintScan-{scan.id}",
                category=self.TASK_CATEGORY,
                args=(scan.id,),
                external_id=self.external_id_for(scan.id),
                timeout=_JOB_TIMEOUT_SECONDS,
            ))
            dispatch_id = dispatch.id
            # El worker es otro proceso: la fila tiene que verse antes de publicar.
            uow.commit_for_handoff()

        OutboxDispatcher.dispatch(dispatch_id, task_queue=self._task_queue)
        logger.info("Escaneo pasivo %s de %s encolado", scan.id, normalized)
        return scan

    def get_scan(self, osint_scan_id: int, user_id: int) -> dict:
        """Devuelve un escaneo pasivo del usuario con todo su detalle.

        Args:
            osint_scan_id: Clave primaria del escaneo.
            user_id: Usuario que lo pide.

        Returns:
            dict: El escaneo serializado (ver ``_format_scan``).

        Raises:
            ScanNotFoundError: Si no existe o es de otro usuario.
        """
        scan = build_repository(OsintScanRepository).get_by_id_and_user(osint_scan_id, user_id)
        if scan is None:
            raise ScanNotFoundError(osint_scan_id)
        return _format_scan(scan)

    def list_scans(self, user_id: int, limit: int = 50, mode: Optional[str] = None) -> List[dict]:
        """Los escaneos de dominio recientes del usuario, sin detalle.

        Args:
            user_id: Usuario dueño.
            limit: Cuántos, como mucho. Por defecto ``50``.
            mode: Solo los de este modo, un valor de ``OsintScanMode``. Por
                defecto ``None``: todos.

        Returns:
            List[dict]: Del más nuevo al más viejo, cada uno con sus recuentos.
        """
        scans = build_repository(OsintScanRepository).get_recent_by_user(user_id, limit, mode)
        return [_format_scan(scan, include_details=False) for scan in scans]

    @staticmethod
    def execute_osint_scan(osint_scan_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            osint_scan_id: Clave primaria del ``OsintScan``.
        """
        _run_osint_scan(osint_scan_id)

    @classmethod
    def reconcile_orphaned_scans(cls) -> int:
        """Marca como fallidos los escaneos pasivos que ya no tienen quien los termine.

        Se llama al arrancar la API. Un escaneo en curso cuyo job ya no se
        puede recuperar (el worker murió, Redis se vació) se quedaría en
        ``running`` para siempre.

        Returns:
            int: Cuántos escaneos se marcaron como fallidos.
        """
        task_queue = TaskQueue.get_instance()
        fixed = 0
        with UnitOfWork() as uow:
            repository = OsintScanRepository(uow)
            for scan in repository.get_active():
                external_id = f"{cls.EXTERNAL_ID_PREFIX}{scan.id}"
                if task_queue.is_recoverable(external_id, cls.TASK_CATEGORY):
                    continue
                if repository.transition_if_state(
                        scan.id, _ACTIVE_STATES, status=ScanStatus.FAILED.value,
                        finished_at=utcnow_naive(),
                        failure_reason=ScanFailureReason.ORPHANED.value):
                    fixed += 1
        return fixed

    @staticmethod
    def build_enrichment_findings(
        target: str,
        findings: Iterable[dict],
        download: Optional[Callable[[OsintSource, str], Any]] = None,
        lookup_records: Optional[Callable[[str, str], Optional[List[str]]]] = None,
    ) -> List[dict]:
        """CPE sugeridos por fuentes externas para los puertos que Lybra no identificó.

        Sólo lo llama un escaneo Lybra cuyo usuario pidió el enriquecimiento
        (es una consulta a terceros sobre su objetivo, y eso es una decisión
        suya). Pregunta a Shodan y Censys por la dirección del objetivo, pasando
        por la caché, y propone un CPE para cada puerto sin resolver en el que
        la fuente lo tenga claro (ver ``suggest_cpe_findings``). Un fallo de
        las fuentes no rompe el escaneo: devuelve lo que haya.

        Args:
            target: La IP o el nombre de host del escaneo.
            findings: Los hallazgos que el motor ya produjo para el objetivo.
            download: Sustituto de la descarga real, para los tests. Por
                defecto ``None``.
            lookup_records: Sustituto de la búsqueda DNS, para los tests. Por
                defecto ``None``.

        Returns:
            List[dict]: Hallazgos ``passive_exposure`` con su procedencia (y su
                evidencia ``osint_record`` para ``FindingEvidence``); lista
                vacía si no hay puertos sin resolver, el objetivo es privado o
                ninguna fuente está disponible.
        """
        finding_list = list(findings)
        has_unresolved_port = any(
            finding.get("category") == "open_port" and finding.get("cpe_resolved") is False
            for finding in finding_list
        )
        if not has_unresolved_port:
            return []
        address = _resolve_public_address(target, _build_lookup(lookup_records))
        if address is None:
            return []
        observations, statuses = collect_host_observations(
            [address], _build_fetcher(download), _source_settings())
        for status in statuses:
            logger.info("Enriquecimiento pasivo de %s: %s %s%s", target, status.source.value,
                        status.outcome.value, f" ({status.detail})" if status.detail else "")
        return suggest_cpe_findings(finding_list, observations, utcnow_naive())
