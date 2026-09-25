"""Qué controles de cumplimiento y qué técnicas de MITRE ATT&CK toca un hallazgo.

Un hallazgo de Lybra dice qué está mal; quien prepara una auditoría necesita
además saber qué requisito incumple (ISO 27001, ENS, NIS2) y qué haría un
atacante con él (MITRE ATT&CK). La traducción sale de un feed curado
(``feeds/compliance_mappings.json``): un mapeo por ``Finding.category`` y, donde
la categoría se queda corta, uno por ``check_id`` que sustituye sólo las claves
que declara.

Cada control se identifica por un código global ``<marco>:<identificador>``
(``ens:op.exp.4``). Es la clave estable que guardan las preferencias de usuario
y organización, así que el día que el catálogo pase a base de datos el resto
del código no cambia. Es puro: no toca base de datos ni red.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

_BUNDLED_FEED = Path(__file__).parent / "feeds" / "compliance_mappings.json"


@dataclass(frozen=True)
class ComplianceFramework:
    """Un marco de cumplimiento que el usuario puede elegir.

    Attributes:
        key: Clave estable del marco (``"iso27001"``, ``"ens"``, ``"nis2"``).
        name: Nombre legible, con su versión (``"ISO/IEC 27001:2022"``).
    """

    key: str
    name: str


@dataclass(frozen=True)
class ComplianceControl:
    """Un control (o una agrupación de controles) de un marco.

    Attributes:
        code: Código global ``<marco>:<identificador>``, p. ej. ``"ens:op.exp.4"``.
        framework: Clave del marco al que pertenece (``"ens"``).
        identifier: Identificador dentro del marco (``"op.exp.4"``).
        title: Título del control en castellano.
        parent: Código global del control padre (``"ens:op.exp"``), o ``None``
            si es una raíz del marco.
    """

    code: str
    framework: str
    identifier: str
    title: str
    parent: Optional[str]


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
        controls: Controles afectados de los marcos pedidos, en el orden del
            feed; vacía si no se pidió ningún marco o el hallazgo no tiene mapeo.
    """

    techniques: tuple[AttackTechnique, ...] = ()
    controls: tuple[ComplianceControl, ...] = ()


@dataclass(frozen=True)
class ComplianceCatalog:
    """El feed ya interpretado.

    Attributes:
        feed_version: Versión del feed (``"lybra-compliance-1"``).
        frameworks: Marcos por clave, en el orden del feed.
        controls: Todos los controles por código global.
        techniques: Todas las técnicas por id.
        categories: Mapeo crudo por ``Finding.category``:
            ``{"mitre": [...], "controls": [...]}``.
        checks: Mapeo crudo por ``check_id``; cada entrada puede declarar sólo
            una de las dos claves.
    """

    feed_version: str
    frameworks: dict[str, ComplianceFramework]
    controls: dict[str, ComplianceControl]
    techniques: dict[str, AttackTechnique]
    categories: dict[str, dict]
    checks: dict[str, dict]


def parse_compliance_catalog(document: dict) -> ComplianceCatalog:
    """Interpreta el documento del feed.

    No valida referencias cruzadas (un control o una técnica que no existen):
    eso lo comprueba ``tests/unit/test_lybra_compliance.py`` sobre el feed que
    se distribuye, y aquí una referencia rota simplemente no se resuelve.

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
    frameworks: dict[str, ComplianceFramework] = {}
    controls: dict[str, ComplianceControl] = {}
    for key, entry in document.get("frameworks", {}).items():
        frameworks[key] = ComplianceFramework(key=key, name=entry["name"])
        for identifier, control in entry.get("controls", {}).items():
            parent = control.get("parent")
            controls[f"{key}:{identifier}"] = ComplianceControl(
                code=f"{key}:{identifier}",
                framework=key,
                identifier=identifier,
                title=control["title"],
                parent=f"{key}:{parent}" if parent else None,
            )
    return ComplianceCatalog(
        feed_version=document.get("feedVersion", ""),
        frameworks=frameworks,
        controls=controls,
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


def list_compliance_frameworks() -> tuple[ComplianceFramework, ...]:
    """Los marcos que se pueden elegir, en el orden del feed.

    Returns:
        tuple[ComplianceFramework, ...]: Uno por marco del catálogo.
    """
    return tuple(load_compliance_catalog().frameworks.values())


def map_finding_compliance(category: Optional[str], check_id: Optional[str],
                           frameworks: Iterable[str] = ()) -> FindingCompliance:
    """Traduce un hallazgo a técnicas de ATT&CK y a controles de los marcos pedidos.

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
        FindingCompliance: Técnicas y controles; los dos vacíos si el hallazgo
            no tiene mapeo.
    """
    catalog = load_compliance_catalog()
    mapping = dict(catalog.categories.get(category or "", {}))
    mapping.update(catalog.checks.get(check_id or "", {}))
    wanted = set(frameworks)
    return FindingCompliance(
        techniques=tuple(catalog.techniques[identifier] for identifier in mapping.get("mitre", ())
                         if identifier in catalog.techniques),
        controls=tuple(catalog.controls[code] for code in mapping.get("controls", ())
                       if code in catalog.controls and catalog.controls[code].framework in wanted),
    )
