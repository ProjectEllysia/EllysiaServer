"""
IrisCampaignManager — campañas: los análisis de un usuario que comparten origen.

La agrupación ocurre sola al terminar cada análisis (``services/campaigns.py``,
llamado desde ``managers/analysis.py``). Este manager es la lectura: el listado
de campañas con sus cifras, el detalle de una campaña con sus mensajes y los
indicadores que comparten, y el resumen que acompaña al informe de un análisis
(«otros N mensajes de esta campaña»).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.modules.infrastructure import build_repository
from src.modules.shared import assert_owned, isoformat_utc

from ..exceptions import IrisCampaignNotFoundError
from ..model import IrisCampaign
from ..repositories import IrisCampaignMemberRepository, IrisCampaignRepository, IrisIndicatorRepository

#: Miembros mínimos para que un grupo se enseñe como campaña.
_MIN_CAMPAIGN_MEMBERS = 2


def _summary(campaign: IrisCampaign, analysis_count: int, message_count: int,
             first_seen, last_seen, verdicts: Dict[str, int]) -> Dict[str, Any]:
    """Serializa lo que enseña el listado de campañas.

    Args:
        campaign: La campaña.
        analysis_count: Análisis que la forman.
        message_count: Mensajes distintos (sin contar dos veces un reanálisis).
        first_seen: Recepción del análisis más antiguo.
        last_seen: Recepción del más reciente.
        verdicts: Análisis por veredicto.

    Returns:
        dict: ``campaignId``, ``label``, ``analysisCount``, ``messageCount``,
            ``firstSeenAt``, ``lastSeenAt`` y ``verdicts``.
    """
    return {
        "campaignId": campaign.id,
        "label": campaign.label,
        "analysisCount": analysis_count,
        "messageCount": message_count,
        "firstSeenAt": isoformat_utc(first_seen),
        "lastSeenAt": isoformat_utc(last_seen),
        "verdicts": verdicts,
    }


class IrisCampaignManager:
    """Consulta de las campañas de un usuario."""

    @staticmethod
    def list_campaigns(user_id: int, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """Campañas del usuario, de la que tuvo actividad más reciente a la que menos.

        Args:
            user_id: Dueño.
            page: Página, empezando en 1. Por defecto ``1``.
            per_page: Campañas por página. Por defecto ``20``.

        Returns:
            dict: ``campaigns`` (ver ``_summary``), ``total``, ``page`` y
                ``perPage``.
        """
        campaign_repo = build_repository(IrisCampaignRepository)
        rows, total = campaign_repo.get_page_for_user(user_id, page, per_page, _MIN_CAMPAIGN_MEMBERS)
        verdicts_by_campaign = campaign_repo.count_verdicts([row[0].id for row in rows])
        return {
            "campaigns": [
                _summary(campaign, analysis_count, message_count, first_seen, last_seen,
                         verdicts_by_campaign.get(campaign.id, {}))
                for campaign, analysis_count, message_count, first_seen, last_seen in rows
            ],
            "total": total,
            "page": page,
            "perPage": per_page,
        }

    @staticmethod
    def get_campaign(campaign_id: int, user_id: int) -> Dict[str, Any]:
        """Una campaña con sus mensajes y lo que comparten.

        Args:
            campaign_id: Campaña pedida.
            user_id: Usuario que la pide; debe ser su dueño.

        Returns:
            dict: Lo de ``_summary`` más ``analyses`` (del más reciente al más
                antiguo: ``analysisId``, ``title``, ``verdict``,
                ``totalScore``, ``receivedAt``, ``similarity`` y
                ``matchedSignals``), ``sharedIndicators`` (``kind``,
                ``value``, ``analysisCount``) y ``brands`` (marcas
                suplantadas por algún mensaje).

        Raises:
            IrisCampaignNotFoundError: Si no existe, no es suya o ya no tiene
                mensajes suficientes para ser una campaña.
        """
        campaign = assert_owned(IrisCampaignRepository, campaign_id, user_id, IrisCampaignNotFoundError)
        members = build_repository(IrisCampaignMemberRepository).get_by_campaign(campaign.id)
        if len(members) < _MIN_CAMPAIGN_MEMBERS:
            raise IrisCampaignNotFoundError(campaign_id)

        analyses = [member.analysis for member in members]
        verdicts: Dict[str, int] = {}
        for analysis in analyses:
            verdict_key = analysis.verdict or "unknown"
            verdicts[verdict_key] = verdicts.get(verdict_key, 0) + 1
        distinct_messages = {analysis.content_sha256 or f"id:{analysis.id}" for analysis in analyses}
        received_times = [analysis.created_at for analysis in analyses]
        brands = sorted({brand for analysis in analyses for brand in (analysis.impersonated_brands or [])})
        shared = build_repository(IrisIndicatorRepository).get_shared_in_campaign(campaign.id)
        return {
            **_summary(campaign, len(analyses), len(distinct_messages),
                       min(received_times), max(received_times), verdicts),
            "analyses": [
                {
                    "analysisId": member.analysis.id,
                    "title": member.analysis.title,
                    "verdict": member.analysis.verdict,
                    "totalScore": member.analysis.total_score,
                    "receivedAt": isoformat_utc(member.analysis.created_at),
                    "similarity": member.similarity,
                    "matchedSignals": list(member.matched_signals or []),
                }
                for member in members
            ],
            "sharedIndicators": [
                {"kind": kind, "value": value, "analysisCount": analysis_count}
                for kind, value, analysis_count in shared
            ],
            "brands": brands,
        }

    @staticmethod
    def get_campaign_of_analysis(analysis_id: int) -> Optional[Dict[str, Any]]:
        """La campaña de un análisis, para enseñarla junto a su informe.

        No comprueba la propiedad: quien la pide ya ha comprobado que el
        análisis es del usuario, y la campaña es siempre del dueño de sus
        análisis.

        Args:
            analysis_id: Análisis.

        Returns:
            Optional[dict]: ``campaignId``, ``label`` y ``relatedCount`` (los
                demás análisis de la campaña), o ``None`` si el análisis no
                está en ninguna campaña o esta ya no tiene otros mensajes.
        """
        member_repo = build_repository(IrisCampaignMemberRepository)
        member = member_repo.get_by_analysis(analysis_id)
        if member is None:
            return None
        member_count = member_repo.count_by_campaign(member.campaign_id)
        if member_count < _MIN_CAMPAIGN_MEMBERS:
            return None
        return {
            "campaignId": member.campaign_id,
            "label": member.campaign.label,
            "relatedCount": member_count - 1,
        }
