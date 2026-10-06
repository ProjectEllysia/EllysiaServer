"""
IrisUrlExpansionManager — seguir una URL de un correo hasta su destino real.

Es una consulta externa bajo demanda (ver ``managers/enrichment.py`` para las
reglas comunes): nunca se hace sola dentro de un análisis, solo sobre una URL
que aparece en un análisis del usuario, y con la superficie
``externalEnrichment`` abierta.

Seguir una cadena de redirects son varias peticiones de red, así que va en
segundo plano: la petición deja la expansión en ``pending`` y encola el job
por la outbox (``iris.enrichment``); el cliente sondea el listado.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.system.taskqueue import TaskTrackingMixin, job_context
from src.modules.system.taskqueue.dispatcher import OutboxDispatcher
from src.modules.system.taskqueue.outbox import build_dispatch
from src.modules.system.taskqueue.outbox_repository import TaskDispatchRepository
from src.modules.users import UserManager

from ..exceptions import IrisAnalysisUrlNotFoundError
from ..model import IrisUrlExpansion, UrlExpansionStatus
from ..repositories import IrisIndicatorRepository, IrisUrlExpansionRepository
from ..services.enrichment.policy import RATE_LIMITER, expiry_after, is_fresh
from ..services.enrichment.url_expander import expand_url
from .analysis import IrisManager

logger = logging.getLogger(__name__)

#: Nombre del proveedor en el limitador: aquí el «proveedor» son las webs de
#: los enlaces, y el cupo protege a la instalación de lanzar demasiadas.
_PROVIDER = "url_expansion"

#: Una expansión ``pending`` o ``running`` más vieja se da por perdida (el
#: worker se cayó) y se puede volver a pedir.
_STALE_AFTER = timedelta(minutes=10)

#: Tiempo máximo del job en la cola, en segundos.
_JOB_TIMEOUT_SECONDS = 300


def _url_hash(url: str) -> str:
    """Huella con que se guarda una URL: la del índice de IOCs, en minúsculas.

    Args:
        url: URL.

    Returns:
        str: SHA-256 hex de la URL en minúsculas.
    """
    return hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()


def _serialize(expansion: Optional[IrisUrlExpansion], url: str, status: Optional[str] = None) -> Dict[str, Any]:
    """Serializa una expansión (o su ausencia).

    Args:
        expansion: La expansión, o ``None`` si nunca se pidió.
        url: URL a la que se refiere.
        status: Estado que se enseña en lugar del guardado (``rate_limited``,
            ``disabled``). Por defecto ``None``: el guardado, o
            ``not_requested`` si no hay expansión.

    Returns:
        dict: ``url``, ``status``, ``hops``, ``finalUrl``, ``finalDomain``,
            ``finalStatus``, ``pageTitle``, ``contentType``,
            ``isDomainChanged``, ``requestedAt`` y ``fetchedAt``.
    """
    if expansion is None:
        return {"url": url, "status": status or "not_requested", "hops": [], "finalUrl": None,
                "finalDomain": None, "finalStatus": None, "pageTitle": None, "contentType": None,
                "isDomainChanged": None, "requestedAt": None, "fetchedAt": None}
    return {
        "url": expansion.url,
        "status": status or expansion.status,
        "hops": list(expansion.hops or []),
        "finalUrl": expansion.final_url,
        "finalDomain": expansion.final_domain,
        "finalStatus": expansion.final_status,
        "pageTitle": expansion.page_title,
        "contentType": expansion.content_type,
        "isDomainChanged": expansion.is_domain_changed,
        "requestedAt": isoformat_utc(expansion.requested_at),
        "fetchedAt": isoformat_utc(expansion.fetched_at),
    }


def _run_url_expansion(expansion_id: int) -> None:
    """Cuerpo del job: sigue la URL y guarda los saltos y el destino.

    Un segundo envío del mismo job (la outbox entrega al menos una vez) no
    hace nada: solo sigue la URL quien la reclama en ``pending``.

    Args:
        expansion_id: Expansión a seguir.
    """
    with job_context():
        with UnitOfWork() as uow:
            repo = IrisUrlExpansionRepository(uow)
            if not repo.claim_for_run(expansion_id):
                return
            url = repo.get_by_id(expansion_id).url
        enrichment = CR.iris_enrichment_config()
        config = CR.iris_url_expansion_config()
        try:
            result = expand_url(url, max_redirects=config.max_redirects,
                                timeout_seconds=enrichment.timeout_seconds, max_bytes=config.max_body_bytes)
        except Exception as e:
            logger.error(f"Fallo siguiendo la URL de la expansión {expansion_id}: {e}", exc_info=True)
            result = None
        now = utcnow_naive()
        with UnitOfWork() as uow:
            expansion = IrisUrlExpansionRepository(uow).get_by_id(expansion_id)
            if expansion is None:
                return
            has_final = result is not None and result.final_url is not None
            expansion.status = (UrlExpansionStatus.DONE if has_final else UrlExpansionStatus.UNAVAILABLE).value
            expansion.hops = list(result.hops) if result else None
            expansion.final_url = result.final_url if result else None
            expansion.final_domain = result.final_domain if result else None
            expansion.final_status = result.final_status if result else None
            expansion.page_title = result.page_title if result else None
            expansion.content_type = (result.content_type or "")[:120] or None if result else None
            expansion.is_domain_changed = result.is_domain_changed if result else None
            expansion.fetched_at = now
            expansion.expires_at = expiry_after(timedelta(hours=config.ttl_hours), now)


class IrisUrlExpansionManager(TaskTrackingMixin):
    """Expansión bajo demanda de las URLs de un análisis."""

    EXTERNAL_ID_PREFIX = "iris-url-expansion:"
    TASK_CATEGORY = "iris.enrichment"

    def request_expansion(self, analysis_id: int, user_id: int, url: str) -> Dict[str, Any]:
        """Pide seguir una URL de un análisis del usuario.

        Si ya hay una expansión vigente o en marcha, la devuelve sin volver a
        encolar.

        Args:
            analysis_id: Análisis en el que aparece la URL.
            user_id: Usuario que la pide; debe ser el dueño del análisis.
            url: URL tal como aparece en los IOCs del análisis.

        Returns:
            dict: La expansión (ver ``_serialize``); ``status`` es ``pending``
                recién encolada, ``done``/``unavailable`` si ya estaba,
                ``rate_limited`` si no queda cupo y ``disabled`` si el
                enriquecimiento está apagado.

        Raises:
            IrisAnalysisNotFoundError: Si el análisis no existe o no es suyo.
            IrisAnalysisUrlNotFoundError: Si la URL no aparece en el análisis.
            SurfaceDisabledError: Si la superficie ``externalEnrichment`` está
                cerrada y el usuario no es el administrador principal.
        """
        IrisManager.assert_analysis_ownership(analysis_id, user_id)
        url = url.strip()
        if url.lower() not in build_repository(IrisIndicatorRepository).get_values_of_analysis(analysis_id, "url"):
            raise IrisAnalysisUrlNotFoundError(url)
        if not CR.iris_enrichment_config().enabled:
            return _serialize(None, url, "disabled")
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.EXTERNAL_ENRICHMENT, user_id)

        url_hash = _url_hash(url)
        existing = build_repository(IrisUrlExpansionRepository).get_by_user_and_hash(user_id, url_hash)
        now = utcnow_naive()
        if existing is not None:
            is_in_flight = (existing.status in (UrlExpansionStatus.PENDING.value, UrlExpansionStatus.RUNNING.value)
                            and now - existing.requested_at < _STALE_AFTER)
            if is_in_flight or is_fresh(existing.expires_at, now):
                return _serialize(existing, url)
        if not RATE_LIMITER.try_acquire(_PROVIDER, CR.iris_url_expansion_config().requests_per_minute):
            return _serialize(existing, url, "rate_limited")

        with UnitOfWork() as uow:
            repo = IrisUrlExpansionRepository(uow)
            expansion = repo.get_by_user_and_hash(user_id, url_hash) or repo.save(IrisUrlExpansion(
                user_id=user_id, url_sha256=url_hash, url=url, requested_at=now,
            ))
            expansion.status = UrlExpansionStatus.PENDING.value
            expansion.requested_at = now
            dispatch = TaskDispatchRepository(uow).save(build_dispatch(
                func=IrisUrlExpansionManager.execute_url_expansion,
                name=f"IrisUrlExpansion-{expansion.id}-{int(now.timestamp())}",
                category=self.TASK_CATEGORY,
                args=(expansion.id,),
                external_id=self.external_id_for(expansion.id),
                timeout=_JOB_TIMEOUT_SECONDS,
            ))
            dispatch_id = dispatch.id
            payload = _serialize(expansion, url)
            uow.commit_for_handoff()
        OutboxDispatcher.dispatch(dispatch_id, task_queue=self._task_queue)
        return payload

    @staticmethod
    def list_expansions(analysis_id: int, user_id: int) -> Dict[str, Any]:
        """Las URLs de un análisis con su expansión, si se pidió.

        Args:
            analysis_id: Análisis.
            user_id: Usuario; debe ser el dueño.

        Returns:
            dict: ``analysisId`` y ``expansions``, una por URL del análisis
                (``status: not_requested`` las que nunca se siguieron).

        Raises:
            IrisAnalysisNotFoundError: Si no existe o no es suyo.
        """
        IrisManager.assert_analysis_ownership(analysis_id, user_id)
        urls = build_repository(IrisIndicatorRepository).get_values_of_analysis(analysis_id, "url")
        by_hash = {
            expansion.url_sha256: expansion
            for expansion in build_repository(IrisUrlExpansionRepository).get_by_user_and_hashes(
                user_id, [_url_hash(url) for url in urls])
        }
        return {
            "analysisId": analysis_id,
            "expansions": [_serialize(by_hash.get(_url_hash(url)), url) for url in urls],
        }

    @staticmethod
    def execute_url_expansion(expansion_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            expansion_id: Expansión a seguir.
        """
        _run_url_expansion(expansion_id)
