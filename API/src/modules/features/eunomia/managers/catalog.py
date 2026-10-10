"""
CatalogManager — el catálogo de marcos tal como lo ve la API.

Lee del servicio puro ``services/catalog.py`` y lo convierte en estructuras
serializables. No toca base de datos: el catálogo son ficheros versionados.
"""

from typing import Optional

from ..exceptions import FrameworkNotFoundError
from ..services.catalog import CatalogNode, FrameworkVersion, load_index, load_version


def _node_payload(version: FrameworkVersion, node: CatalogNode) -> dict:
    """Serializa un nodo con sus hijos, recursivamente y en el orden del catálogo."""
    return {
        "code": node.code,
        "identifier": node.identifier,
        "kind": node.kind,
        "isAssessable": node.is_assessable,
        "title": node.title,
        "description": node.description,
        "actions": list(node.actions),
        "evidence": list(node.evidence),
        "source": node.source,
        "register": node.register,
        "children": [_node_payload(version, child) for child in version.children(node.code)],
    }


class CatalogManager:
    """Consulta del catálogo de marcos: qué marcos hay y el árbol de cada versión."""

    def list_frameworks(self) -> list[dict]:
        """Devuelve el catálogo resumido: cada marco con sus versiones y la vigente.

        Returns:
            list[dict]: Un elemento por marco, con ``key``, ``name``, ``shortName``,
                ``current`` (versión vigente) y ``versions`` (``[{"version", "status"}]``).
        """
        return [
            {
                "key": framework["key"],
                "name": framework["name"],
                "shortName": framework["shortName"],
                "current": framework["current"],
                "versions": [dict(item) for item in framework["versions"]],
            }
            for framework in load_index()["frameworks"]
        ]

    def get_version(self, key: str, version: str) -> dict:
        """Devuelve el árbol de una versión de un marco.

        Args:
            key: Clave del marco (``"nis2"``).
            version: Identificador de la versión (``"2022-2555"``).

        Returns:
            dict: Metadatos de la versión (``key``, ``version``, ``status``, ``name``,
                ``shortName``, ``publishedAt``, ``licenseMode``, ``notes``, ``sources``) y ``tree``: las raíces
                con sus hijos anidados.

        Raises:
            FrameworkNotFoundError: Si el catálogo no declara ese marco o esa versión.
        """
        loaded: Optional[FrameworkVersion] = load_version(key, version)
        if loaded is None:
            raise FrameworkNotFoundError(f"{key}/{version}")
        return {
            "key": loaded.key,
            "version": loaded.version,
            "status": loaded.status,
            "name": loaded.name,
            "shortName": loaded.short_name,
            "publishedAt": loaded.published_at,
            "licenseMode": loaded.license_mode,
            "notes": loaded.notes,
            "sources": [
                {"name": source.name, "url": source.url, "license": source.license,
                 "consultedAt": source.consulted_at}
                for source in loaded.sources
            ],
            "tree": [_node_payload(loaded, root) for root in loaded.children(None)],
        }
