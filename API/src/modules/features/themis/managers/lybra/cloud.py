"""CloudScanManager — la exposición cloud de Lybra: recursos declarados y subdominios.

La decisión de qué es una exposición vive en la capa pura
(``themis/lybra/cloud.py``); aquí está lo que esa capa no puede tener: la
autorización del usuario, las peticiones HTTP, la resolución DNS y el ciclo de
vida del escaneo en la cola de tareas.

**Un escaneo cloud es un ``OsintScan`` de modo ``cloud``**, no un ``LybraScan``.
Un ``LybraScan`` descubre los puertos de un host y analiza sus servicios; un
bucket o una base no tienen host ni puerto, y un subdominio secuestrable se
encuentra leyendo el DNS. La tabla de escaneos de dominio ya guarda justo eso
(dominio, subdominios conocidos, hallazgos con su procedencia) y su modo estaba
previsto para esta extensión, así que se reutilizan el modelo, la cola
(``themis.osint``), la reconciliación de escaneos huérfanos y los endpoints de
consulta (``GET /themis/osint``).

**Este escaneo sí toca a terceros, y por eso sí exige autorización.** A
diferencia del escaneo pasivo, que sólo pregunta a fuentes públicas, aquí se
piden los recursos del cliente. Nada se toca sin una entrada en el registro de
objetivos autorizados: el dominio (que cubre sus subdominios) para el takeover, y
cada recurso cloud por su forma exacta. La autorización se comprueba al crear
el escaneo **y otra vez al ejecutarlo**: el usuario puede haberla retirado entre
medias.

Los recursos se **declaran** o llegan de un escaneo pasivo previo del dominio
(``OsintScan.subdomains``); nunca se enumeran nombres.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence

import dns.exception
import dns.resolver

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.shared._exceptions import ValidationError
from src.modules.system.taskqueue import (
    JobDeadlineExceeded,
    OutboxDispatcher,
    TaskTrackingMixin,
    build_dispatch,
    job_context,
)
from src.modules.system.taskqueue.outbox_repository import TaskDispatchRepository

from ...exceptions import TargetNotAuthorizedError
from ...lybra import (
    CloudProbe,
    HttpProbe,
    compute_dedup_key,
    normalize_domain,
    parse_cloud_resource,
    Response,
)
from ...model import OsintScan, OsintScanMode, ScanFailureReason, ScanStatus
from ...repositories import OsintScanRepository
from ..authorized_target import AuthorizedTargetManager
from .osint import OsintManager

logger = logging.getLogger(__name__)

#: Cuántos recursos cloud se admiten por escaneo. Cada uno es una petición a un
#: tercero; el tope evita que una lista larga se use para enumerar.
MAX_CLOUD_RESOURCES = 25

#: Plazo del job en la cola, en segundos.
_JOB_TIMEOUT_SECONDS = 600

_ACTIVE_STATES = [ScanStatus.PENDING.value, ScanStatus.RUNNING.value]


def _resolve_cname(name: str) -> Optional[str]:
    """El destino al que apunta un nombre por CNAME, según el DNS público.

    Args:
        name: El nombre consultado.

    Returns:
        Optional[str]: El destino del primer CNAME; ``None`` si el nombre no es
            un CNAME, no existe o el DNS no dio una respuesta definitiva. En
            los tres casos no hay nada que comprobar.
    """
    resolver = dns.resolver.Resolver()
    resolver.lifetime = float(CR.lybra_osint_config().request_timeout_seconds)
    try:
        answer = resolver.resolve(name, "CNAME", raise_on_no_answer=False)
    except dns.exception.DNSException:
        return None
    if answer.rrset is None:
        return None
    return next((rdata.to_text() for rdata in answer.rrset), None)


def _build_fetch() -> Callable[[str, int, str], Optional[Response]]:
    """La petición HTTP que recibe la sonda: un ``GET`` con la configuración del motor.

    Returns:
        Callable: ``(host, puerto, ruta) -> Response | None``.
    """
    engine = CR.lybra_engine_config()
    probe = HttpProbe(timeout=engine.http_timeout, max_bytes=engine.http_max_body_bytes,
                      user_agent=engine.http_user_agent)
    return lambda host, port, path: probe.fetch(host, port, "GET", path)


def _subdomains_to_probe(user_id: int, domain: str) -> List[str]:
    """Los nombres que se comprueban para el takeover: el dominio y sus subdominios conocidos.

    Los subdominios salen del último escaneo pasivo terminado del dominio, con
    el tope de ``maxSubdomains``. Sin escaneo previo sólo se comprueba el propio
    dominio: no se inventan nombres.

    Args:
        user_id: Dueño del escaneo.
        domain: El dominio, normalizado.

    Returns:
        List[str]: Nombres sin repetir, el dominio primero.
    """
    with UnitOfWork() as uow:
        passive = OsintScanRepository(uow).get_latest_finished(
            user_id, domain, OsintScanMode.PASSIVE.value)
        known = [record.get("name") for record in (passive.subdomains or [])] if passive else []
    names = [domain]
    for name in known:
        if name and name not in names:
            names.append(name)
    return names[:CR.lybra_osint_config().max_subdomains]


def _run_cloud_scan(
        osint_scan_id: int,
        fetch: Optional[Callable[[str, int, str], Optional[Response]]] = None,
        resolve_cname: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Cuerpo del job: comprueba los recursos declarados y los subdominios, y guarda el resultado.

    Es repetible: recalcula todo y sobrescribe la fila por id, así que la
    reentrega de la outbox no duplica nada. La autorización se vuelve a
    comprobar aquí y lo que ya no esté autorizado se **omite**, no se toca.

    Args:
        osint_scan_id: Clave primaria del ``OsintScan``.
        fetch: Sustituto de la petición HTTP, para los tests. Por defecto
            ``None``: la red de verdad.
        resolve_cname: Sustituto de la resolución de CNAME, para los tests. Por
            defecto ``None``: ``dnspython``.
    """
    with job_context() as job:
        with UnitOfWork() as uow:
            repository = OsintScanRepository(uow)
            scan = repository.get_by_id(osint_scan_id)
            if scan is None:
                logger.warning("Escaneo cloud %s no encontrado; se descarta el job", osint_scan_id)
                return
            user_id, domain = scan.user_id, scan.domain
            parameters = scan.parameters or {}
            resources = list(parameters.get("cloud_resources") or [])
            checks_subdomains = bool(parameters.get("check_subdomains"))
            repository.transition_if_state(osint_scan_id, _ACTIVE_STATES,
                                           status=ScanStatus.RUNNING.value)

        try:
            probe = CloudProbe(fetch or _build_fetch(), resolve_cname or _resolve_cname)
            findings: List[dict] = []
            names: List[str] = []
            for raw in resources:
                if job.cancelled():
                    break
                resource = parse_cloud_resource(raw)
                if resource is None or not AuthorizedTargetManager.is_cloud_resource_authorized(
                        user_id, resource.canonical):
                    logger.warning("Escaneo cloud %s: recurso no autorizado, se omite", osint_scan_id)
                    continue
                findings.append(probe.probe_resource(resource))
            if checks_subdomains and AuthorizedTargetManager.is_domain_authorized(user_id, domain):
                names = _subdomains_to_probe(user_id, domain)
                for name in names:
                    if job.cancelled():
                        break
                    findings.append(probe.probe_subdomain(name))
            if job.cancelled():
                _finish(osint_scan_id, ScanStatus.CANCELLED)
                return

            observed_at = isoformat_utc(utcnow_naive())
            serialized = []
            for finding in (found for found in findings if found is not None):
                finding["dedup_key"] = compute_dedup_key({**finding, "host_id": None})
                finding["provenance"] = {"source": "cloud", "observedAt": observed_at}
                serialized.append(finding)
            with UnitOfWork() as uow:
                OsintScanRepository(uow).transition_if_state(
                    osint_scan_id, _ACTIVE_STATES,
                    status=ScanStatus.FINISHED.value, finished_at=utcnow_naive(),
                    subdomains=[{"name": name} for name in names],
                    findings=serialized,
                )
            logger.info("Escaneo cloud %s de %s terminado: %d hallazgos",
                        osint_scan_id, domain, len(serialized))
        except JobDeadlineExceeded:
            _finish(osint_scan_id, ScanStatus.FAILED, ScanFailureReason.TIMEOUT)
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error("Error en el escaneo cloud %s: %s", osint_scan_id, type(error).__name__,
                         exc_info=True)
            _finish(osint_scan_id, ScanStatus.FAILED, ScanFailureReason.INTERNAL_ERROR)


