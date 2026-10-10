"""
src.modules.features.aegis - Módulo de concienciación en ciberseguridad

Exponente:
    - AegisManager: Generación de píldoras
    - Modelos: AegisDocument, AegisTip, Topic
    - Endpoints: aegis_bp
"""

from src.modules.system.taskqueue import QueueRegistry

from .model import (
    AegisDocument,
    AegisDocumentAlert,
    AegisQuizQuestion,
    AegisTip,
    Campaign,
    CampaignAnswer,
    CampaignRecipient,
    DistributionList,
    Recipient,
    Topic,
)
from .managers import AegisManager, CampaignManager
from .endpoints import aegis_blp
from src.modules.features.eunomia import EvidenceProviderRegistry
from .services.compliance_evidence import CONTROLS as _AWARENESS_CONTROLS, summarize_awareness

# Registro de las categorías de cola de este módulo (OCP).
QueueRegistry.register("aegis.generate", "aegis.campaign")

EvidenceProviderRegistry.register(
    "aegis.awareness", name="Formación y concienciación", controls=_AWARENESS_CONTROLS,
    collect=lambda owner_user_id, framework_key, identifier: summarize_awareness(
        CampaignManager(user=None).get_awareness_summary(owner_user_id)),
)

__all__ = [
    "AegisDocument",
    "AegisDocumentAlert",
    "AegisQuizQuestion",
    "AegisTip",
    "Campaign",
    "CampaignAnswer",
    "CampaignRecipient",
    "DistributionList",
    "Recipient",
    "Topic",
    "AegisManager",
    "CampaignManager",
    "aegis_blp",
]