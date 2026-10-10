"""Qué datos de un usuario entrega Eunomia en la exportación de sus datos."""

from src.modules.shared import ExportTable, owned_by

from .model import EunomiaAssessmentEvent, EunomiaControlAssessment, EunomiaFrameworkAdoption

#: Tablas de Eunomia que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    ExportTable("framework_adoptions", EunomiaFrameworkAdoption, owned_by(EunomiaFrameworkAdoption.owner_user_id)),
    ExportTable("control_assessments", EunomiaControlAssessment, owned_by(EunomiaControlAssessment.owner_user_id)),
    ExportTable("assessment_history", EunomiaAssessmentEvent, owned_by(EunomiaAssessmentEvent.owner_user_id)),
)
