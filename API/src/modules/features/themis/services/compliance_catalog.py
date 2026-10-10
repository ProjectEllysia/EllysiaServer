"""
Los marcos de cumplimiento tal como los usa Themis: títulos y jerarquía de Eunomia.

Lybra mapea cada hallazgo a **códigos** de control (``nis2:21.2.e``) y no conoce el
catálogo; los marcos, sus títulos y su jerarquía son de Eunomia. Este módulo es el
punto donde Themis junta las dos cosas: lista los marcos que un usuario puede elegir
y resuelve los códigos de un hallazgo a controles con título para los informes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from src.modules.features.eunomia import CatalogManager

from ..lybra.compliance import (
    AttackTechnique,
    load_compliance_catalog,
    map_finding_compliance,
)


@dataclass(frozen=True)
class ComplianceFramework:
    """Un marco de cumplimiento que el usuario puede elegir.

    Attributes:
        key: Clave estable del marco (``"iso27001"``, ``"ens"``, ``"nis2"``).
        name: Nombre legible.
        short_name: Nombre corto para rótulos estrechos (``"ISO 27001"``).
    """

    key: str
    name: str
    short_name: str


@dataclass(frozen=True)
class ComplianceControl:
    """Un control (o una agrupación de controles) de un marco, ya con su título.

    Attributes:
        code: Código global ``<marco>:<identificador>``, p. ej. ``"ens:op.exp.4"``.
        framework: Clave del marco al que pertenece (``"ens"``).
        identifier: Identificador dentro del marco (``"op.exp.4"``).
        title: Título del control en castellano.
        parent: Código global del control padre, o ``None`` si es una raíz.
    """

    code: str
    framework: str
    identifier: str
    title: str
    parent: Optional[str]


@dataclass(frozen=True)
class ReportCompliance:
    """Lo que un hallazgo significa para un informe: técnicas y controles con título.

    Attributes:
        techniques: Técnicas de MITRE ATT&CK; vacía si el hallazgo no tiene mapeo.
        controls: Controles afectados de los marcos pedidos, en el orden del feed.
    """

    techniques: tuple[AttackTechnique, ...] = ()
    controls: tuple[ComplianceControl, ...] = ()


def list_compliance_frameworks() -> tuple[ComplianceFramework, ...]:
    """Los marcos que se pueden elegir, en el orden del catálogo de Eunomia.

    Returns:
        tuple[ComplianceFramework, ...]: Uno por marco del catálogo.
    """
    return tuple(
        ComplianceFramework(key=item["key"], name=item["name"], short_name=item["shortName"])
        for item in CatalogManager().list_frameworks()
    )


def resolve_report_controls(codes: Iterable[str]) -> dict[str, ComplianceControl]:
    """Resuelve códigos de control a controles con título, con sus ascendientes.

    Se resuelven contra la versión de cada marco a la que apunta el feed de Lybra.

    Args:
        codes: Códigos globales (``"nis2:21.2.e"``).

    Returns:
        dict[str, ComplianceControl]: Los controles pedidos y sus ascendientes, en el orden
            del catálogo (padres antes que hijos). Los códigos que el catálogo no tiene no
            aparecen.
    """
    resolved = CatalogManager().resolve_controls(codes, load_compliance_catalog().targets)
    return {
        code: ComplianceControl(
            code=code, framework=entry["framework"], identifier=entry["identifier"],
            title=entry["title"], parent=entry["parent"],
        )
        for code, entry in resolved.items()
    }


def map_report_compliance(category: Optional[str], check_id: Optional[str],
                          frameworks: Iterable[str] = ()) -> ReportCompliance:
    """Traduce un hallazgo a técnicas y a controles con título, para un informe.

    Args:
        category: ``Finding.category``.
        check_id: ``Finding.check_id``, o ``None``.
        frameworks: Claves de los marcos cuyos controles se quieren. Por defecto
            ninguno: solo salen las técnicas de ATT&CK.

    Returns:
        ReportCompliance: Técnicas y controles; los dos vacíos si el hallazgo no
            tiene mapeo. Un código que el catálogo de Eunomia no tiene se omite.
    """
    mapped = map_finding_compliance(category, check_id, frameworks)
    resolved = resolve_report_controls(mapped.controls)
    return ReportCompliance(
        techniques=mapped.techniques,
        controls=tuple(resolved[code] for code in mapped.controls if code in resolved),
    )
