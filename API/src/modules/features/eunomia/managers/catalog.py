"""
CatalogManager — el catálogo de marcos tal como lo ve la API.

Lee del servicio puro ``services/catalog.py`` y lo convierte en estructuras
serializables. No toca base de datos: el catálogo son ficheros versionados.
"""

from typing import Iterable, Mapping, Optional

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
        "officialText": node.official_text,
        "description": node.description,
        "actions": list(node.actions),
        "evidence": list(node.evidence),
        "source": node.source,
        "register": node.register,
        "metadata": node.metadata,
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

    def resolve_controls(self, codes: Iterable[str], versions: Optional[Mapping[str, str]] = None) -> dict[str, dict]:
        """Resuelve códigos de control a sus nodos del catálogo, con sus ascendientes.

        Es lo que usan los módulos que citan controles sin ser dueños del catálogo (los
        informes de Lybra): les basta con el código y una versión.

        Args:
            codes: Códigos globales ``<marco>:<identificador>`` (``"nis2:21.2.e"``). Los que
                el catálogo no tiene se ignoran.
            versions: Versión de cada marco a consultar (``{"nis2": "2022-2555"}``). Un marco
                que no aparece se resuelve contra su versión vigente. Por defecto, ninguna.

        Returns:
            dict[str, dict]: Por código, ``{"code", "framework", "identifier", "title",
                "parent", "order"}``. Incluye cada control pedido y todos sus ascendientes, y
                sale en el orden del catálogo (marcos en el orden del índice y, dentro de
                cada uno, el árbol en profundidad): quien recorra el diccionario ve a los
                hermanos juntos y a cada padre antes que a sus hijos.
        """
        wanted = set(codes)
        resolved: dict[str, dict] = {}
        for framework in load_index()["frameworks"]:
            key = framework["key"]
            if not any(code.startswith(f"{key}:") for code in wanted):
                continue
            loaded = load_version(key, (versions or {}).get(key) or framework["current"])
            if loaded is None:
                continue
            needed: set[str] = set()
            for code in wanted:
                node = loaded.node(code)
                if node is not None:
                    needed.add(code)
                    needed.update(ancestor.code for ancestor in loaded.ancestors(code))
            for position, node in enumerate(loaded.walk()):
                if node.code in needed:
                    resolved[node.code] = {
                        "code": node.code, "framework": key, "identifier": node.identifier,
                        "title": node.title, "parent": node.parent, "order": position,
                    }
        return resolved

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
