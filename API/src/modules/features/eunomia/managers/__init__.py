"""Managers del módulo Eunomia."""

from .catalog import CatalogManager
from .assessments import EunomiaAssessmentManager
from .documents import EunomiaDocumentManager
from .evidence import EunomiaEvidenceManager
from .frameworks import EunomiaFrameworkManager
from .registers import EunomiaRegisterManager
from .templates import EunomiaTemplateManager

__all__ = ["CatalogManager", "EunomiaDocumentManager", "EunomiaAssessmentManager", "EunomiaEvidenceManager", "EunomiaFrameworkManager",
           "EunomiaRegisterManager", "EunomiaTemplateManager"]
