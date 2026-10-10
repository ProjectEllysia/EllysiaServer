"""Qué datos de un usuario entrega Eunomia en la exportación de sus datos."""

from src.modules.shared import ExportTable, owned_by, owned_through

from .model import (
    EunomiaAssessmentEvent,
    EunomiaControlAssessment,
    EunomiaDocument,
    EunomiaEvidence,
    EunomiaEvidenceLink,
    EunomiaFrameworkAdoption,
    EunomiaTemplateDraft,
)

#: Tablas de Eunomia que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    ExportTable("framework_adoptions", EunomiaFrameworkAdoption, owned_by(EunomiaFrameworkAdoption.owner_user_id)),
    ExportTable("control_assessments", EunomiaControlAssessment, owned_by(EunomiaControlAssessment.owner_user_id)),
    ExportTable("assessment_history", EunomiaAssessmentEvent, owned_by(EunomiaAssessmentEvent.owner_user_id)),
    ExportTable("documents", EunomiaDocument, owned_by(EunomiaDocument.user_id), frozenset({"filename"})),
    ExportTable("evidence", EunomiaEvidence, owned_by(EunomiaEvidence.owner_user_id)),
    ExportTable("template_drafts", EunomiaTemplateDraft, owned_by(EunomiaTemplateDraft.owner_user_id)),
    ExportTable(
        "evidence_links", EunomiaEvidenceLink,
        owned_through(EunomiaEvidenceLink.evidence_id, EunomiaEvidence.id, EunomiaEvidence.owner_user_id),
    ),
)
