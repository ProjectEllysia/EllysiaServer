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
    - Endpoints: eunomia_blp.
    - Excepciones: EunomiaError.
"""

from .endpoints import eunomia_blp
from .managers import CatalogManager
from .exceptions import EunomiaError

__all__ = [
    "eunomia_blp",
    "CatalogManager",
    "EunomiaError",
]
