"""El informe PDF de un escaneo de exposición cloud.

Un escaneo cloud no es un ``Scan``: su informe lo dibuja un generador propio a
partir de la fila ``OsintScan``. Estos tests fijan lo que el lector necesita
encontrar en él —qué se comprobó, qué significa cada hallazgo y cómo se
corrige— sin base de datos: el generador recibe los datos ya cargados.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.modules.features.themis.services.compliance_catalog import list_compliance_frameworks
from src.modules.features.themis.services.reports.cloud import CloudExposurePDFCreator

pytestmark = pytest.mark.unit


def _finding(title: str, check: str, subject: str, severity: str = "HIGH") -> dict:
    """Un hallazgo con la forma que guarda el escaneo cloud."""
    return {"title": title, "category": "cloud_exposure", "severity": severity, "port": None,
            "service": subject, "check_id": f"lybra:{check}@1", "confirmed": True, "state": "open"}


def _scan(findings: list, check_subdomains: bool = True, subdomains=None) -> SimpleNamespace:
    """Una fila ``OsintScan`` de mentira, ya terminada."""
    return SimpleNamespace(
        id=7, user_id=1, domain="example.com", mode="cloud", status="finished",
        started_at=datetime(2026, 9, 29, 10, 0), finished_at=datetime(2026, 9, 29, 10, 1),
        parameters={"cloud_resources": ["s3:datos", "firebase:app-prod"],
                    "check_subdomains": check_subdomains},
        subdomains=subdomains if subdomains is not None else [{"name": "blog.example.com"}],
        findings=findings,
    )


def _body_text(generator: CloudExposurePDFCreator) -> str:
    """El texto plano del cuerpo del informe, celda a celda."""
    elements: list = []
    generator.append_body(elements, generator.theme)
    texts = []

    def collect(flowable) -> None:
        if isinstance(flowable, str):
            texts.append(flowable)
        elif hasattr(flowable, "getPlainText"):
            texts.append(flowable.getPlainText())
        for cells in getattr(flowable, "_cellvalues", []):
            # Una fila se lee como en el PDF: sus celdas en orden, separadas.
            row: list = []
            for cell in cells:
                for inner in (cell if isinstance(cell, list) else [cell]):
                    before = len(texts)
                    collect(inner)
                    row.extend(texts[before:])
                    del texts[before:]
            texts.append(" | ".join(part for part in row if part))
    for element in elements:
        collect(element)
    return "\n".join(texts)


_FINDINGS = [
    _finding("Bucket S3 público: cualquiera puede listar su contenido (datos)",
             "cloud-s3-public-bucket", "s3:datos"),
    _finding("Subdominio susceptible de takeover: blog.example.com apunta a GitHub Pages",
             "cloud-takeover-github-pages", "blog.example.com"),
    _finding("Base de Firebase sin reglas: cualquiera puede leer sus datos (app-prod)",
             "cloud-firebase-open-database", "firebase:app-prod", severity="CRITICAL"),
]


def test_the_scope_says_what_was_checked():
    text = _body_text(CloudExposurePDFCreator(_scan(_FINDINGS)))

    assert "s3:datos, firebase:app-prod" in text
    assert "Comprobados: 1 conocidos" in text
    assert "3 (1 crítica, 2 altas)" in text


def test_the_gravest_finding_comes_first_with_its_meaning_and_remedy():
    text = _body_text(CloudExposurePDFCreator(_scan(_FINDINGS)))

    assert text.index("Hallazgo #1: CRÍTICA") < text.index("Hallazgo #2: ALTA") < text.index("Hallazgo #3: ALTA")
    assert "Base de datos de Firebase sin reglas de acceso" in text
    assert "reglas de seguridad que exijan autenticación" in text
    # Todo check de takeover comparte explicación, sea cual sea el proveedor.
    assert "Subdominio que se puede secuestrar" in text
    assert "Borra el registro DNS (el CNAME)" in text


def test_each_card_names_its_controls_for_the_chosen_frameworks():
    frameworks = tuple(framework for framework in list_compliance_frameworks()
                       if framework.key == "iso27001")
    text = _body_text(CloudExposurePDFCreator(_scan(_FINDINGS), frameworks=frameworks))

    assert "MITRE ATT&CK:" in text
    assert "ISO 27001:" in text
    assert "ENS:" not in text


def test_a_clean_scan_says_so_and_still_warns_about_what_was_not_checked():
    text = _body_text(CloudExposurePDFCreator(_scan([], check_subdomains=False)))

    assert "No se encontró ningún recurso" in text
    assert "No se pidió comprobarlos" in text
    assert "no busca buckets" in text


def test_the_whole_document_renders_to_a_pdf():
    assert CloudExposurePDFCreator(_scan(_FINDINGS)).generate().startswith(b"%PDF")
