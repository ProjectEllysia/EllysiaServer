"""
IrisTenantManager — inteligencia de Iris compartida dentro de una organización.

Tres piezas, cada una con su dueño:

- **La política** (``IrisTenantProfile``) la decide el dueño de la
  organización: si se comparte y qué dominios y marcas propios se vigilan.
- **El consentimiento** (``IrisTenantConsent``) lo da cada miembro: sin él, lo
  suyo no entra en lo compartido y él no ve lo agregado.
- **Lo compartido** se calcula al leer, con ``services/tenant.py``: agregados
  anonimizados de los miembros que consienten y siguen en la organización,
  solo si superan el mínimo de miembros distintos.

Nunca cruza entre miembros un correo, un análisis, una dirección ni un id de
miembro, y nunca cruza nada entre organizaciones.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import src.modules.system.config_reading as CR
from src.modules.accounts import OrganizationManager
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc, utcnow_naive

from ..exceptions import IrisInvalidInputError, IrisNotInOrganizationError, IrisTenantOwnerRequiredError
from ..model import IrisTenantConsent, IrisTenantProfile
from ..repositories import (
    IrisCommunicationEdgeRepository,
    IrisIndicatorRepository,
    IrisTenantConsentRepository,
    IrisTenantProfileRepository,
)
from ..services.tenant import (
    find_imitated_protected,
    is_shareable_sender_domain,
    normalize_protected_brands,
    normalize_protected_domains,
)

#: Tipos de indicador que se comparten. Las IPs no (la de entrada suele ser la
#: del proveedor de correo, compartida por todo) ni las direcciones (son
#: personas).
_SHARED_KINDS = ["domain", "url", "hash"]


def _organization_of(user_id: int) -> Dict[str, Any]:
    """La organización del usuario.

    Args:
        user_id: Usuario.

    Returns:
        dict: La de ``OrganizationManager.get_mine`` (``id``, ``name``,
            ``isOwner``…).

    Raises:
        IrisNotInOrganizationError: Si no pertenece a ninguna.
    """
    organization = OrganizationManager().get_mine(user_id)
    if organization is None:
        raise IrisNotInOrganizationError()
    return organization


def _contributing_members(organization_id: int) -> List[int]:
    """Miembros cuyo consentimiento vale hoy en una organización.

    Un consentimiento se dio en una organización concreta: si el miembro se
    fue después, deja de contar aunque su fila siga.

    Args:
        organization_id: Organización.

    Returns:
        List[int]: Ids de los miembros que aportan.
    """
    organization_manager = OrganizationManager()
    return [
        user_id for user_id in build_repository(IrisTenantConsentRepository).get_active_user_ids(organization_id)
        if (organization_manager.get_mine(user_id) or {}).get("id") == organization_id
    ]


def _has_consented(user_id: int, organization_id: int) -> bool:
    """Si el usuario tiene vigente su consentimiento en esta organización.

    Args:
        user_id: Usuario.
        organization_id: Organización a la que pertenece hoy.

    Returns:
        bool: ``True`` si lo dio aquí y no lo ha retirado.
    """
    consent = build_repository(IrisTenantConsentRepository).get_by_user(user_id)
    return consent is not None and consent.revoked_at is None and consent.organization_id == organization_id


def _profile_dict(profile: Optional[IrisTenantProfile]) -> Dict[str, Any]:
    """La política, o la de por defecto si nunca se configuró.

    Args:
        profile: Política guardada, o ``None``.

    Returns:
        dict: ``sharingEnabled``, ``protectedDomains``, ``protectedBrands`` y
            ``updatedAt``.
    """
    if profile is None:
        return {"sharingEnabled": False, "protectedDomains": [], "protectedBrands": [], "updatedAt": None}
    return {
        "sharingEnabled": profile.is_sharing_enabled,
        "protectedDomains": list(profile.protected_domains or []),
        "protectedBrands": list(profile.protected_brands or []),
        "updatedAt": isoformat_utc(profile.updated_at),
    }


def _invalid_input(text: str) -> IrisInvalidInputError:
    """Error de validación cuyo mensaje se enseña tal cual al usuario.

    Args:
        text: Qué falló, en castellano.

    Returns:
        IrisInvalidInputError: Con ``user_message`` igual a ``text``.
    """
    return IrisInvalidInputError(text, user_message=text)


class IrisTenantManager:
    """Política, consentimiento y agregados de la inteligencia de una organización."""

    @staticmethod
    def get_intel(user_id: int) -> Dict[str, Any]:
        """Lo que el usuario puede ver de la inteligencia de su organización.

        Los agregados solo se calculan si la organización comparte y el
        usuario ha consentido; si no, van vacíos y el resto dice por qué.

        Args:
            user_id: Usuario.

        Returns:
            dict: ``organization`` (``id``, ``name``), ``isOwner``,
                ``hasConsented``, ``contributingMembers``, ``minMembers``,
                ``windowDays``, la política (ver ``_profile_dict``),
                ``sharedIndicators`` (``kind``, ``value``, ``memberCount``,
                ``analysisCount``, ``firstSeenAt``, ``lastSeenAt``,
                ``imitatesProtected``) y ``frequentDomains`` (``domain``,
                ``memberCount``, ``legitimateMessages``).

        Raises:
            IrisNotInOrganizationError: Si no pertenece a ninguna.
        """
        organization = _organization_of(user_id)
        config = CR.iris_tenant_config()
        profile = build_repository(IrisTenantProfileRepository).get_by_organization(organization["id"])
        policy = _profile_dict(profile)
        has_consented = _has_consented(user_id, organization["id"])
        members = _contributing_members(organization["id"])
        base = {
            "organization": {"id": organization["id"], "name": organization["name"]},
            "isOwner": bool(organization.get("isOwner")),
            "hasConsented": has_consented,
            "contributingMembers": len(members),
            "minMembers": config.min_members,
            "windowDays": config.window_days,
            **policy,
            "sharedIndicators": [],
            "frequentDomains": [],
        }
        if not policy["sharingEnabled"] or not has_consented:
            return base

        since = utcnow_naive() - timedelta(days=config.window_days)
        indicators = build_repository(IrisIndicatorRepository).aggregate_across_users(
            members, since, _SHARED_KINDS, config.min_members, config.max_items,
        )
        domains = build_repository(IrisCommunicationEdgeRepository).aggregate_sender_domains(
            members, config.min_members, config.max_items,
        )
        return {
            **base,
            "sharedIndicators": [
                {
                    "kind": kind, "value": value, "memberCount": member_count, "analysisCount": analysis_count,
                    "firstSeenAt": isoformat_utc(first_seen), "lastSeenAt": isoformat_utc(last_seen),
                    "imitatesProtected": find_imitated_protected(kind, value, policy["protectedDomains"]),
                }
                for kind, value, member_count, analysis_count, first_seen, last_seen in indicators
            ],
            "frequentDomains": [
                {"domain": domain, "memberCount": member_count, "legitimateMessages": messages}
                for domain, member_count, messages in domains if is_shareable_sender_domain(domain)
            ],
        }

    @staticmethod
    def update_policy(user_id: int, is_sharing_enabled: bool, protected_domains: List[str],
                      protected_brands: List[str]) -> Dict[str, Any]:
        """El dueño decide si se comparte y qué dominios y marcas se protegen.

        Args:
            user_id: Dueño de la organización.
            is_sharing_enabled: Si se comparte.
            protected_domains: Dominios propios a vigilar.
            protected_brands: Marcas propias a vigilar.

        Returns:
            dict: Lo mismo que ``get_intel``, ya con la política nueva.

        Raises:
            IrisNotInOrganizationError: Si no pertenece a ninguna.
            IrisTenantOwnerRequiredError: Si no es el dueño.
            IrisInvalidInputError: Si un dominio no es válido o hay demasiados.
        """
        organization = _organization_of(user_id)
        if not organization.get("isOwner"):
            raise IrisTenantOwnerRequiredError()
        try:
            domains = normalize_protected_domains(protected_domains)
            brands = normalize_protected_brands(protected_brands)
        except ValueError as e:
            raise _invalid_input(str(e)) from e
        with UnitOfWork() as uow:
            repo = IrisTenantProfileRepository(uow)
            profile = repo.get_by_organization(organization["id"]) or repo.save(IrisTenantProfile(
                organization_id=organization["id"], protected_domains=[], protected_brands=[],
            ))
            profile.is_sharing_enabled = is_sharing_enabled
            profile.protected_domains = domains
            profile.protected_brands = brands
            profile.changed_by_user_id = user_id
            profile.updated_at = utcnow_naive()
        return IrisTenantManager.get_intel(user_id)

    @staticmethod
    def set_consent(user_id: int, has_consented: bool) -> Dict[str, Any]:
        """Un miembro da o retira su consentimiento para aportar a lo compartido.

        Retirarlo lo saca de todos los agregados al momento.

        Args:
            user_id: Miembro.
            has_consented: ``True`` para darlo, ``False`` para retirarlo.

        Returns:
            dict: Lo mismo que ``get_intel``.

        Raises:
            IrisNotInOrganizationError: Si no pertenece a ninguna.
        """
        organization = _organization_of(user_id)
        now = utcnow_naive()
        with UnitOfWork() as uow:
            repo = IrisTenantConsentRepository(uow)
            consent = repo.get_by_user(user_id)
            if has_consented:
                if consent is None:
                    consent = repo.save(IrisTenantConsent(user_id=user_id, organization_id=organization["id"],
                                                          consented_at=now))
                consent.organization_id = organization["id"]
                consent.consented_at = now
                consent.revoked_at = None
            elif consent is not None and consent.revoked_at is None:
                consent.revoked_at = now
        return IrisTenantManager.get_intel(user_id)

    @staticmethod
    def get_sightings(user_id: int, indicator_pairs: List[Tuple[str, str]]) -> Optional[Dict[str, Any]]:
        """Cuántos miembros de la organización han visto los indicadores de un análisis.

        Es lo que el informe de un análisis enseña como «este dominio lo han
        recibido N miembros de tu organización». Solo cuenta indicadores que
        superan el mínimo de miembros distintos, igual que lo compartido.

        Args:
            user_id: Dueño del análisis.
            indicator_pairs: Pares ``(kind, value)`` del análisis.

        Returns:
            Optional[dict]: ``minMembers`` e ``indicators`` (``kind``,
                ``value``, ``memberCount``); ``None`` si el usuario no está
                en una organización que comparte, no ha consentido, o ningún
                indicador llega al mínimo.
        """
        organization = OrganizationManager().get_mine(user_id)
        if organization is None or not _has_consented(user_id, organization["id"]):
            return None
        profile = build_repository(IrisTenantProfileRepository).get_by_organization(organization["id"])
        if profile is None or not profile.is_sharing_enabled:
            return None
        config = CR.iris_tenant_config()
        pairs = [(kind, value) for kind, value in indicator_pairs if kind in _SHARED_KINDS]
        counts = build_repository(IrisIndicatorRepository).count_users_per_indicator(
            _contributing_members(organization["id"]), utcnow_naive() - timedelta(days=config.window_days), pairs,
        )
        seen = [
            {"kind": kind, "value": value, "memberCount": count}
            for (kind, value), count in sorted(counts.items()) if count >= config.min_members
        ]
        return {"minMembers": config.min_members, "indicators": seen} if seen else None
