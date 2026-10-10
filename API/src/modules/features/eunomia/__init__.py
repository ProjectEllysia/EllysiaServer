"""
src.modules.features.eunomia - Marcos de cumplimiento normativo (NIS2, RGPD y los que vengan)

Eunomia deja que una cuenta adopte marcos de cumplimiento, los recorra como un árbol de
controles de profundidad arbitraria, evalúe cada control y adjunte las evidencias que lo
demuestran.

Reglas que atraviesan todo el módulo:
    - Los datos son del **dueño efectivo**: el propio usuario o, si pertenece a una
      organización, el dueño de esa organización. Lo resuelve
      ``OrganizationManager.resolve_data_owner`` y ningún módulo lo repite a mano.
    - Los miembros de una organización evalúan controles y suben evidencias, pero no
      adoptan ni quitan marcos ni editan el perfil de empresa. La excepción a «la
      organización comparte plan, no datos» está descrita en el docstring de
      ``accounts.Organization``.
    - El catálogo de marcos son ficheros versionados e inmutables que viven en este
      paquete (``catalog/``); no son filas de base de datos. Lybra sigue siendo el dueño
      de las técnicas MITRE ATT&CK y de qué comprobación cubre qué control.

Exponente:
    - CatalogManager: el catálogo de marcos y el árbol de cada versión.
    - EunomiaFrameworkManager: marcos adoptados por el dueño efectivo de los datos.
    - EunomiaAssessmentManager: evaluar los controles de un marco adoptado.
    - Modelos: EunomiaFrameworkAdoption, EunomiaControlAssessment.
    - Endpoints: eunomia_blp.
    - EvidenceProviderRegistry / AutomaticEvidence: cómo otros módulos aportan evidencias solas.
    - Excepciones: EunomiaError.
"""

from src.modules.accounts import LimitKey, register_stock_counter
from src.modules.system.taskqueue import QueueRegistry
from src.modules.users import UserDataRegistry

from .data_export import EXPORT_TABLES
from .endpoints import eunomia_blp
from .managers import CatalogManager, EunomiaFrameworkManager
from .exceptions import EunomiaError
from .model import EunomiaControlAssessment, EunomiaEvidence, EunomiaFrameworkAdoption
from .repositories import EunomiaEvidenceRepository, EunomiaFrameworkAdoptionRepository
from .services.adoption_data import AdoptionDataRegistry
from .services.providers import AutomaticEvidence, EvidenceProviderRegistry
from .services.register_evidence import register_providers
from .services.assessment_data import count_assessments, purge_assessments
from .services.evidence_data import count_evidence, purge_evidence
from .services.user_data import export_evidence_files, purge_eunomia_data

# Cómo se cuentan los marcos adoptados para la cuota ``eunomia.frameworks``: solo los activos,
# sobre la bolsa de dueños que pide el motor de cuotas.
register_stock_counter(
    LimitKey.EUNOMIA_FRAMEWORKS,
    lambda session, user_ids: EunomiaFrameworkAdoptionRepository(session=session).count_active_for_owners(user_ids),
)

# Un registro con fichas demuestra los requisitos que lo exigen: un proveedor por tipo de registro.
register_providers()

# Los documentos de cumplimiento se generan en el worker, en su propia cola.
QueueRegistry.register("eunomia.report")

# Lo que cuelga de una adopción y hay que contar y purgar al quitar un marco.
AdoptionDataRegistry.register("assessments", count=count_assessments, purge=purge_assessments)
AdoptionDataRegistry.register("evidence", count=count_evidence, purge=purge_evidence)

# Cómo se cuenta el almacenamiento de evidencias para la cuota ``eunomia.evidence_storage``: suma
# del tamaño original (no del cifrado, para que la cifra sea la que el usuario entiende).
register_stock_counter(
    LimitKey.EUNOMIA_EVIDENCE_STORAGE,
    lambda session, user_ids: EunomiaEvidenceRepository(session=session).sum_size_for_owners(user_ids),
)

# Qué hace ``users`` con los datos de este módulo al borrar una cuenta o exportarlos.
UserDataRegistry.register(
    "eunomia",
    purge=purge_eunomia_data,
    deletion_models={"complianceFrameworks": (EunomiaFrameworkAdoption,), "complianceEvidence": (EunomiaEvidence,)},
    export_tables=EXPORT_TABLES,
    export_files=export_evidence_files,
)

__all__ = [
    "eunomia_blp",
    "CatalogManager",
    "EunomiaFrameworkManager",
    "EunomiaFrameworkAdoption",
    "EunomiaControlAssessment",
    "EunomiaAssessmentManager",
    "EunomiaError",
    "EvidenceProviderRegistry",
    "AutomaticEvidence",
]
