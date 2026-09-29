"""La mitad de red del análisis de la superficie de una API.

La decisión (qué dice la especificación y qué checks salen de ella) vive en
``lybra.api_surface``, libre de red; aquí sólo se pide la especificación y se
ejecutan los checks derivados con el mismo runtime que el resto de checks
activos.
"""

import logging
from typing import Callable, List, Optional

import src.modules.system.config_reading as CR
from ...lybra import (
    CheckRuntime,
    HostRateLimiter,
    HttpProbe,
    SPECIFICATION_PATHS,
    derive_api_checks,
    is_http_service,
    parse_specification,
)

logger = logging.getLogger(__name__)


def run_api_surface(
    target: str,
    services: list,
    mode: str = "safe",
    cancel_check: Optional[Callable[[], bool]] = None,
    fetch: Optional[Callable] = None,
) -> List[dict]:
    """Prueba los endpoints que la especificación de cada servicio web declara protegidos.

    Por cada servicio HTTP pide, como mucho, las rutas de
    :data:`~...lybra.SPECIFICATION_PATHS` hasta dar con una especificación que
    se pueda parsear, deriva de ella los checks (con el tope de
    ``features.themis.scanners.lybra.apiSurface.maxEndpoints``) y los ejecuta.

    Los checks de lectura y el de asignación masiva se ejecutan en runtimes
    **distintos** a propósito: el runtime comparte por ejecución la respuesta de
    cada petición, y la lectura posterior a una escritura devolvería la
    respuesta que otro check pidió *antes* de escribir, con lo que el fallo
    nunca se vería. Los de escritura sólo corren en modo ``aggressive``.

    Best-effort, como el resto de fases de red: un fallo no hunde el escaneo.

    Args:
        target: El objetivo (IP o nombre ya fijado a la IP validada).
        services: Los servicios del escaneo.
        mode: ``"safe"`` o ``"aggressive"``; el segundo habilita el check de
            asignación masiva. Por defecto ``"safe"``.
        cancel_check: Función sin argumentos que dice si el escaneo se
            canceló, o ``None``. Por defecto ``None``.
        fetch: ``(host, port, method, path, body, headers) -> Response | None``.
            Por defecto, una :class:`~...lybra.HttpProbe` con la
            configuración del motor.

    Returns:
        list: Los hallazgos de los checks derivados que dispararon. Vacía si
            ningún servicio publica una especificación, si el análisis está
            desactivado (``maxEndpoints`` a cero) o si algo falló.
    """
    config = CR.lybra_api_surface_config()
    if config.max_endpoints < 1:
        return []
    try:
        engine = CR.lybra_engine_config()
        fetch = fetch or HttpProbe(
            timeout=engine.http_timeout,
            max_bytes=config.max_specification_bytes,
            user_agent=engine.http_user_agent,
        ).fetch
        limiter = HostRateLimiter(
            min_interval=engine.rate_limit_interval,
            max_backoff_factor=engine.rate_limit_max_backoff_factor,
        )
        findings: List[dict] = []
        for service in services:
            if not is_http_service(service) or (cancel_check and cancel_check()):
                continue
            checks = _derived_checks(target, service, fetch, limiter, config.max_endpoints)
            for check_mode in ("safe", "aggressive"):
                group = [check for check in checks if check.mode == check_mode]
                if not group or (check_mode == "aggressive" and mode != "aggressive"):
                    continue
                findings.extend(CheckRuntime(
                    group, fetch, mode=mode, rate_limiter=limiter,
                    capture_evidence=CR.lybra_evidence_config().enabled,
                ).run(target, [service], cancel_check=cancel_check))
        return findings
    except Exception:  # noqa: BLE001 - un fallo aquí cuesta este análisis, no el escaneo
        logger.exception("Lybra API surface analysis failed for %s", target)
        return []


def _derived_checks(target: str, service, fetch: Callable, limiter: HostRateLimiter,
                    max_endpoints: int) -> list:
    """Los checks derivados de la primera especificación parseable de un servicio.

    Args:
        target: El objetivo.
        service: El servicio web.
        fetch: La función que hace las peticiones.
        limiter: El limitador de ritmo del host.
        max_endpoints: El tope de checks derivados.

    Returns:
        list: Los checks; vacía si el servicio no publica especificación.
    """
    for path in SPECIFICATION_PATHS:
        limiter.acquire(target)
        response = fetch(target, service.port, "GET", path)
        if response is None or response.status != 200:
            continue
        specification = parse_specification(response.body)
        if specification is not None:
            return derive_api_checks(specification, max_endpoints)
    return []
