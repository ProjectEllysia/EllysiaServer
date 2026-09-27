"""
IrisEnrichmentManager — lo que se sabe de un indicador preguntando fuera.

Todas las consultas siguen el mismo camino:

1. El indicador tiene que estar en el índice de IOCs del usuario: Iris no hace
   de proxy de consultas arbitrarias.
2. Si el enriquecimiento está apagado en la configuración, responde
   ``disabled`` sin hacer red.
3. La superficie ``externalEnrichment`` de ``general.launch`` tiene que estar
   abierta (el administrador principal está exento, como en el resto de
   superficies).
4. Una respuesta en caché que no ha caducado se devuelve tal cual.
5. Si el proveedor no tiene cupo este minuto, responde ``rate_limited``.
6. Si no, se consulta y se guarda, también cuando el servicio no responde
   (``unavailable``, con una caducidad corta): así un registro caído no se
   golpea en cada petición.

Nada de lo que devuelve cambia ningún veredicto.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Dict, List, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.users import UserManager

from ..exceptions import IrisIndicatorNotFoundError
from ..model import EnrichmentStatus, IrisDomainCache, IrisThreatIntelResult, ThreatIntelVerdict
from ..repositories import IrisDomainCacheRepository, IrisIndicatorRepository, IrisThreatIntelResultRepository
from ..services.enrichment.policy import RATE_LIMITER, expiry_after, is_fresh
from ..services.enrichment.rdap import lookup_domain
from ..services.enrichment.threat_intel import ThreatIntelFinding, registered_adapters, worst_verdict
from ..services.indicators import refang
from ..services.text import registrable_domain

#: Nombre del proveedor RDAP en el limitador.
_RDAP_PROVIDER = "rdap"

#: Tipos de indicador por los que se puede preguntar la reputación. Las
#: direcciones de correo no: los proveedores no las catalogan, y mandarlas
#: sería enviar datos personales a cambio de nada.
_REPUTATION_KINDS = ("domain", "url", "ip", "hash")


def _assert_indicator_of_user(user_id: int, kind: str, value: str) -> None:
    """Comprueba que el usuario ya tiene ese indicador en alguno de sus análisis.

    Args:
        user_id: Usuario.
        kind: ``IrisIndicator.kind``.
        value: Valor normalizado.

    Raises:
        IrisIndicatorNotFoundError: Si no lo tiene.
    """
    if not build_repository(IrisIndicatorRepository).exists_for_user(user_id, kind, value):
        raise IrisIndicatorNotFoundError(value)


def _domain_context(domain: str, entry: Optional[IrisDomainCache], status: str,
                    is_cached: bool) -> Dict[str, Any]:
    """Serializa el contexto de un dominio.

    Args:
        domain: Dominio pedido.
        entry: Entrada de caché con los datos, o ``None`` si no los hay.
        status: ``EnrichmentStatus``.
        is_cached: Si la respuesta viene de la caché.

    Returns:
        dict: ``domain``, ``registrableDomain``, ``status``, ``cached``,
            ``registeredAt``, ``ageDays``, ``isRecentlyRegistered``,
            ``registryExpiresAt``, ``registrar``, ``registryStatus``,
            ``nameservers``, ``address``, ``networkName``, ``country``,
            ``asn``, ``error`` y ``fetchedAt``. Sin datos, todo salvo
            ``domain``, ``status`` y ``cached`` va a ``None`` o vacío.
    """
    has_data = entry is not None and entry.status == EnrichmentStatus.OK.value
    age_days = None
    if has_data and entry.registered_at is not None:
        age_days = max(0, (utcnow_naive() - entry.registered_at).days)
    return {
        "domain": domain,
        "registrableDomain": entry.domain if entry is not None else registrable_domain(domain) or domain,
        "status": status,
        "cached": is_cached,
        "registeredAt": isoformat_utc(entry.registered_at) if has_data else None,
        "ageDays": age_days,
        "isRecentlyRegistered": age_days is not None and age_days < CR.iris_rdap_config().recent_domain_days,
        "registryExpiresAt": isoformat_utc(entry.registry_expires_at) if has_data else None,
        "registrar": entry.registrar if has_data else None,
        "registryStatus": list(entry.registry_status or []) if has_data else [],
        "nameservers": list(entry.nameservers or []) if has_data else [],
        "address": entry.address if has_data else None,
        "networkName": entry.network_name if has_data else None,
        "country": entry.country if has_data else None,
        "asn": entry.asn if has_data else None,
        "error": entry.error if entry is not None and not has_data else None,
        "fetchedAt": isoformat_utc(entry.fetched_at) if entry is not None else None,
    }


def _provider_result(provider: str, verdict: str, detail: Optional[dict], error: Optional[str],
                     checked_at, is_cached: bool) -> Dict[str, Any]:
    """Serializa lo que dijo un proveedor.

    Args:
        provider: Nombre del proveedor.
        verdict: ``ThreatIntelVerdict``, o ``rate_limited`` si no se preguntó
            por falta de cupo.
        detail: Detalle del proveedor, o ``None``.
        error: Motivo si no hubo veredicto, o ``None``.
        checked_at: Cuándo se consultó, o ``None``.
        is_cached: Si viene de la caché.

    Returns:
        dict: ``provider``, ``verdict``, ``detail``, ``error``, ``checkedAt`` y
            ``cached``.
    """
    return {"provider": provider, "verdict": verdict, "detail": detail or {}, "error": error,
            "checkedAt": isoformat_utc(checked_at) if checked_at else None, "cached": is_cached}


def _query_providers(adapters: List[Any], kind: str, value: str, timeout_seconds: float,
                     max_bytes: int) -> List[ThreatIntelFinding]:
    """Pregunta a varios proveedores a la vez.

    En paralelo para que la espera sea la del más lento y no la suma. Solo
    hacen red: la base de datos se toca después, en el hilo de la petición.

    Args:
        adapters: Adaptadores a consultar.
        kind: Tipo de indicador.
        value: El indicador.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes que se leen como mucho de cada respuesta.

    Returns:
        List[ThreatIntelFinding]: Un resultado por adaptador, en el mismo orden.
    """
    if not adapters:
        return []
    with ThreadPoolExecutor(max_workers=len(adapters)) as pool:
        futures = [
            pool.submit(adapter.lookup, kind, value, CR.get_iris_threat_intel_key(adapter.NAME),
                        timeout_seconds, max_bytes)
            for adapter in adapters
        ]
        return [future.result() for future in futures]


class IrisEnrichmentManager:
    """Consultas bajo demanda sobre los indicadores de un usuario."""

    @staticmethod
    def get_domain_context(domain: str, user_id: int) -> Dict[str, Any]:
        """Edad, registrador, red, país y sistema autónomo de un dominio.

        La consulta se hace en la propia petición: son dos peticiones RDAP
        acotadas por ``timeoutSeconds``, y quien pregunta está esperando la
        respuesta.

        Args:
            domain: Dominio tal como lo escribió el usuario (se admite
                desactivado, ``evil[.]example``).
            user_id: Usuario que pregunta; el dominio tiene que estar en su
                índice de IOCs.

        Returns:
            dict: Ver ``_domain_context``.

        Raises:
            IrisIndicatorNotFoundError: Si el dominio no aparece en ninguno de
                sus análisis.
            SurfaceDisabledError: Si la superficie ``externalEnrichment`` está
                cerrada y el usuario no es el administrador principal.
        """
        normalized = refang(domain).strip(".")
        _assert_indicator_of_user(user_id, "domain", normalized)
        enrichment = CR.iris_enrichment_config()
        if not enrichment.enabled:
            return _domain_context(normalized, None, EnrichmentStatus.DISABLED.value, False)
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.EXTERNAL_ENRICHMENT, user_id)

        registrable = registrable_domain(normalized) or normalized
        cached = build_repository(IrisDomainCacheRepository).get_by_domain(registrable)
        if cached is not None and is_fresh(cached.expires_at):
            return _domain_context(normalized, cached, cached.status, True)

        rdap = CR.iris_rdap_config()
        if not RATE_LIMITER.try_acquire(_RDAP_PROVIDER, rdap.requests_per_minute):
            return _domain_context(normalized, None, EnrichmentStatus.RATE_LIMITED.value, False)

        context = lookup_domain(registrable, base_url=rdap.base_url, timeout_seconds=enrichment.timeout_seconds,
                                max_bytes=enrichment.max_response_bytes)
        now = utcnow_naive()
        is_ok = context.registration is not None
        with UnitOfWork() as uow:
            repo = IrisDomainCacheRepository(uow)
            entry = repo.get_by_domain(registrable) or repo.save(IrisDomainCache(
                domain=registrable, status=EnrichmentStatus.UNAVAILABLE.value, fetched_at=now, expires_at=now,
            ))
            registration, network = context.registration, context.network
            entry.status = (EnrichmentStatus.OK if is_ok else EnrichmentStatus.UNAVAILABLE).value
            entry.registered_at = registration.registered_at if is_ok else None
            entry.registry_expires_at = registration.expires_at if is_ok else None
            entry.registrar = (registration.registrar or "")[:255] or None if is_ok else None
            entry.registry_status = list(registration.statuses) or None if is_ok else None
            entry.nameservers = list(registration.nameservers) or None if is_ok else None
            entry.address = network.address if network else None
            entry.network_name = (network.name or "")[:255] or None if network else None
            entry.country = network.country if network else None
            entry.asn = network.asn if network else None
            entry.error = None if is_ok else (context.error or "unavailable")[:64]
            entry.fetched_at = now
            entry.expires_at = expiry_after(
                timedelta(hours=rdap.ttl_hours) if is_ok else timedelta(minutes=rdap.negative_ttl_minutes), now,
            )
            return _domain_context(normalized, entry, entry.status, False)

    @staticmethod
    def get_reputation(kind: str, value: str, user_id: int) -> Dict[str, Any]:
        """Qué dicen los proveedores de reputación configurados de un indicador.

        Solo se envía el indicador y la clave de cada proveedor; nunca el
        correo. Cada proveedor se consulta en paralelo en la propia petición,
        acotado por ``timeoutSeconds``.

        Args:
            kind: ``domain``, ``url``, ``ip`` o ``hash``.
            value: El indicador (se admite desactivado).
            user_id: Usuario que pregunta; el indicador tiene que estar en su
                índice de IOCs.

        Returns:
            dict: ``kind``, ``value``, ``verdict`` (el más grave de los
                proveedores que respondieron, o ``unavailable``), ``status``
                (``ok``, ``disabled`` o ``not_configured``) y ``providers``
                (uno por proveedor configurado, ver ``_provider_result``).

        Raises:
            IrisIndicatorNotFoundError: Si el indicador no aparece en sus
                análisis o su tipo no admite consulta.
            SurfaceDisabledError: Si la superficie ``externalEnrichment`` está
                cerrada y el usuario no es el administrador principal.
        """
        normalized = refang(value) if kind != "hash" else value.strip().lower()
        if kind not in _REPUTATION_KINDS:
            raise IrisIndicatorNotFoundError(value)
        _assert_indicator_of_user(user_id, kind, normalized.lower())
        base = {"kind": kind, "value": normalized, "verdict": ThreatIntelVerdict.UNAVAILABLE.value,
                "providers": []}
        enrichment = CR.iris_enrichment_config()
        if not enrichment.enabled:
            return {**base, "status": EnrichmentStatus.DISABLED.value}
        UserManager().assert_launch_surface_enabled(CR.LaunchSurface.EXTERNAL_ENRICHMENT, user_id)

        config = CR.iris_threat_intel_config()
        adapters = [
            adapter for adapter in registered_adapters()
            if kind in adapter.SUPPORTED_KINDS and config.is_provider_enabled(adapter.NAME)
            and CR.get_iris_threat_intel_key(adapter.NAME)
        ]
        if not adapters:
            return {**base, "status": "not_configured"}

        value_hash = hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()
        cache_repo = build_repository(IrisThreatIntelResultRepository)
        results_by_provider: Dict[str, Dict[str, Any]] = {}
        to_query = []
        for adapter in adapters:
            cached = cache_repo.get_entry(adapter.NAME, kind, value_hash)
            if cached is not None and is_fresh(cached.expires_at):
                results_by_provider[adapter.NAME] = _provider_result(
                    adapter.NAME, cached.verdict, cached.detail, cached.error, cached.checked_at, True)
            elif not RATE_LIMITER.try_acquire(f"threat_intel:{adapter.NAME}", config.requests_per_minute(adapter.NAME)):
                results_by_provider[adapter.NAME] = _provider_result(
                    adapter.NAME, EnrichmentStatus.RATE_LIMITED.value, None, None, None, False)
            else:
                to_query.append(adapter)

        findings = _query_providers(to_query, kind, normalized, enrichment.timeout_seconds,
                                    enrichment.max_response_bytes)
        now = utcnow_naive()
        with UnitOfWork() as uow:
            repo = IrisThreatIntelResultRepository(uow)
            for finding in findings:
                is_answer = finding.verdict != ThreatIntelVerdict.UNAVAILABLE
                entry = repo.get_entry(finding.provider, kind, value_hash) or repo.save(IrisThreatIntelResult(
                    provider=finding.provider, kind=kind, value_sha256=value_hash, value=normalized,
                    verdict=finding.verdict.value, checked_at=now, expires_at=now,
                ))
                entry.verdict = finding.verdict.value
                entry.detail = dict(finding.detail) or None
                entry.error = (finding.error or "")[:64] or None
                entry.checked_at = now
                entry.expires_at = expiry_after(
                    timedelta(hours=config.ttl_hours) if is_answer else timedelta(minutes=config.negative_ttl_minutes),
                    now,
                )
                results_by_provider[finding.provider] = _provider_result(
                    finding.provider, entry.verdict, entry.detail, entry.error, now, False)

        providers = [results_by_provider[adapter.NAME] for adapter in adapters]
        verdicts = [ThreatIntelVerdict(result["verdict"]) for result in providers
                    if result["verdict"] in {verdict.value for verdict in ThreatIntelVerdict}]
        return {**base, "status": EnrichmentStatus.OK.value, "verdict": worst_verdict(verdicts).value,
                "providers": providers}
