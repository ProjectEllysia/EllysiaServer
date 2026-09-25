"""El apartado de cumplimiento del informe PDF de Lybra.

Cada ficha lleva sus técnicas de MITRE ATT&CK (siempre) y los controles de los
marcos que el dueño del escaneo tiene elegidos; una sección aparte los agrega
por control, agrupados bajo su control padre. Es exclusivo de Lybra: el
informe de Nuclei comparte la clase que pinta las fichas y no debe heredarlo.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from reportlab.lib.styles import getSampleStyleSheet

from src.modules.tools.press import ColorType, ReportTheme

pytestmark = pytest.mark.unit

_PALETTE = {
    ColorType.BLACK: "#1A2410", ColorType.DARK: "#4A6132", ColorType.MAIN: "#7CA163",
    ColorType.SECONDARY: "#A8C98F", ColorType.LIGHT: "#D4E8C4", ColorType.WHITE: "#F3F8EE",
}


def _row(title, category, check_id, state="open"):
    return SimpleNamespace(
        fixed_reason=None, title=title, category=category, port=443, service="https", cpe=None,
        cve_ids=[], cvss_score=None, epss_score=None, in_kev=False, qod=90, confirmed=True,
        exploit_maturity=None, state=state, source="lybra", cpe_resolved=False, required_os=None,
        check_id=check_id, vhost=None, severity="HIGH",
    )


_ROWS = [
    _row("Certificado TLS caducado", "tls", "tls-expired-cert"),
    _row("Fichero .env expuesto", "exposed_path", "dotenv-exposure"),
    _row("Cabecera HSTS ausente", "security_header", "missing-hsts-header", state="false_positive"),
]


def _render(monkeypatch, strategy_class, frameworks):
    """Ejecuta ``append_body`` sin base de datos y devuelve los elementos y su texto."""
    from src.modules.infrastructure import session as session_module
    from src.modules.features.themis.managers import ComplianceManager, LybraEngineManager
    from src.modules.features.themis.services.reports import findings as report_module

    monkeypatch.setattr(session_module, "build_repository",
                        lambda _cls: SimpleNamespace(get_findings_by_scan=lambda _scan_id: _ROWS))
    monkeypatch.setattr(LybraEngineManager, "exposure_for", staticmethod(lambda _scan: "public"))
    monkeypatch.setattr(ComplianceManager, "resolve_effective_frameworks",
                        lambda _self, _user_id: list(frameworks))
    monkeypatch.setattr(report_module, "enrich_with_cve_context", lambda _findings: None)
    monkeypatch.setattr(report_module, "_knowledge_base_line", lambda _scan: "NVD 2026-09-24")
    monkeypatch.setattr(report_module, "_failing_sources_line", lambda: None)

    strategy = strategy_class.__new__(strategy_class)
    strategy.scan = SimpleNamespace(id=7, user_id=1)
    strategy.color_palette = _PALETTE
    elements = []
    strategy.append_body(ReportTheme(getSampleStyleSheet(), _PALETTE), elements)

    texts = []
    for element in elements:
        if hasattr(element, "getPlainText"):
            texts.append(element.getPlainText())
        for cells in getattr(element, "_cellvalues", []):
            texts.append(" | ".join(cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)
                                    for cell in cells))
    return elements, "\n".join(texts)


def _lybra():
    from src.modules.features.themis.services.reports.lybra import LybraPrintingStrategy
    return LybraPrintingStrategy


def _nuclei():
    from src.modules.features.themis.services.reports.nuclei import NucleiPrintingStrategy
    return NucleiPrintingStrategy


def test_each_card_names_its_attack_technique_and_its_controls(monkeypatch):
    _, text = _render(monkeypatch, _lybra(), ["ens"])

    assert "MITRE ATT&CK: | T1557 Adversary-in-the-Middle (Credential Access, Collection)" in text
    assert "ENS: | mp.com.2 Protección de la confidencialidad" in text
    # Sólo los marcos elegidos: ni ISO 27001 ni NIS2.
    assert "ISO 27001:" not in text and "NIS2:" not in text


def test_the_section_groups_controls_under_their_parent_and_counts_findings(monkeypatch):
    _, text = _render(monkeypatch, _lybra(), ["ens"])

    assert "Cumplimiento y técnicas de ataque" in text
    assert "op.exp Explotación" in text
    assert "op.exp.2 | Configuración de seguridad | 1 | " in text
    # El falso positivo no cuenta: HSTS sólo lo tocaría a él.
    assert "T1557 | Adversary-in-the-Middle | Credential Access, Collection | 1 | " in text


def test_without_frameworks_only_attack_is_shown_and_the_report_says_where_to_choose(monkeypatch):
    _, text = _render(monkeypatch, _lybra(), [])

    assert "MITRE ATT&CK:" in text
    assert "ENS:" not in text
    assert "No hay marcos de cumplimiento elegidos" in text


def test_the_nuclei_report_has_no_compliance_at_all(monkeypatch):
    _, text = _render(monkeypatch, _nuclei(), ["ens", "iso27001", "nis2"])

    assert "MITRE ATT&CK" not in text
    assert "Cumplimiento y técnicas de ataque" not in text


def test_the_compliance_body_builds_a_real_pdf(monkeypatch, tmp_path):
    """Sólo construir el documento detecta un ``SPAN`` o un ancho de columna imposibles."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    elements, _ = _render(monkeypatch, _lybra(), ["iso27001", "ens", "nis2"])
    target = tmp_path / "compliance.pdf"
    SimpleDocTemplate(str(target), pagesize=A4).build(elements)

    assert target.stat().st_size > 0
