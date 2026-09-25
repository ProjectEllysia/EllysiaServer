"""El cuerpo del informe PDF, agrupado por unidad remediable.

Un escaneo contra un host con dos productos desactualizados puede dar 150
hallazgos, y hasta ahora el PDF los imprimía como 150 fichas seguidas. Lo
llamativo era que el propio informe ya tenía la agrupación delante: la usa
desde hace tiempo para armar el prompt del análisis de IA. Así que la IA
recomendaba «actualiza Apache y cierras 12 CVEs» y tres páginas más abajo esos
12 CVEs aparecían como fichas inconexas.

Lo que hay que fijar aquí es lo que un lector del PDF puede comprobar sin
abrirlo en un visor: que los grupos se parten en las dos secciones correctas y
en el orden correcto, que el orden interno de las fichas es el de siempre, y
que el árbol de marcadores sale con los niveles bien anidados (ReportLab
rechaza un nivel que salte más de uno respecto al anterior, así que un error
aquí no es cosmético: no genera el PDF).
"""

from __future__ import annotations

import pytest
from reportlab.lib.styles import getSampleStyleSheet

from src.modules.tools.press import ColorType, ReportTheme
from src.modules.features.themis.lybra.grouping import build_service_rollup
from src.modules.features.themis.services.reports.findings import (
    FindingsPrintingStrategy,
    _default_site_warning,
    _unverified_warning,
)
from src.modules.features.themis.services.reports.outline import OutlineEntry

pytestmark = pytest.mark.unit

_PALETTE = {
    ColorType.BLACK: "#1A2410", ColorType.DARK: "#4A6132", ColorType.MAIN: "#7CA163",
    ColorType.SECONDARY: "#A8C98F", ColorType.LIGHT: "#D4E8C4", ColorType.WHITE: "#F3F8EE",
}

_APACHE = "cpe:2.3:a:apache:http_server:2.4.52:*:*:*:*:*:*:*"
_OPENSSH = "cpe:2.3:a:openbsd:openssh:8.2:*:*:*:*:*:*:*"


class _Scan:
    """Lo único que el cuerpo agrupado mira del escaneo es su id, que va en la
    clave de los marcadores, y su dueño, del que salen los marcos de cumplimiento."""

    id = 7
    user_id = 1


def _strategy() -> FindingsPrintingStrategy:
    """La estrategia sin pasar por ``__init__``.

    ``__init__`` construye además el escritor de IA y lee la paleta de
    ``SecOpsConfig.json``, y nada de eso interviene en cómo se reparten los
    grupos: pedirlo obligaría a montar configuración para comprobar un orden.
    """
    strategy = FindingsPrintingStrategy.__new__(FindingsPrintingStrategy)
    strategy.scan = _Scan()
    strategy.color_palette = _PALETTE
    return strategy


def _theme() -> ReportTheme:
    return ReportTheme(getSampleStyleSheet(), _PALETTE)


def _finding(**overrides) -> dict:
    base = {
        "title": "hallazgo", "category": "outdated_software", "port": 80, "service": "http",
        "cpe": None, "cve_ids": [], "cvss_score": None, "epss_score": None, "in_kev": False,
        "confirmed": False, "priority": "INFO", "fixed_version": None,
    }
    base.update(overrides)
    return base


def _outline_entries(elements: list) -> list:
    return [(entry.level, entry.title, entry.key)
            for entry in elements if isinstance(entry, OutlineEntry)]


# ------------------------------------------------------------------ secciones

def test_products_and_configuration_are_two_separate_sections_in_that_order():
    """Son dos clases de trabajo distintas: subir un producto de versión, y
    arreglar una configuración. Mezclarlas hacía que «falta la cabecera HSTS»
    pareciera un producto más del inventario."""
    groups = build_service_rollup([
        _finding(cpe=_APACHE, cvss_score=9.8),
        _finding(category="security_header", cvss_score=2.0),
    ])

    sections = _strategy()._split_into_sections(groups)  # pylint: disable=protected-access

    assert [key for key, _, _ in sections] == ["prod", "conf"]
    assert [title for _, title, _ in sections] == [
        "Productos afectados", "Configuración y exposición"]
    assert [group.label for group in sections[0][2]] == ["http server 2.4.52"]
    assert [group.label for group in sections[1][2]] == ["security_header (http)"]


def test_a_section_with_no_groups_is_not_printed_at_all():
    """Imprimir el título de una sección para no colgarle nada debajo se lee
    como si faltara algo, no como si no hubiera nada que decir."""
    groups = build_service_rollup([_finding(cpe=_APACHE, cvss_score=9.8)])

    sections = _strategy()._split_into_sections(groups)  # pylint: disable=protected-access

    assert [key for key, _, _ in sections] == ["prod"]


