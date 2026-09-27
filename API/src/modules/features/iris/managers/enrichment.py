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

from datetime import timedelta
from typing import Any, Dict, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc, utcnow_naive
from src.modules.users import UserManager

from ..exceptions import IrisIndicatorNotFoundError
from ..model import EnrichmentStatus, IrisDomainCache
from ..repositories import IrisDomainCacheRepository, IrisIndicatorRepository
from ..services.enrichment.policy import RATE_LIMITER, expiry_after, is_fresh
from ..services.enrichment.rdap import lookup_domain
from ..services.indicators import refang
from ..services.text import registrable_domain

#: Nombre del proveedor RDAP en el limitador.
_RDAP_PROVIDER = "rdap"


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