def _finish(osint_scan_id: int, status: ScanStatus,
            failure_reason: Optional[ScanFailureReason] = None) -> None:
    """Cierra un escaneo cloud en un estado terminal, si seguía en curso.

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


class CloudScanManager(TaskTrackingMixin):
    """Lanza escaneos de exposición cloud y los deja consultables como escaneos de dominio.

    Comparte cola, prefijo de ``external_id`` y reconciliación con
    :class:`OsintManager` a propósito: es la misma tabla y el mismo tipo de
    trabajo, así que el arranque de la API ya recupera los escaneos cloud
    huérfanos, y ``GET /themis/osint`` los lista.
    """

    EXTERNAL_ID_PREFIX = OsintManager.EXTERNAL_ID_PREFIX
    TASK_CATEGORY = OsintManager.TASK_CATEGORY

    def create_cloud_scan(self, user_id: int, domain: str,
                          cloud_resources: Optional[Sequence[str]] = None,
                          check_subdomains: bool = True) -> OsintScan:
        """Valida, autoriza y encola un escaneo de exposición cloud.

        Args:
            user_id: Dueño del escaneo.
            domain: El dominio al que pertenece lo que se comprueba, tal como lo
                escribió el usuario.
            cloud_resources: Recursos a comprobar, en forma
                ``proveedor:identificador`` (``s3:nombre``, ``gcs:nombre``,
                ``azure:cuenta/contenedor``, ``firebase:proyecto``), como mucho
                :data:`MAX_CLOUD_RESOURCES`. Por defecto ninguno.
            check_subdomains: Si se comprueba el takeover del dominio y de sus
                subdominios conocidos por un escaneo pasivo previo. Por defecto
                ``True``.

        Returns:
            OsintScan: El escaneo ya guardado en ``pending``.

        Raises:
            ValidationError: Si el dominio o un recurso no son válidos, hay más
                recursos que el tope, o no se pidió comprobar nada.
            TargetNotAuthorizedError: Si el dominio (con ``check_subdomains``) o
                algún recurso no está en el registro de objetivos autorizados.
                Ningún recurso se toca sin autorización, y un solo recurso sin
                ella rechaza la petición entera.
        """
        normalized = normalize_domain(domain)
        if normalized is None:
            raise ValidationError(
                f"Dominio no válido: {domain!r}", field="domain", value=domain,
                user_message=f"«{domain}» no es un nombre de dominio válido.")
        raw_resources = list(cloud_resources or [])
        if not raw_resources and not check_subdomains:
            raise ValidationError(
                "Nada que comprobar", field="cloudResources", value=raw_resources,
                user_message="Indica algún recurso cloud o pide comprobar los subdominios.")
        if len(raw_resources) > MAX_CLOUD_RESOURCES:
            raise ValidationError(
                "Demasiados recursos", field="cloudResources", value=len(raw_resources),
                user_message=f"Como mucho {MAX_CLOUD_RESOURCES} recursos cloud por escaneo.")
        canonical_resources: List[str] = []
        for raw in raw_resources:
            resource = parse_cloud_resource(raw)
            if resource is None:
                raise ValidationError(
                    f"Recurso cloud no válido: {raw!r}", field="cloudResources", value=raw,
                    user_message=(f"«{raw}» no es un recurso cloud válido "
                                  "(s3:nombre, gcs:nombre, azure:cuenta/contenedor, firebase:proyecto)."))
            if not AuthorizedTargetManager.is_cloud_resource_authorized(user_id, resource.canonical):
                raise TargetNotAuthorizedError(resource.canonical)
            if resource.canonical not in canonical_resources:
                canonical_resources.append(resource.canonical)
        if check_subdomains and not AuthorizedTargetManager.is_domain_authorized(user_id, normalized):
            raise TargetNotAuthorizedError(normalized)

        scan = OsintScan(
            user_id=user_id, domain=normalized, mode=OsintScanMode.CLOUD.value,
            status=ScanStatus.PENDING.value, started_at=utcnow_naive(),
            parameters={"cloud_resources": canonical_resources,
                        "check_subdomains": bool(check_subdomains)},
        )
        with UnitOfWork() as uow:
            OsintScanRepository(uow).save(scan)
            dispatch = TaskDispatchRepository(uow).save(build_dispatch(
                func=CloudScanManager.execute_cloud_scan,
                name=f"CloudScan-{scan.id}",
                category=self.TASK_CATEGORY,
                args=(scan.id,),
                external_id=self.external_id_for(scan.id),
                timeout=_JOB_TIMEOUT_SECONDS,
            ))
            dispatch_id = dispatch.id
            # El worker es otro proceso: la fila tiene que verse antes de publicar.
            uow.commit_for_handoff()

        OutboxDispatcher.dispatch(dispatch_id, task_queue=self._task_queue)
        logger.info("Escaneo cloud %s de %s encolado", scan.id, normalized)
        return scan

    @staticmethod
    def execute_cloud_scan(osint_scan_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            osint_scan_id: Clave primaria del ``OsintScan``.
        """
        _run_cloud_scan(osint_scan_id)