def test_findings_inside_a_group_keep_the_priority_ladder_of_the_flat_list():
    """El orden de las fichas no cambia con la agrupación: sigue siendo
    prioridad, luego comprobados antes que hipótesis, luego CVSS. Lo que cambia
    es que ahora se aplica dentro de cada grupo."""
    low = _finding(title="bajo", priority="LOW", confirmed=True)
    critical_guess = _finding(title="crítico deducido", priority="CRITICAL", confirmed=False)
    critical_confirmed = _finding(title="crítico comprobado", priority="CRITICAL", confirmed=True)

    ordered = _strategy()._sorted_findings(  # pylint: disable=protected-access
        [low, critical_guess, critical_confirmed])

    assert [finding["title"] for finding in ordered] == [
        "crítico comprobado", "crítico deducido", "bajo"]


def test_a_scan_with_no_findings_still_says_so_and_prints_no_group_index():
    """El caso vacío no es un informe a medias: es la afirmación de que se
    comprobó y no había nada. Un índice de grupos vacío ahí sobra."""
    elements = []
    strategy = _strategy()
    strategy._append_findings_section(_theme(), elements, [])  # pylint: disable=protected-access

    texts = [element.text for element in elements if hasattr(element, "text")]

    assert "El motor no detectó ningún hallazgo para este objetivo." in texts
    assert "Índice de grupos" not in texts
    assert [level for level, _, _ in _outline_entries(elements)] == [0]


# ---------------------------------------------------------------- marcadores

def test_the_outline_nests_section_under_findings_and_group_under_section():
    """ReportLab rechaza un nivel que salte más de uno respecto al anterior, así
    que este anidamiento no es cosmético: si se rompe, el PDF no se genera."""
    elements = []
    strategy = _strategy()
    strategy._append_findings_section(  # pylint: disable=protected-access
        _theme(), elements, [
            _finding(cpe=_APACHE, cvss_score=9.8, cve_ids=["CVE-2023-1"]),
            _finding(cpe=_OPENSSH, port=22, service="ssh", cvss_score=7.1),
            _finding(category="security_header", cvss_score=2.0),
        ])

    levels = [level for level, _, _ in _outline_entries(elements)]

    assert levels == [0, 1, 2, 2, 1, 2]
    for index, level in enumerate(levels[1:], start=1):
        assert level - levels[index - 1] <= 1


def test_every_bookmark_key_is_unique_and_carries_the_scan():
    """Dos marcadores con la misma clave apuntarían al mismo destino, y el
    índice mandaría al sitio equivocado."""
    elements = []
    strategy = _strategy()
    strategy._append_findings_section(  # pylint: disable=protected-access
        _theme(), elements, [
            _finding(cpe=_APACHE, cvss_score=9.8),
            _finding(cpe=_OPENSSH, port=22, service="ssh", cvss_score=7.1),
            _finding(category="security_header", cvss_score=2.0),
        ])

    keys = [key for _, _, key in _outline_entries(elements)]

    assert len(keys) == len(set(keys))
    assert all(key.startswith("scan7-") for key in keys)


def test_a_group_bookmark_says_how_many_findings_it_hides():
    """El árbol de marcadores es lo más parecido a plegar que un PDF admite, y
    sólo sirve para decidir dónde entrar si dice cuánto hay detrás."""
    elements = []
    strategy = _strategy()
    strategy._append_findings_section(  # pylint: disable=protected-access
        _theme(), elements, [
            _finding(cpe=_APACHE, cvss_score=9.8),
            _finding(cpe=_APACHE, cvss_score=7.5),
        ])

    group_titles = [title for level, title, _ in _outline_entries(elements) if level == 2]

    assert group_titles == ["http server 2.4.52 (2)"]


# ------------------------------------------------------------- el PDF entero

