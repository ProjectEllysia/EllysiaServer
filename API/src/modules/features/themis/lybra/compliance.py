"""Qué controles de cumplimiento y qué técnicas de MITRE ATT&CK toca un hallazgo.

Un hallazgo de Lybra dice qué está mal; quien prepara una auditoría necesita
además saber qué requisito incumple (ISO 27001, ENS, NIS2) y qué haría un
atacante con él (MITRE ATT&CK). La traducción sale de un feed curado
(``feeds/compliance_mappings.json``): un mapeo por ``Finding.category`` y, donde
la categoría se queda corta, uno por ``check_id`` que sustituye sólo las claves
que declara.

Lybra es dueño de las técnicas de ATT&CK y de **qué control cubre cada
hallazgo**; no lo es de los marcos: el título y la jerarquía de cada control son
de Eunomia. Un control se cita por su código global ``<marco>:<identificador>``
(``ens:op.exp.4``) y aquí nunca se resuelve a un título: quien lo necesita
(los informes) lo pide a Eunomia con la versión que declara ``targets``. Es
puro: no toca base de datos ni red, y no conoce el catálogo de marcos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

_BUNDLED_FEED = Path(__file__).parent / "feeds" / "compliance_mappings.json"


@dataclass(frozen=True)
class AttackTechnique:
    """Una técnica de MITRE ATT&CK.

    Attributes:
        identifier: Id de la técnica o subtécnica (``"T1190"``, ``"T1552.001"``).
        name: Nombre oficial, en inglés.
        tactics: Nombres de las tácticas a las que sirve, en el orden del feed
            (la primera es la que mejor describe el hallazgo).
    """

    identifier: str
    name: str
    tactics: tuple[str, ...]


@dataclass(frozen=True)
class FindingCompliance:
    """Lo que un hallazgo significa en términos de ataque y de cumplimiento.

    Attributes:
        techniques: Técnicas de MITRE ATT&CK; vacía si el hallazgo no tiene mapeo.
        controls: Códigos globales de los controles afectados de los marcos
            pedidos (``"nis2:21.2.e"``), en el orden del feed; vacía si no se
            pidió ningún marco o el hallazgo no tiene mapeo. Sin título: lo
            resuelve Eunomia.
    """

    techniques: tuple[AttackTechnique, ...] = ()
    controls: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComplianceCatalog:
    """El feed ya interpretado.

    Attributes:
        feed_version: Versión del feed (``"lybra-compliance-1"``).
        targets: Versión de cada marco a la que apuntan los códigos del feed
            (``{"nis2": "2022-2555"}``), en el orden del feed.
        techniques: Todas las técnicas por id.
        categories: Mapeo crudo por ``Finding.category``:
            ``{"mitre": [...], "controls": [...]}``.
        checks: Mapeo crudo por ``check_id``; cada entrada puede declarar sólo
            una de las dos claves.
    """

    feed_version: str
    targets: dict[str, str]
    techniques: dict[str, AttackTechnique]
    categories: dict[str, dict]
    checks: dict[str, dict]


def parse_compliance_catalog(document: dict) -> ComplianceCatalog:
    """Interpreta el documento del feed.

    No valida referencias cruzadas (una técnica que no existe, o un control que
    el catálogo de Eunomia no tiene): eso lo comprueban los tests sobre el feed
    que se distribuye, y aquí una técnica rota simplemente no se resuelve.

    Args:
        document: El JSON del feed ya cargado.

    Returns:
        ComplianceCatalog: El catálogo listo para consultar.
    """
    mitre = document.get("mitre", {})
    tactic_names = mitre.get("tactics", {})
    techniques = {
        identifier: AttackTechnique(
            identifier=identifier,
            name=entry["name"],
            tactics=tuple(tactic_names.get(tactic, tactic) for tactic in entry.get("tactics", ())),
        )
        for identifier, entry in mitre.get("techniques", {}).items()
    }
    return ComplianceCatalog(
        feed_version=document.get("feedVersion", ""),
        targets=dict(document.get("targets", {})),
        techniques=techniques,
        categories=document.get("categories", {}),
        checks=document.get("checks", {}),
    )


@lru_cache(maxsize=1)
def load_compliance_catalog(path: Optional[str] = None) -> ComplianceCatalog:
    """Carga el feed de mapeos de cumplimiento.

    Args:
        path: Ruta a otro feed. Por defecto, ``None``: el que acompaña al módulo.

    Returns:
        ComplianceCatalog: El catálogo, cacheado tras la primera lectura.
    """
    feed_path = Path(path) if path else _BUNDLED_FEED
    return parse_compliance_catalog(json.loads(feed_path.read_text(encoding="utf-8")))


def map_finding_compliance(category: Optional[str], check_id: Optional[str],
                           frameworks: Iterable[str] = ()) -> FindingCompliance:
    """Traduce un hallazgo a técnicas de ATT&CK y a códigos de control de los marcos pedidos.

    Parte del mapeo de su categoría y, si el ``check_id`` tiene entrada propia,
    sustituye por la suya cada clave que esa entrada declara (``mitre``,
    ``controls`` o las dos).

    Args:
        category: ``Finding.category`` (``"tls"``, ``"exposed_path"``…). Una
            categoría sin mapeo (los eventos como ``fingerprint``) no aporta nada.
        check_id: ``Finding.check_id``, o ``None``.
        frameworks: Claves de los marcos cuyos controles se quieren
            (``"iso27001"``, ``"ens"``, ``"nis2"``). Por defecto ninguno: sólo
            se devuelven las técnicas de ATT&CK, que salen siempre.

    Returns:
        FindingCompliance: Técnicas y códigos de control; los dos vacíos si el
            hallazgo no tiene mapeo.
    """
    catalog = load_compliance_catalog()
    mapping = dict(catalog.categories.get(category or "", {}))
    mapping.update(catalog.checks.get(check_id or "", {}))
    wanted = set(frameworks)
    return FindingCompliance(
        techniques=tuple(catalog.techniques[identifier] for identifier in mapping.get("mitre", ())
                         if identifier in catalog.techniques),
        controls=tuple(code for code in mapping.get("controls", ())
                       if code.split(":", 1)[0] in wanted),
    )
