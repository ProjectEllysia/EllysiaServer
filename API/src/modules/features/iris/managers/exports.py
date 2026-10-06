"""
IrisExportManager — inteligencia de Iris para un SOC: JSON versionado, STIX 2.1 y MISP.

Monta el documento neutro de ``services/exporters`` a partir de lo que Iris
conserva de un análisis o de una campaña —el índice de IOCs, las reglas que
penalizaron, la corrección del analista y la campaña— y lo traduce al formato
pedido. Parte del índice y no del correo original: el original se purga por
retención y el índice no, así que un análisis viejo se sigue pudiendo
exportar.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import src.modules.system.config_reading as CR
from src.modules.infrastructure import build_repository
from src.modules.shared import assert_owned, utcnow_naive

from ..exceptions import IrisAnalysisNotReadyError, IrisCampaignNotFoundError
from ..model import IrisAnalysis
from ..repositories import (
    IrisAnalystFeedbackRepository,
    IrisCampaignMemberRepository,
    IrisCampaignRepository,
    IrisIndicatorRepository,
    IrisRuleResultRepository,
)
from ..services.exporters import (
    ExportDocument,
    ExportedAnalysis,
    ExportedFinding,
    ExportedIndicator,
    ExportFormat,
    indicator_confidence,
    render_export,
    worst_verdict,
)
from .analysis import IrisManager
from .campaigns import IrisCampaignManager

#: Confianza ordinal de Iris → 0-100, para la confianza global del documento.
_DOCUMENT_CONFIDENCE = {"high": 85, "medium": 60, "low": 35}
_DEFAULT_DOCUMENT_CONFIDENCE = 35


def _exported_analysis(analysis: IrisAnalysis) -> ExportedAnalysis:
    """Resumen exportable de un análisis, con la última corrección del analista.

    Args:
        analysis: Análisis terminado.

    Returns:
        ExportedAnalysis: El resumen.
    """
    feedback = build_repository(IrisAnalystFeedbackRepository).latest_for_analysis(analysis.id)
    return ExportedAnalysis(
        analysis_id=analysis.id, title=analysis.title or "", verdict=analysis.verdict or "",
        confidence=analysis.confidence or "", received_at=analysis.created_at,
        analyst_label=feedback.label if feedback else "",
    )


def _exported_indicators(analyses: List[IrisAnalysis], validity_days: int) -> Tuple[ExportedIndicator, ...]:
    """IOCs de varios análisis, fusionados por tipo y valor.

    Un IOC que aparece en varios análisis se exporta una vez, con el peor
    veredicto y la mayor confianza de los análisis en que aparece, válido
    desde la primera vez que se vio hasta ``validity_days`` después de la
    última.

    Args:
        analyses: Análisis terminados.
        validity_days: Días de vigencia tras el último avistamiento.

    Returns:
        Tuple[ExportedIndicator, ...]: Ordenados por tipo y valor.
    """
    analyses_by_id = {analysis.id: analysis for analysis in analyses}
    pairs_by_analysis = build_repository(IrisIndicatorRepository).get_pairs_by_analysis_ids(list(analyses_by_id))
    sources_by_pair: Dict[Tuple[str, str], List[IrisAnalysis]] = {}
    for analysis_id, pairs in pairs_by_analysis.items():
        for pair in pairs:
            sources_by_pair.setdefault(pair, []).append(analyses_by_id[analysis_id])

    indicators = []
    for (kind, value), sources in sorted(sources_by_pair.items()):
        received = [source.created_at for source in sources]
        indicators.append(ExportedIndicator(
            kind=kind, value=value,
            confidence=max(indicator_confidence(source.verdict, source.confidence) for source in sources),
            verdict=worst_verdict([source.verdict for source in sources]),
            valid_from=min(received),
            valid_until=max(received) + timedelta(days=validity_days),
            analysis_ids=tuple(sorted(source.id for source in sources)),
        ))
    return tuple(indicators)


def _exported_findings(analyses: List[IrisAnalysis]) -> Tuple[ExportedFinding, ...]:
    """Reglas que penalizaron en el mensaje que decidió cada veredicto.

    Args:
        analyses: Análisis terminados.

    Returns:
        Tuple[ExportedFinding, ...]: Por análisis y, dentro de cada uno, en el
            orden del catálogo.
    """
    rule_repo = build_repository(IrisRuleResultRepository)
    findings = []
    for analysis in analyses:
        for rule in rule_repo.get_by_analysis(analysis.id, context_type=analysis.winning_context):
            if (rule.score or 0) >= 0:
                continue
            findings.append(ExportedFinding(
                rule_id=rule.rule_id or "", name=rule.rule_name, category=rule.category or "",
                severity=rule.severity or "", score=rule.score,
                mitre_techniques=tuple(rule.mitre_techniques or ()), analysis_id=analysis.id,
            ))
    return tuple(findings)


def _build_document(subject_kind: str, subject_id: int, title: str, analyses: List[IrisAnalysis],
                    campaign_id: Optional[int], campaign_label: str) -> ExportDocument:
    """Monta el documento neutro de una exportación.

    Args:
        subject_kind: ``analysis`` o ``campaign``.
        subject_id: Id de lo exportado.
        title: Nombre legible.
        analyses: Análisis terminados que entran; al menos uno.
        campaign_id: Campaña a la que pertenece, o ``None``.
        campaign_label: Su rótulo, o vacío.

    Returns:
        ExportDocument: El documento.
    """
    received = [analysis.created_at for analysis in analyses]
    detector_versions = sorted({analysis.detector_version for analysis in analyses if analysis.detector_version})
    return ExportDocument(
        subject_kind=subject_kind, subject_id=subject_id, title=title,
        verdict=worst_verdict([analysis.verdict for analysis in analyses]),
        confidence=max(_DOCUMENT_CONFIDENCE.get(analysis.confidence or "", _DEFAULT_DOCUMENT_CONFIDENCE)
                       for analysis in analyses),
        first_seen=min(received), last_seen=max(received),
        generated_at=utcnow_naive(), detector_version=", ".join(detector_versions),
        producer_version=CR.get_app_version(),
        analyses=tuple(_exported_analysis(analysis) for analysis in analyses),
        indicators=_exported_indicators(analyses, CR.iris_exports_config().indicator_validity_days),
        findings=_exported_findings(analyses),
        campaign_id=campaign_id, campaign_label=campaign_label,
    )


def _file_name(subject_kind: str, subject_id: int, export_format: ExportFormat) -> str:
    """Nombre del fichero descargado.

    Args:
        subject_kind: ``analysis`` o ``campaign``.
        subject_id: Id de lo exportado.
        export_format: Formato.

    Returns:
        str: ``iris-<tipo>-<id>.<formato>.json``.
    """
    return f"iris-{subject_kind}-{subject_id}.{export_format.value}.json"


class IrisExportManager:
    """Exportación de indicadores y hallazgos de Iris."""

    @staticmethod
    def export_analysis(analysis_id: int, user_id: int, export_format: str,
                        is_defanged: bool = True) -> Tuple[Dict[str, Any], str]:
        """Exporta un análisis terminado.

        Args:
            analysis_id: Análisis.
            user_id: Quien exporta; debe ser su dueño.
            export_format: ``json``, ``stix`` o ``misp`` (``ExportFormat``).
            is_defanged: Solo para ``json``: desactivar los valores. Por
                defecto ``True``.

        Returns:
            Tuple[dict, str]: El documento en el formato pedido y el nombre del
                fichero con que se descarga.

        Raises:
            IrisAnalysisNotFoundError: Si no existe o no es suyo.
            IrisAnalysisNotReadyError: Si aún no ha terminado.
        """
        analysis = IrisManager.assert_analysis_ownership(analysis_id, user_id)
        if analysis.status != "finished":
            raise IrisAnalysisNotReadyError(analysis_id, analysis.status)
        campaign = IrisCampaignManager.get_campaign_of_analysis(analysis_id)
        document = _build_document(
            "analysis", analysis.id, analysis.title or f"Análisis {analysis.id}", [analysis],
            campaign["campaignId"] if campaign else None, (campaign or {}).get("label") or "",
        )
        format_value = ExportFormat(export_format)
        return render_export(document, format_value, is_defanged), _file_name("analysis", analysis.id, format_value)

    @staticmethod
    def export_campaign(campaign_id: int, user_id: int, export_format: str,
                        is_defanged: bool = True) -> Tuple[Dict[str, Any], str]:
        """Exporta una campaña entera: todos sus mensajes en un solo documento.

        Args:
            campaign_id: Campaña.
            user_id: Quien exporta; debe ser su dueño.
            export_format: ``json``, ``stix`` o ``misp`` (``ExportFormat``).
            is_defanged: Solo para ``json``: desactivar los valores. Por
                defecto ``True``.

        Returns:
            Tuple[dict, str]: El documento y el nombre del fichero.

        Raises:
            IrisCampaignNotFoundError: Si no existe, no es suya o ya no tiene
                mensajes suficientes para ser una campaña.
        """
        campaign = assert_owned(IrisCampaignRepository, campaign_id, user_id, IrisCampaignNotFoundError)
        members = build_repository(IrisCampaignMemberRepository).get_by_campaign(campaign.id)
        analyses = [member.analysis for member in members if member.analysis.status == "finished"]
        if len(analyses) < 2:
            raise IrisCampaignNotFoundError(campaign_id)
        document = _build_document(
            "campaign", campaign.id, campaign.label or f"Campaña {campaign.id}", analyses,
            campaign.id, campaign.label or "",
        )
        format_value = ExportFormat(export_format)
        return render_export(document, format_value, is_defanged), _file_name("campaign", campaign.id, format_value)
