"""La sección de riesgo de movimiento lateral del informe PDF de Lybra.

El riesgo lateral no se guarda: el informe de un escaneo de red lo calcula al
generarse con ``NetworkRiskManager.assess_scan``, igual que la pantalla. Estos
tests sustituyen ese cálculo por un resultado fijo y comprueban lo que el
lector encuentra: cada riesgo con su frase, su alcance, los equipos implicados
y qué hacer; nada en un escaneo de un solo equipo, y nada en Nuclei.
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

_RISKS = [
    {"title": "SMB con firma desactivada en srv-files alcanza a 2 equipos de su segmento",
     "severity": "HIGH", "riskScore": 8.1, "reach": 2, "rule": "exposed-service",
     "checkId": "lybra:lateral-exposed-service@1", "dedupKey": "a",
     "hosts": [{"hostId": 1, "name": "srv-files"}, {"hostId": 2, "name": "pc-01"},
               {"hostId": 3, "name": "pc-02"}]},
    {"title": "gw-01 tiene direcciones en 10.0.0.0/24 y 10.0.1.0/24",
     "severity": "MEDIUM", "riskScore": 5.0, "reach": 1, "rule": "multi-homed",
     "checkId": "lybra:lateral-multi-homed@1", "dedupKey": "b",
     "hosts": [{"hostId": 4, "name": "gw-01"}, {"hostId": 2, "name": "pc-01"}]},
]


def _text_of(elements: list) -> str:
    """El texto plano de los elementos, con las celdas de cada fila unidas por ``|``."""
    texts: list = []

    def collect(flowable) -> None:
        if isinstance(flowable, str):
            texts.append(flowable)
        elif hasattr(flowable, "getPlainText"):
            texts.append(flowable.getPlainText())
        for cells in getattr(flowable, "_cellvalues", []):
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


def _render(monkeypatch, strategy_name: str, assessment: dict) -> str:
    """Dibuja el cuerpo del informe de un escaneo sin hallazgos propios y devuelve su texto."""
    from src.modules.infrastructure import session as session_module
    from src.modules.features.themis.managers import (
        LybraEngineManager, NetworkRiskManager,
    )
    from src.modules.features.themis.services.reports import findings as report_module
    from src.modules.features.themis.services.reports.lybra import LybraPrintingStrategy
    from src.modules.features.themis.services.reports.nuclei import NucleiPrintingStrategy

    calls: list = []

    def assess(_self, user_id, scan_id):
        calls.append((user_id, scan_id))
        return assessment

    monkeypatch.setattr(session_module, "build_repository",
                        lambda _cls: SimpleNamespace(get_findings_by_scan=lambda _scan_id: []))
    monkeypatch.setattr(LybraEngineManager, "exposure_for", staticmethod(lambda _scan: "private"))
    monkeypatch.setattr(report_module, "active_framework_keys", lambda _user_id: [])
    monkeypatch.setattr(NetworkRiskManager, "assess_scan", assess)
    monkeypatch.setattr(report_module, "enrich_with_cve_context", lambda _findings: None)
    monkeypatch.setattr(report_module, "_knowledge_base_line", lambda _scan: "NVD 2026-09-24")
    monkeypatch.setattr(report_module, "_failing_sources_line", lambda: None)

    strategy_class = {"lybra": LybraPrintingStrategy, "nuclei": NucleiPrintingStrategy}[strategy_name]
    strategy = strategy_class.__new__(strategy_class)
    strategy.scan = SimpleNamespace(id=120, user_id=1, target="10.0.0.0/24", kb_version=None)
    strategy.color_palette = _PALETTE
    elements: list = []
    strategy.append_body(ReportTheme(getSampleStyleSheet(), _PALETTE), elements)
    text = _text_of(elements)
    return text if strategy_name != "nuclei" else text + f"\n<assess calls: {len(calls)}>"


def test_a_network_scan_lists_each_risk_with_its_reach_hosts_and_remedy(monkeypatch):
    text = _render(monkeypatch, "lybra", {"hostCount": 4, "risks": _RISKS})

    assert "Riesgo de movimiento lateral" in text
    assert "los 4 equipos de este escaneo" in text
    assert "Riesgo #1: ALTO | Alcanza a 2 equipos" in text
    assert "Riesgo #2: MEDIO | Alcanza a 1 equipo" in text
    assert "Servicio de administración remota expuesto" in text
    assert "srv-files, pc-01, pc-02" in text
    assert "Equipo que hace de puente entre redes" in text
    assert "Revisa si el equipo necesita estar en las dos redes" in text


def test_a_network_without_risks_says_so(monkeypatch):
    text = _render(monkeypatch, "lybra", {"hostCount": 3, "risks": []})

    assert "Riesgo de movimiento lateral" in text
    assert "No se ha encontrado ninguna forma" in text


def test_a_single_host_scan_has_no_lateral_section(monkeypatch):
    text = _render(monkeypatch, "lybra", {"hostCount": 1, "risks": []})

    assert "Riesgo de movimiento lateral" not in text


def test_nuclei_never_computes_lateral_risk(monkeypatch):
    text = _render(monkeypatch, "nuclei", {"hostCount": 4, "risks": _RISKS})

    assert "Riesgo de movimiento lateral" not in text
    assert "<assess calls: 0>" in text