def test_the_grouped_body_builds_a_real_pdf_with_its_outline(tmp_path):
    """La comprobación de que todo esto compone de verdad: tablas, saltos
    condicionales y marcadores pasando juntos por ReportLab. Es lo único que
    puede detectar un ancho de columna imposible o un nivel de outline mal
    anidado, que sólo revientan al construir el documento."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    elements = []
    strategy = _strategy()
    strategy._append_findings_section(  # pylint: disable=protected-access
        _theme(), elements, [
            _finding(cpe=_APACHE, cvss_score=9.8, epss_score=0.42, in_kev=True,
                     cve_ids=["CVE-2023-1"], confirmed=True, priority="CRITICAL",
                     fixed_version="2.4.58"),
            _finding(cpe=_APACHE, cvss_score=5.0, cve_ids=["CVE-2023-2"], priority="MEDIUM"),
            _finding(category="security_header", cvss_score=2.0, priority="LOW",
                     title="Falta la cabecera HSTS"),
        ])

    target = tmp_path / "grouped.pdf"
    SimpleDocTemplate(str(target), pagesize=A4).build(elements)

    contents = target.read_bytes()
    assert target.stat().st_size > 0
    assert b"/Outlines" in contents


# ────────────────────── aviso de hallazgos sin contrastar con el proveedor


def test_the_report_warns_about_unverified_distro_findings(monkeypatch):
    from src.modules.features.themis.services.reports import findings as report_module
    monkeypatch.setattr(report_module, "_is_oval_stale", lambda: True)
    findings = [{"is_unverified_distro_package": True, "state": "open"},
                {"is_unverified_distro_package": True, "state": "false_positive"},
                {"is_unverified_distro_package": False, "state": "open"}]

    warning = _unverified_warning(findings)

    assert "1 hallazgo(s)" in warning
    assert "OVAL" in warning


def test_no_unverified_findings_means_no_warning():
    assert _unverified_warning([{"state": "open"}]) is None


# ────────────────────── hallazgos corregidos desde el escaneo anterior


def test_fixed_findings_get_their_own_section_after_the_findings():
    from src.modules.features.themis.services.reports.findings import _append_fixed_section

    elements = []
    _append_fixed_section(_theme(), elements, [
        _finding(title="Falta la cabecera <HSTS>", state="fixed", vhost="www.example.org"),
    ], "scan7-fixed")

    assert _outline_entries(elements) == [(0, "Corregidos desde el escaneo anterior", "scan7-fixed")]
    lines = [element.getPlainText() for element in elements if hasattr(element, "getPlainText")]
    assert any("Falta la cabecera <HSTS> (http:80, sitio www.example.org)" in line for line in lines)


def test_no_fixed_findings_means_no_section():
    from src.modules.features.themis.services.reports.findings import _append_fixed_section

    elements = []
    _append_fixed_section(_theme(), elements, [], "scan7-fixed")
    assert elements == []


def test_the_report_body_keeps_fixed_findings_out_of_the_cards_and_the_counts(monkeypatch):
    """Un «Corregido» no es un riesgo vivo: ni ficha, ni prioridad, ni total."""
    from types import SimpleNamespace
    from src.modules.infrastructure import session as session_module
    from src.modules.features.themis.managers import ComplianceManager, LybraEngineManager
    from src.modules.features.themis.services.reports import findings as report_module

    def row(title, state, fixed_reason=None):
        return SimpleNamespace(fixed_reason=fixed_reason,
            title=title, category="security_header", port=80, service="http", cpe=None, cve_ids=[],
            cvss_score=None, epss_score=None, in_kev=False, qod=90, confirmed=True,
            exploit_maturity=None, state=state, source="lybra", cpe_resolved=False,
            required_os=None, check_id="lybra:hsts@2", vhost=None, severity="MEDIUM",
        )
    rows = [row("Cabecera HSTS ausente", "open"), row("Cabecera X-Frame-Options ausente", "fixed"),
            row("Falta la cabecera Referrer-Policy", "fixed", fixed_reason="alias")]
    monkeypatch.setattr(session_module, "build_repository",
                        lambda _cls: SimpleNamespace(get_findings_by_scan=lambda _scan_id: rows))
    monkeypatch.setattr(LybraEngineManager, "exposure_for", staticmethod(lambda _scan: "public"))
    monkeypatch.setattr(ComplianceManager, "resolve_effective_frameworks", lambda _self, _user_id: [])
    monkeypatch.setattr(report_module, "enrich_with_cve_context", lambda _findings: None)
    monkeypatch.setattr(report_module, "_knowledge_base_line", lambda _scan: "NVD 2026-09-24")
    monkeypatch.setattr(report_module, "_failing_sources_line", lambda: None)

    from src.modules.features.themis.services.reports.lybra import LybraPrintingStrategy
    strategy = LybraPrintingStrategy.__new__(LybraPrintingStrategy)
    strategy.scan = _Scan()
    strategy.color_palette = _PALETTE
    elements = []
    strategy.append_body(_theme(), elements)

    texts = []
    for element in elements:
        if hasattr(element, "getPlainText"):
            texts.append(element.getPlainText())
        for cells in getattr(element, "_cellvalues", []):
            texts.append(" ".join(cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)
                                  for cell in cells))
    joined = "\n".join(texts)
    assert "Total de hallazgos: 1" in joined
    assert "Corregidos desde el escaneo anterior: 1" in joined
    assert "Hallazgo #1.1" in joined and "Hallazgo #1.2" not in joined
    assert "• Cabecera X-Frame-Options ausente (http:80)" in joined
    # Lo que deja de verse por una mejora del motor va aparte y no cuenta
    # como corregido: el cliente no ha hecho nada.
    assert "Ya no se reportan (mejoras del motor)" in joined
    assert "• Falta la cabecera Referrer-Policy (http:80)" in joined


def test_engine_dropped_findings_are_grouped_by_reason():
    from src.modules.features.themis.services.reports.findings import _append_dropped_section

    elements = []
    _append_dropped_section(_theme(), elements, [
        _finding(title="OpenSSH 9.6p1 — CVE-2024-6387", state="fixed", fixed_reason="backport"),
        _finding(title="Falta la cabecera CSP", state="fixed", fixed_reason="alias",
                 vhost="alias.example.org"),
    ], "scan7-dropped")

    assert _outline_entries(elements) == [(0, "Ya no se reportan (mejoras del motor)", "scan7-dropped")]
    lines = [element.getPlainText() for element in elements if hasattr(element, "getPlainText")]
    assert any(line.startswith("Descartados: la distribución ya los había corregido") for line in lines)
    assert any(line.startswith("El sitio resultó ser un alias") for line in lines)
    assert any("Falta la cabecera CSP (http:80, sitio alias.example.org)" in line for line in lines)


def test_the_report_warns_when_the_ip_hosts_other_webs():
    from src.modules.features.themis.lybra.correlation import DEFAULT_SITE_VHOST

    warning = _default_site_warning([{"vhost": DEFAULT_SITE_VHOST}, {"vhost": None}])

    assert "aloja varias webs" in warning
    assert "escanéala por su nombre" in warning
    assert _default_site_warning([{"vhost": "web.ejemplo.test"}, {}]) is None


# ────────────────────── la fila «Base de conocimiento»


def test_the_knowledge_base_line_is_the_one_the_scan_used():
    """La fila sale de la marca que guardó el escaneo, no del estado de hoy:
    regenerar el informe después de una sincronización no la cambia."""
    from datetime import datetime
    from types import SimpleNamespace
    from src.modules.features.themis.services.reports.findings import _knowledge_base_line

    scan = SimpleNamespace(
        kb_version="lybra-kb:nvd=2026-09-24,kev=2026-09-10,epss=2026-09-23,oval=none",
        started_at=datetime(2026, 9, 24, 18, 10))

    line = _knowledge_base_line(scan)

    assert line == ("NVD 2026-09-24 · KEV 2026-09-10 (desactualizada) · EPSS 2026-09-23 · "
                    "OVAL sin datos")


def test_a_scan_without_a_mark_says_so():
    from types import SimpleNamespace
    from src.modules.features.themis.services.reports.findings import _knowledge_base_line

    assert _knowledge_base_line(SimpleNamespace(kb_version=None, started_at=None)).startswith("No consta")


def test_the_failing_sources_row_says_which_and_why(monkeypatch):
    from src.modules.features.themis.managers import kb_sync
    from src.modules.features.themis.services.reports.findings import _failing_sources_line

    monkeypatch.setattr(kb_sync.KbSyncManager, "status", lambda self: {"sources": [
        {"source": "nvd", "error": None, "lastSuccessAt": "2026-09-25T03:07:26Z"},
        {"source": "oval:ubuntu:22.04", "error": "ValueError: no es una URL", "lastSuccessAt": None},
        {"source": "kev", "error": "HTTPError: 503", "lastSuccessAt": "2026-09-20T03:00:01Z"},
    ]})

    assert _failing_sources_line() == (
        "oval:ubuntu:22.04 (no ha terminado bien nunca): ValueError: no es una URL; "
        "kev (sin éxito desde 2026-09-20): HTTPError: 503")


def test_key_value_cells_wrap_instead_of_overflowing():
    """Una cadena suelta en una celda de ReportLab no salta de línea: se sale
    de la columna. Como párrafo, sí salta; y se escapa, porque es texto y no
    marcado."""
    from reportlab.platypus import Paragraph

    table = _theme().kv_table([["Corregidos desde el escaneo anterior:", "<3 & 4>"]], [72, 144])
    key, value = table._cellvalues[0]

    assert isinstance(key, Paragraph) and isinstance(value, Paragraph)
    assert value.getPlainText() == "<3 & 4>"
    _, height = table.wrap(216, 1000)
    assert height > 20, "la etiqueta larga ocupa dos líneas en su columna"
