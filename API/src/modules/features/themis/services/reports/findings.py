"""
``FindingsPrintingStrategy``: base compartida por los tipos de escaneo que
viven enteramente en ``Finding`` (Lybra y Nuclei).
"""

import logging
from datetime import date
from typing import Dict, Optional
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import CondPageBreak, Paragraph, Spacer, Table, TableStyle
import src.modules.system.config_reading as CR

from src.modules.tools.press import ColorType, build_palette, safe_markup
from ...lybra.compliance import load_compliance_catalog, map_finding_compliance
from ...lybra.correlation import DEFAULT_SITE_VHOST
from ...lybra.grouping import build_service_rollup
from ...lybra.kb import KB_MARK_SOURCES, parse_kb_feed_version
from ..cve_context import enrich_with_cve_context
from .base import PrintingStrategy
from .outline import OutlineEntry

logger = logging.getLogger(__name__)


class FindingsPrintingStrategy(PrintingStrategy):
    """Shared PDF renderer for scan types whose data lives entirely in the
    unified `Finding` table rather than a tool-specific incident/vulnerability
    model — Lybra originally, and now Nuclei.

    Extracted from what used to be a single, Lybra-only class: Nuclei's JSONL
    output maps onto `Finding` almost as completely as Lybra's own engine does
    (`cve_ids`, `cvss_score`, `check_id` all populated — see
    `lybra/adapters.py::nuclei_result_to_finding`), so its PDF is "the exact
    same card renderer, a different identity and palette" rather than a fourth
    near-duplicate `PrintingStrategy`. A subclass fixes the small set of class
    attributes below; everything else — fetching findings via the repository
    (neither `LybraScan` nor `NucleiScan` carries an ORM relationship to
    `Finding`), scoring, sorting, the summary table, the CVE-context
    enrichment and the per-finding card — is identical.

    Cards are sorted by the same `priority` ladder the web UI uses, computed
    the same way (`score_finding`), so the PDF and the web view never
    disagree.

    Subclass contract (all required, no defaults — each identity must be a
    deliberate choice, not an inherited accident):
        _TOOL:              ``ScanType`` member, for ``CR.get_tool_color_palette``.
        _WRITER_CLASS:       AI writer class to instantiate (both tools reuse
                             ``LybraAIWriter`` today — its logic only reads
                             already-structured findings, nothing Lybra-specific).
        _WRITER_PROMPT_KEY:  Which ``SecOpsConfig.json`` prompt pair to read
                             (``"lybra"`` / ``"nuclei"``).
        _OWN_SOURCE:         This tool's own ``Finding.source`` value, so a
                             finding corroborated by *another* scanner is
                             correctly flagged ("Corroborado por: ...") instead
                             of always comparing against the literal "lybra".
        _HEADER_TITLE:       In-body report title (``theme.title`` paragraph).
        _REPORT_TITLE:       PDF metadata / cover title (``get_report_title``).
        _FILENAME_SUFFIX:    Download filename suffix (``get_filename_suffix``).
        _LOGO_FILENAME:      Logo file in ``features/themis/resources/``
                             (``get_logo_filename``).
        _DEFAULT_PALETTE:    Fallback color dict when ``SecOpsConfig.json``
                             carries no ``colorPalette`` for ``_TOOL``.
        _SHOWS_COMPLIANCE:   Si el informe traduce cada hallazgo a técnicas de
                             MITRE ATT&CK y a los controles de los marcos de
                             cumplimiento del dueño del escaneo. Es exclusivo
                             del motor propio: sólo Lybra lo activa.

    Attributes:
        writer: ``_WRITER_CLASS`` instance for AI analysis.
        color_palette: This tool's color palette for the report.
    """

    _PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    _PRIORITY_LABEL = {"CRITICAL": "CRÍTICA", "HIGH": "ALTA", "MEDIUM": "MEDIA", "LOW": "BAJA", "INFO": "INFO"}
    _STATE_LABEL = {"open": "Abierto", "fixed": "Corregido", "regressed": "Regresado", "accepted": "Aceptado"}

    # Bare annotations, no defaults on purpose (see the "Subclass contract"
    # docstring above): each subclass must set every one of these explicitly,
    # the same way ScanManager._MODEL/_RICH_LOADER declare the contract a
    # concrete subclass fills in. Declaring them here (rather than leaving
    # them only in prose) is what lets static analysis resolve `self._TOOL`
    # etc. inside this class's own methods.
    _TOOL: "ScanType"
    _WRITER_CLASS: type
    _WRITER_PROMPT_KEY: str
    _OWN_SOURCE: str
    _HEADER_TITLE: str
    _REPORT_TITLE: str
    _FILENAME_SUFFIX: str
    _LOGO_FILENAME: str
    _DEFAULT_PALETTE: Dict[str, str]
    _SHOWS_COMPLIANCE: bool

    # Los marcos de cumplimiento del dueño del escaneo; los fija `append_body`.
    # Vacío por defecto para que una ficha pintada fuera de él no los necesite.
    _frameworks: tuple = ()

    def __init__(self, scan) -> None:
        """Initialize the printing strategy.

        Args:
            scan: LybraScan or NucleiScan instance to generate the report from.
        """
        super().__init__(scan)
        self.color_palette = build_palette(
            CR.get_tool_color_palette(self._TOOL), self._DEFAULT_PALETTE
        )

    def _make_writer(self):
        """El writer de IA de Lybra/Nuclei, construido al primer uso (ver base)."""
        return self._WRITER_CLASS(prompt_key=self._WRITER_PROMPT_KEY)

    def append_body(self, theme: "ReportTheme", elements: list, ai_report: bool = False) -> None:
        from src.modules.infrastructure.session import build_repository
        from src.modules.features.themis import ScanRepository
        from src.modules.features.themis.lybra import is_unverified_distro_package, score_finding
        # Diferido como el resto de imports de esta función: `managers` importa
        # `services`, así que a nivel de módulo sería un ciclo.
        from src.modules.features.themis.managers import LybraEngineManager

        rows = build_repository(ScanRepository).get_findings_by_scan(self.scan.id)
        exposure = LybraEngineManager.exposure_for(self.scan)

        findings = [{
            "title": row.title, "category": row.category, "port": row.port, "service": row.service,
            "cpe": row.cpe, "cve_ids": row.cve_ids or [], "cvss_score": row.cvss_score,
            "epss_score": row.epss_score, "in_kev": row.in_kev, "qod": row.qod, "confirmed": row.confirmed,
            "exploit_maturity": row.exploit_maturity, "state": row.state,
            "source": row.source, "state": row.state, "cpe_resolved": row.cpe_resolved,
            "required_os": row.required_os, "check_id": row.check_id, "vhost": row.vhost,
            "severity": row.severity, "fixed_reason": row.fixed_reason,
        } for row in rows]
        # Los sitios con nombre que sirve la IP no son riesgos: van en su
        # propia sección, no entre las fichas ni en los recuentos.
        sites = [finding for finding in findings if finding["category"] == "virtual_host"]
        findings = [finding for finding in findings if finding["category"] != "virtual_host"]
        # Lo que el escaneo anterior vio y éste ya no ve tampoco es un riesgo
        # vivo: va en su propia sección al final, sin prioridad y fuera de los
        # recuentos. Mezclado con los abiertos, el mismo problema salía dos
        # veces y el total se inflaba.
        # Un «corregido» que sale de una mejora del motor (la distribución ya
        # lo había parcheado, o su sitio es un alias) no es trabajo del
        # cliente: va aparte y no cuenta como corregido.
        fixed_findings = [finding for finding in findings
                          if finding.get("state") == "fixed" and not finding.get("fixed_reason")]
        dropped_findings = [finding for finding in findings
                            if finding.get("state") == "fixed" and finding.get("fixed_reason")]
        findings = [finding for finding in findings if finding.get("state") != "fixed"]
        for finding in findings:
            finding["priority"] = score_finding(finding, exposure)
            finding["is_unverified_distro_package"] = is_unverified_distro_package(finding)
        enrich_with_cve_context(findings)
        if self._SHOWS_COMPLIANCE:
            self._frameworks = _effective_frameworks(self.scan.user_id)
            keys = [framework.key for framework in self._frameworks]
            for finding in findings:
                finding["compliance"] = map_finding_compliance(finding["category"], finding["check_id"], keys)

        self._append_finding_header(theme, elements, findings, exposure, len(fixed_findings))
        _append_sites_section(theme, elements, sites)

        if findings:
            self._append_finding_summary(theme, elements, findings)
        self._append_cpe_coverage_note(theme, elements, findings)

        self._append_findings_section(theme, elements, findings)
        if self._SHOWS_COMPLIANCE:
            _append_compliance_section(theme, elements, findings, self._frameworks,
                                       self.color_palette, self._outline_key("compliance"))
        _append_fixed_section(theme, elements, fixed_findings, self._outline_key("fixed"))
        _append_dropped_section(theme, elements, dropped_findings, self._outline_key("dropped"))

        if ai_report:
            # La misma lista que imprime las fichas: ya priorizada por
            # `score_finding` y ya enriquecida con descripción y versión
            # corregida. Así el análisis puede recomendar la versión destino
            # concreta y no puede contradecir al cuerpo del informe.
            self._append_ai_analysis(elements, theme, findings=findings)

        # ponytail: no per-target history chart yet — _append_history_stats'
        # tool_map only knows the Nmap/Nikto scan classes, since it relies on
        # a MetricExtractor for each; a Finding-based one is separate scope
        # from wiring the PDF itself. Add it when that's needed.

    def _append_finding_header(
        self, theme: "ReportTheme", elements: list, findings: list, exposure: str, fixed_count: int = 0,
    ) -> None:
        """Cabecera del informe: título y tablas de objetivo y escaneo.

        Args:
            theme: El tema del informe.
            elements: La lista de elementos del documento; se amplía en sitio.
            findings: Los hallazgos vivos del escaneo, sin los corregidos.
            exposure: ``"public"``, ``"private"`` o cualquier otro valor
                (se muestra como «Desconocida»).
            fixed_count: Cuántos hallazgos del escaneo anterior ya no
                aparecen. Se dice en una fila propia, fuera del total. Por
                defecto ``0``, que no añade la fila.
        """
        scan = self.scan

        elements.append(Paragraph(self._HEADER_TITLE, theme.title))
        elements.append(Spacer(1, 0.1 * inch))

        # Van antes que ninguna tabla porque cambian cómo se leen todas: el
        # primero señala los hallazgos que más fácilmente resultan falsos, y el
        # segundo, lo que el escaneo no ha podido mirar.
        for warning in (_unverified_warning(findings), _default_site_warning(findings)):
            if warning:
                elements.append(Paragraph(warning, theme.body))
                elements.append(Spacer(1, 0.1 * inch))

        exposure_label = "Pública" if exposure == "public" else "Privada" if exposure == "private" else "Desconocida"
        target_info = [
            ["Objetivo:", str(getattr(scan, "target", ""))],
            ["Exposición:", exposure_label],
        ]
        # Sólo Lybra tiene perfil de escaneo (fast/standard/thorough); los
        # otros tres escáneres, que comparten esta misma clase base, no
        # traen la columna y `getattr` lo trata como "no aplica" en vez de
        # imprimir un valor inventado.
        profile = getattr(scan, "profile", None)
        if profile is not None:
            profile_label = {
                "fast": "Rápido", "standard": "Estándar", "thorough": "Exhaustivo",
            }.get(profile, profile)
            target_info.append(["Perfil de escaneo:", profile_label])
        target_table = theme.kv_table(target_info, col_widths=[2 * inch, 4 * inch])
        elements.append(target_table)
        elements.append(Spacer(1, 0.1 * inch))

        started = getattr(scan, "started_at", None)
        started_str = started.strftime("%d/%m/%Y %H:%M:%S") if started else "N/A"
        confirmed_count = sum(1 for finding in findings if finding["confirmed"]
                              and finding.get("state") != "false_positive")
        refuted_count = sum(1 for finding in findings
                            if finding.get("state") == "false_positive")

        scan_info = [
            ["ID del escaneo:", str(getattr(scan, "id", ""))],
            ["Fecha de inicio:", started_str],
            ["Total de hallazgos:", str(len(findings))],
            ["Confirmados activamente:", str(confirmed_count)],
            ["Base de conocimiento:", _knowledge_base_line(scan)],
        ]
        failing_sources = _failing_sources_line()
        if failing_sources:
            scan_info.append(["Fuentes que fallan hoy:", failing_sources])
        if getattr(scan, "is_partial", False):
            # Un escaneo parcial no puede leerse como uno limpio: lo que no se
            # llegó a comprobar no está ausente, es desconocido.
            scan_info.append(["Cobertura:",
                              "Parcial: el escaneo no llegó a cubrir todo el objetivo"])
        if refuted_count:
            # Se dice, no se esconde: que el informe no los cuente como riesgo
            # es correcto, pero callar cuántos hay ocultaría que alguien
            # intervino sobre lo que el motor detectó.
            scan_info.append(["Desmentidos por el usuario:", str(refuted_count)])
        if fixed_count:
            scan_info.append(["Corregidos desde el escaneo anterior:", str(fixed_count)])
        info_table = theme.kv_table(scan_info, col_widths=[2 * inch, 4 * inch])
        elements.append(info_table)
        elements.append(Spacer(1, 0.3 * inch))

    #: Cómo se lee cada nivel de ``Finding.exploit_maturity`` en el informe.
    #: ``none`` no aparece: decir "no consta exploit" en cada ficha sería ruido
    #: en la inmensa mayoría de los hallazgos, y su ausencia ya lo dice.
    _EXPLOIT_MATURITY_LABEL = {
        "poc": "Existe una prueba de concepto pública",
        "functional": "Existe un exploit funcional público",
        "weaponized": "Existe un exploit integrado en herramientas de ataque",
        "in_the_wild": "Se explota activamente en el mundo real",
    }

    def _append_finding_summary(self, theme: "ReportTheme", elements: list, findings: list) -> None:
        """Tabla resumen: cantidad de hallazgos por prioridad."""
        palette = self.color_palette
        dark = colors.HexColor(palette[ColorType.DARK])
        white = colors.HexColor(palette[ColorType.WHITE])

        elements.append(Paragraph("Resumen por prioridad", theme.subtitle))
        elements.append(Spacer(1, 0.1 * inch))

        counts: Dict[str, int] = {}
        for finding in findings:
            if finding.get("state") == "false_positive":
                # El usuario ha desmentido este hallazgo: no es un riesgo, y un
                # resumen que lo cuente afirma una postura de seguridad peor
                # que la real.
                continue
            counts[finding["priority"]] = counts.get(finding["priority"], 0) + 1

        data = [["Prioridad", "Cantidad"]]
        for prio in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            if prio not in counts:
                continue
            data.append([self._PRIORITY_LABEL[prio], str(counts[prio])])

        table = Table(data, colWidths=[3 * inch, 2 * inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette[ColorType.SECONDARY])),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), white),
            ("TEXTCOLOR", (0, 1), (-1, -1), dark),
            ("ALIGN", (0, 1), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.4, dark),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3 * inch))

    def _append_cpe_coverage_note(self, theme: "ReportTheme", elements: list, findings: list) -> None:
        """Advierte cuando el matcher no pudo identificar parte del inventario.

        Un escaneo por inventario emite un hallazgo ``installed_package`` por
        **cada** paquete, se le haya podido resolver un CPE o no.
        ``Finding.cpe_resolved`` distingue exactamente cuántos de los
        paquetes inventariados no se pudieron ni identificar contra el
        catálogo CPE — la KB local puede seguir sin tener CVEs para los que
        sí se resolvieron, pero eso no es ambiguo, es "comprobado y sin
        hallazgos".
        """
        packages = sum(1 for finding in findings if finding["category"] == "installed_package")
        unresolved = sum(
            1 for finding in findings
            if finding["category"] == "installed_package" and finding.get("cpe_resolved") is False
        )
        if not packages or not unresolved:
            return

        note_style = ParagraphStyle(
            "CpeCoverageNote", parent=theme.body, textColor=colors.HexColor("#8a6d1f"),
            backColor=colors.HexColor("#fff8e1"), borderColor=colors.HexColor("#e0c34a"),
            borderWidth=0.75, borderPadding=6, alignment=TA_LEFT,
        )
        elements.append(Paragraph(
            f"<b>Nota de cobertura:</b> {unresolved} de los {packages} paquetes inventariados no se "
            "pudieron identificar contra el catálogo de vulnerabilidades (nombre de producto sin "
            "resolución conocida), así que no se comprobaron. El resto sí se comprobó — su ausencia "
            "de hallazgos es una verificación real, no una laguna.",
            note_style,
        ))
        elements.append(Spacer(1, 0.25 * inch))

    # Las dos clases de trabajo en que se parten los grupos, en el orden en
    # que se imprimen. Son los mismos títulos que usa la interfaz web
    # (`LybraResults.vue`), a propósito: quien mira la pantalla y quien lee el
    # PDF tienen que estar hablando del mismo sitio.
    _GROUP_SECTIONS = (
        ("prod", "Productos afectados", True),
        ("conf", "Configuración y exposición", False),
    )

    def _outline_key(self, suffix: str) -> str:
        """Clave de un marcador, única dentro del documento.

        Lleva el escaneo delante porque un mismo informe podría llegar a
        arrastrar bloques de más de un origen; sin eso, dos grupos homónimos
        anclarían al mismo destino y el índice mandaría al sitio equivocado.
        """
        return f"scan{getattr(self.scan, 'id', 0)}-{suffix}"

    def _append_findings_section(self, theme: "ReportTheme", elements: list, findings: list) -> None:
        """El bloque «Hallazgos» completo: su rama del índice, su título y su cuerpo.

        Los tres niveles del árbol de marcadores —«Hallazgos», la sección y el
        grupo— los emite este método y no dos repartidos, porque ReportLab
        rechaza un nivel que salte más de uno respecto al anterior: si la raíz
        la pusiera el llamante, el subárbol sólo sería válido cuando alguien se
        acordara de emitirla antes, y el precio de olvidarlo no es un índice
        raro sino un informe que no se genera.
        """
        elements.append(OutlineEntry("Hallazgos", key=self._outline_key("findings"), level=0))
        elements.append(Paragraph("Hallazgos", theme.subtitle))
        elements.append(Spacer(1, 0.1 * inch))

        if not findings:
            elements.append(Paragraph(
                "El escaneo no llegó a cubrir todo el objetivo: la ausencia de hallazgos "
                "no es un resultado limpio." if getattr(self.scan, "is_partial", False)
                else "El motor no detectó ningún hallazgo para este objetivo.", theme.info))
            return

        self._append_grouped_findings(theme, elements, findings)

    def _append_grouped_findings(self, theme: "ReportTheme", elements: list, findings: list) -> None:
        """Imprimir los hallazgos por unidad remediable, no en lista plana.

        Un escaneo contra un host con dos productos desactualizados puede dar
        150 hallazgos, y ciento cincuenta fichas seguidas confunden la cantidad
        de *evidencia* con la cantidad de *trabajo*: son dos acciones —subir
        dos productos de versión— más un puñado de cosas de configuración que
        se arreglan de otra manera.

        La agrupación no se calcula aquí: `build_service_rollup` ya existía en
        la capa pura y la interfaz web ya la pintaba. Lo llamativo es que el
        informe la tenía delante —la usa desde hace tiempo para armar el
        prompt del análisis de IA— y aun así imprimía plano. El resultado era
        un informe donde la IA recomendaba «actualiza Apache y cierras 12
        CVEs» y tres páginas más abajo esos 12 CVEs aparecían como fichas
        inconexas.
        """
        sections = self._split_into_sections(build_service_rollup(findings))

        self._append_group_index(theme, elements, sections)

        position = 0
        for section_key, section_title, groups in sections:
            elements.append(CondPageBreak(2 * inch))
            elements.append(OutlineEntry(
                section_title, key=self._outline_key(f"section-{section_key}"), level=1))
            elements.append(Paragraph(section_title, theme.subtitle))
            elements.append(Spacer(1, 0.12 * inch))

            for group in groups:
                position += 1
                elements.append(OutlineEntry(
                    f"{group.label} ({group.total_findings})",
                    key=self._outline_key(f"group-{position}"),
                    level=2,
                ))
                self._append_group_header(theme, elements, group, position)

                for idx, finding in enumerate(self._sorted_findings(group.findings), start=1):
                    self._append_finding_card(theme, elements, finding, f"{position}.{idx}")

    def _split_into_sections(self, groups: list) -> list:
        """Repartir los grupos entre producto y configuración, sin los vacíos.

        Un objetivo puede no tener ningún producto identificado (o ninguna
        configuración señalada), y en ese caso imprimir el título de una
        sección para no colgarle nada debajo se lee como si faltara algo.

        Returns:
            Tuplas ``(clave, título, grupos)`` de las secciones con contenido.
        """
        sections = []
        for key, title, wants_products in self._GROUP_SECTIONS:
            matching = [group for group in groups if group.is_product is wants_products]
            if matching:
                sections.append((key, title, matching))
        return sections

    def _sorted_findings(self, findings: list) -> list:
        """Priority first (the contextual CVSS+EPSS+KEV+exposure synthesis
        that is Lybra's whole value proposition); raw CVSS only breaks ties
        *within* the same priority band, confirmed findings before
        hypotheses. Este orden se aplica dentro de cada grupo, no sobre la
        lista entera."""
        return sorted(
            findings,
            key=lambda finding: (
                self._PRIORITY_ORDER.get(finding["priority"], 5),
                not finding["confirmed"],
                -(finding["cvss_score"] or 0),
            ),
        )

    def _append_group_index(self, theme: "ReportTheme", elements: list, sections: list) -> None:
        """Tabla-índice: todo el trabajo pendiente junto, antes del detalle.

        Es la mitad de la respuesta a «que se pueda plegar para leer mejor»
        que sí cabe dentro de la página (la otra mitad es el árbol de
        marcadores del visor). Quien recibe el informe ve de un vistazo
        cuántas acciones hay y cuáles son, y sólo baja al detalle de las que
        le interesan.
        """
        palette = self.color_palette
        dark = colors.HexColor(palette[ColorType.DARK])
        white = colors.HexColor(palette[ColorType.WHITE])

        elements.append(Paragraph("Índice de grupos", theme.subtitle))
        elements.append(Spacer(1, 0.1 * inch))

        cell = ParagraphStyle("GroupIndexCell", parent=theme.body, fontSize=8,
                              leading=10, alignment=TA_LEFT, spaceAfter=0)
        data = [["#", "Unidad a remediar", "Prioridad", "Hallazgos", "CVEs", "Acción"]]
        position = 0
        for _, _, groups in sections:
            for group in groups:
                position += 1
                action = (f"Actualizar a {group.fixed_version} o superior"
                          if group.fixed_version else "Revisar configuración")
                data.append([
                    str(position),
                    Paragraph(safe_markup(group.label), cell),
                    self._PRIORITY_LABEL.get(group.worst_priority, group.worst_priority),
                    str(group.total_findings),
                    str(group.total_cves),
                    Paragraph(safe_markup(action), cell),
                ])

        table = Table(data, colWidths=[0.3 * inch, 2.1 * inch, 0.75 * inch,
                                       0.75 * inch, 0.5 * inch, 1.6 * inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette[ColorType.SECONDARY])),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("BACKGROUND", (0, 1), (-1, -1), white),
            ("TEXTCOLOR", (0, 1), (-1, -1), dark),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (4, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.4, dark),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.25 * inch))

    def _append_group_header(self, theme: "ReportTheme", elements: list, group, position: int) -> None:
        """Cabecera de un grupo: qué es, cuánto pesa y qué hay que hacer con él.

        La línea que de verdad importa es `fixed_version`: es la cota más alta
        del grupo, así que actualizar hasta ahí cierra también todas las
        inferiores — un solo movimiento para todos los hallazgos de debajo.
        """
        palette = self.color_palette
        dark = colors.HexColor(palette[ColorType.DARK])
        light = colors.HexColor(palette[ColorType.LIGHT])

        elements.append(CondPageBreak(2.2 * inch))

        where = f"{group.service or 'svc'}:{group.port}" if group.port else "—"
        title = Paragraph(
            f"Grupo #{position} · {safe_markup(group.label)}",
            ParagraphStyle("GroupTitle", parent=theme.styles["Normal"], fontName="Helvetica-Bold",
                           fontSize=9.5, textColor=dark, alignment=TA_LEFT),
        )
        heading = Table([[title, where]], colWidths=[4.6 * inch, 1.4 * inch])
        heading.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), light),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (1, 0), (1, -1), 8.5),
            ("TEXTCOLOR", (1, 0), (1, -1), dark),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("BOX", (0, 0), (-1, -1), 0.6, dark),
        ]))
        elements.append(heading)

        confirmed_plural = "" if group.confirmed_count == 1 else "s"
        rows = [
            ["Prioridad del grupo:",
             self._PRIORITY_LABEL.get(group.worst_priority, group.worst_priority)],
            ["Hallazgos:",
             f"{group.total_findings} ({group.confirmed_count} comprobado{confirmed_plural})"],
        ]
        if group.total_cves:
            rows.append(["CVEs distintos:", str(group.total_cves)])
        if group.kev_cve_ids:
            rows.append(["En CISA KEV:",
                         f"{len(group.kev_cve_ids)} — explotación activa confirmada"])
        if group.max_cvss is not None:
            rows.append(["CVSS máximo:", str(group.max_cvss)])
        if group.max_epss is not None:
            rows.append(["EPSS máximo (30 días):", f"{group.max_epss * 100:.1f}%"])
        if group.fixed_version:
            rows.append(["Cierra el grupo:",
                         f"actualizar a {group.fixed_version} o superior"])

        summary = Table(rows, colWidths=[1.7 * inch, 4.3 * inch])
        summary.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9f9f9")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(palette[ColorType.BLACK])),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ]))
        elements.append(summary)
        elements.append(Spacer(1, 0.12 * inch))

    def _append_finding_card(self, theme: "ReportTheme", elements: list, finding: dict, label: str) -> None:
        """Tarjeta de un hallazgo: cabecera de prioridad, nombre, detalles,
        descripción y referencias (mismo lenguaje visual que Nmap/Nikto:
        cada bloque lleva su propio borde, no solo la cabecera)."""
        severity_bg = {
            "CRITICAL": colors.HexColor("#ffcccc"),
            "HIGH": colors.HexColor("#ffe6cc"),
            "MEDIUM": colors.HexColor("#fff4cc"),
            "LOW": colors.HexColor("#e6f7ff"),
            "INFO": colors.HexColor("#f0f0f0"),
        }
        palette = self.color_palette
        main = colors.HexColor(palette[ColorType.MAIN])
        dark = colors.HexColor(palette[ColorType.DARK])
        border = colors.HexColor("#dddddd")
        prio = finding["priority"]
        bgcolor = severity_bg.get(prio, severity_bg["INFO"])

        elements.append(CondPageBreak(2.5 * inch))

        confirmed_text = "Comprobado" if finding["confirmed"] else "Potencial"
        header = theme.severity_header_table(
            left_text=f"Hallazgo #{label}: {self._PRIORITY_LABEL.get(prio, prio)}",
            right_text=confirmed_text,
            bg_color=bgcolor,
        )
        elements.append(header)

        # Título en banda de color principal, mismo lenguaje visual que las demás tarjetas.
        title_para = Paragraph(finding["title"], ParagraphStyle(
            "LybraFindingTitle", parent=theme.styles["Normal"], fontName="Helvetica-Bold",
            fontSize=10, textColor=colors.whitesmoke, alignment=TA_LEFT,
        ))
        title_table = Table([[title_para]], colWidths=[6 * inch])
        title_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), main),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.6, dark),
        ]))
        elements.append(title_table)

        details = []
        if finding.get("port"):
            details.append(["Puerto/servicio:", f"{finding.get('service') or '?'}:{finding['port']}"])
        if finding.get("vhost"):
            details.append(["Sitio:", finding["vhost"]])
        if finding.get("cve_ids"):
            details.append(["CVE:", ", ".join(finding["cve_ids"])])
        if finding.get("cwe_ids"):
            details.append(["CWE:", ", ".join(finding["cwe_ids"])])
        if finding.get("cvss_score") is not None:
            details.append(["CVSS:", str(finding["cvss_score"])])
        if finding.get("epss_score") is not None:
            details.append(["EPSS (30 días):", f"{finding['epss_score'] * 100:.1f}%"])
        if finding.get("in_kev"):
            details.append(["CISA KEV:", "Sí — explotada activamente"])
        # La tercera dimensión de explotabilidad, junto a KEV y EPSS: si existe
        # algo público que demuestre el fallo. Es lo que separa una urgencia de
        # un deber cuando el lector decide qué arregla el lunes.
        maturity_label = self._EXPLOIT_MATURITY_LABEL.get(finding.get("exploit_maturity"))
        if maturity_label:
            details.append(["Explotación:", maturity_label])
        if finding.get("required_os") and not finding.get("confirmed"):
            details.append(["Requiere SO:", f"{finding['required_os']} (no verificado en este escaneo)"])
        if finding.get("is_unverified_distro_package"):
            details.append(["Sin contrastar:", "paquete de distribución; puede estar corregido "
                                               "sin cambiar la versión (backport)"])
        if finding.get("fixed_version"):
            details.append(["Corregido en:", f"{finding['fixed_version']} o superior"])
        if finding.get("state") and finding["state"] != "open":
            details.append(["Estado:", self._STATE_LABEL.get(finding["state"], finding["state"])])
        if finding.get("source") and finding["source"] != self._OWN_SOURCE:
            details.append(["Corroborado por:", finding["source"]])
        details.extend(_compliance_rows(theme, finding.get("compliance"), self._frameworks))

        if details:
            detail_table = Table(details, colWidths=[1.7 * inch, 4.3 * inch])
            detail_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9f9f9")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(palette[ColorType.BLACK])),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, border),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            elements.append(detail_table)

        description = finding.get("description")
        if description:
            text = description[:450] + ("..." if len(description) > 450 else "")
            desc_style = ParagraphStyle(
                "LybraFindingDesc", parent=theme.body, fontSize=8.5, leading=11.5,
            )
            para = Paragraph(f"Qué implica: {safe_markup(text)}", desc_style)
            desc_table = Table([[para]], colWidths=[6 * inch])
            desc_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("BOX", (0, 0), (-1, -1), 0.4, border),
            ]))
            elements.append(desc_table)

        elements.append(Spacer(1, 0.2 * inch))

    def get_filename_suffix(self) -> str:
        return self._FILENAME_SUFFIX

    def get_logo_filename(self) -> str:
        """Get the logo filename declared by the subclass in ``_LOGO_FILENAME``.

        Returns:
            str: Bare filename inside ``features/themis/resources/``.
        """
        return self._LOGO_FILENAME

    def get_report_title(self) -> str:
        return self._REPORT_TITLE


def _append_sites_section(theme: "ReportTheme", elements: list, sites: list) -> None:
    """La sección «Sitios detectados en esta IP», si el escaneo descubrió alguno.

    Un escaneo por IP audita además los sitios con nombre que la propia IP
    delata (sus certificados, su DNS inverso). El lector necesita saber cuáles
    son y de dónde salió cada nombre para leer la fila «Sitio» de las fichas.

    Args:
        theme: El tema del informe.
        elements: La lista de elementos del documento; se amplía en sitio.
        sites: Los avisos ``virtual_host`` del escaneo; vacía, no se añade nada.
    """
    if not sites:
        return
    elements.append(Paragraph("Sitios detectados en esta IP", theme.subtitle))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        "Además del sitio por defecto de la IP, se auditaron por separado estos "
        "sitios con nombre, que resuelven a la misma IP. Los que sirven la misma "
        "página que el sitio por defecto no se auditan aparte:", theme.body))
    for site in sites:
        elements.append(Paragraph(f"• {site['title']}", theme.body))
    elements.append(Spacer(1, 0.3 * inch))


def _append_fixed_section(theme: "ReportTheme", elements: list, fixed_findings: list, outline_key: str) -> None:
    """La sección «Corregidos desde el escaneo anterior», si hay alguno.

    Son hallazgos que el escaneo anterior del mismo objetivo vio y éste ya no.
    Se listan en una línea cada uno, sin prioridad ni ficha: ya no son un
    riesgo, y darles el mismo formato que a los abiertos los hacía pasar por
    uno más.

    Args:
        theme: El tema del informe.
        elements: La lista de elementos del documento; se amplía en sitio.
        fixed_findings: Los hallazgos con ``state="fixed"``; vacía, no se
            añade nada.
        outline_key: La clave del marcador de la sección en el índice del PDF.
    """
    if not fixed_findings:
        return
    title = "Corregidos desde el escaneo anterior"
    elements.append(CondPageBreak(1.5 * inch))
    elements.append(OutlineEntry(title, key=outline_key, level=0))
    elements.append(Paragraph(title, theme.subtitle))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        "El escaneo anterior de este objetivo los detectó y éste ya no. No cuentan en "
        "el total ni en el resumen por prioridad.", theme.body))
    for finding in fixed_findings:
        where = f"{finding.get('service') or 'servicio'}:{finding['port']}" if finding.get("port") else ""
        if finding.get("vhost"):
            where += f", sitio {finding['vhost']}"
        suffix = f" ({safe_markup(where)})" if where else ""
        elements.append(Paragraph(f"• {safe_markup(finding['title'])}{suffix}", theme.body))
    elements.append(Spacer(1, 0.3 * inch))


#: Cómo se llama cada fuente de la base de conocimiento en el informe.
_KB_SOURCE_LABEL = {"nvd": "NVD", "kev": "KEV", "epss": "EPSS", "oval": "OVAL"}


def _knowledge_base_line(scan) -> str:
    """Contra qué fecha de cada fuente de la base de conocimiento se resolvió el escaneo.

    Sale de la marca que el escaneo guardó al empezar (``LybraScan.kb_version``),
    no del estado actual de la base de conocimiento: un informe regenerado días
    después no puede afirmar que usó datos que todavía no existían, ni callar
    los que sí usó. La detección por versión —la que produce la mayoría de los
    hallazgos con CVE— vale exactamente lo que valga la frescura de ese espejo,
    así que una fuente que ya pasaba de su antigüedad máxima cuando se escaneó
    se marca como desactualizada.

    Args:
        scan: El escaneo del informe. Se lee su ``kb_version`` (ausente en
            escáneres que no son Lybra) y su ``started_at``.

    Returns:
        str: ``"NVD 2026-09-24 · KEV 2026-09-22 · EPSS 2026-09-23 · OVAL
            2026-09-24"``, con ``sin datos`` en una fuente vacía y
            ``(desactualizada)`` en una que ya estaba vieja; o una frase que
            dice que no consta, si el escaneo es anterior a que se guardara la
            marca.
    """
    dates = parse_kb_feed_version(getattr(scan, "kb_version", None))
    if dates is None:
        return "No consta: el escaneo es anterior a que se registrara"
    max_age = CR.knowledge_base_config().max_age_days
    started = getattr(scan, "started_at", None)
    parts = []
    for source in KB_MARK_SOURCES:
        if source not in dates:
            continue
        label = _KB_SOURCE_LABEL.get(source, source.upper())
        day = dates[source]
        if day is None:
            parts.append(f"{label} sin datos")
            continue
        is_stale = (started is not None and max_age.get(source) is not None
                    and (started.date() - date.fromisoformat(day)).days > max_age[source])
        parts.append(f"{label} {day}" + (" (desactualizada)" if is_stale else ""))
    return " · ".join(parts)


def _failing_sources_line() -> Optional[str]:
    """Qué fuentes de la base de conocimiento fallan al sincronizarse, y por qué.

    Es el estado **de hoy**, no el del escaneo, y por eso va en una fila aparte
    de «Base de conocimiento»: sirve para que quien lee el informe sepa que una
    fuente lleva tiempo sin actualizarse y el motivo, que de otro modo sólo
    queda en el registro del servidor. OVAL aparece por distribución, que es
    como se sincroniza y como falla. Best-effort: un fallo leyendo el estado no
    puede impedir que se emita el informe.

    Returns:
        Optional[str]: ``"oval:ubuntu:22.04 (sin éxito desde 2026-09-20):
            <motivo>"``, una entrada por fuente separadas por ``;``; o ``None``
            si ninguna falla o no se pudo consultar.
    """
    from src.modules.features.themis.managers.kb_sync import KbSyncManager

    try:
        status = KbSyncManager().status()
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo leer el estado de la base de conocimiento")
        return None
    parts = []
    for entry in status["sources"]:
        if not entry["error"]:
            continue
        since = (entry["lastSuccessAt"] or "")[:10]
        when = f"sin éxito desde {since}" if since else "no ha terminado bien nunca"
        reason = entry["error"] if len(entry["error"]) <= 120 else entry["error"][:117] + "..."
        parts.append(f"{entry['source']} ({when}): {reason}")
    return "; ".join(parts) or None


#: Cómo se explica en el informe cada motivo de ``Finding.fixed_reason``.
_DROPPED_REASON_LABEL = {
    "backport": ("Descartados: la distribución ya los había corregido en el paquete "
                 "instalado, aunque su número de versión no lo refleje"),
    "alias": ("El sitio resultó ser un alias del sitio por defecto de la IP: sus avisos "
              "salen ahora con el sitio por defecto"),
}


def _append_dropped_section(theme: "ReportTheme", elements: list, dropped_findings: list,
                            outline_key: str) -> None:
    """La sección «Ya no se reportan (mejoras del motor)», si hay alguno.

    Son hallazgos que el escaneo anterior mostraba y éste ya no, pero no porque
    el cliente los haya arreglado: el motor ha aprendido a no reportarlos. Se
    agrupan por motivo, con una frase que lo explica, para que nadie los lea
    como una remediación.

    Args:
        theme: El tema del informe.
        elements: La lista de elementos del documento; se amplía en sitio.
        dropped_findings: Los hallazgos ``fixed`` con ``fixed_reason``; vacía,
            no se añade nada.
        outline_key: La clave del marcador de la sección en el índice del PDF.
    """
    if not dropped_findings:
        return
    title = "Ya no se reportan (mejoras del motor)"
    elements.append(CondPageBreak(1.5 * inch))
    elements.append(OutlineEntry(title, key=outline_key, level=0))
    elements.append(Paragraph(title, theme.subtitle))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        "El escaneo anterior los mostraba y éste ya no, pero no porque se hayan corregido: "
        "el motor ha dejado de reportarlos. No cuentan en el total ni como corregidos.",
        theme.body))
    by_reason: dict = {}
    for finding in dropped_findings:
        by_reason.setdefault(finding["fixed_reason"], []).append(finding)
    for reason, group in by_reason.items():
        label = _DROPPED_REASON_LABEL.get(reason, reason)
        elements.append(Paragraph(f"<b>{safe_markup(label)}</b>", theme.body))
        for finding in group:
            where = f"{finding.get('service') or 'servicio'}:{finding['port']}" if finding.get("port") else ""
            if finding.get("vhost"):
                where += f", sitio {finding['vhost']}"
            suffix = f" ({safe_markup(where)})" if where else ""
            elements.append(Paragraph(f"• {safe_markup(finding['title'])}{suffix}", theme.body))
    elements.append(Spacer(1, 0.3 * inch))


def _unverified_warning(findings: list) -> Optional[str]:
    """El aviso de portada sobre los hallazgos que el proveedor no ha contrastado.

    Args:
        findings: Los hallazgos del informe, ya marcados con
            ``is_unverified_distro_package``.

    Returns:
        Optional[str]: El texto del aviso, que añade si la fuente OVAL
            está desactualizada, o ``None`` si no hay ningún hallazgo así.
    """
    count = sum(1 for finding in findings if finding.get("is_unverified_distro_package")
                and finding.get("state") != "false_positive")
    if not count:
        return None
    text = (f"<b>Aviso:</b> {count} hallazgo(s) por versión son de paquetes de una "
            "distribución Linux y no se han podido contrastar con el proveedor. La "
            "distribución puede haberlos corregido sin cambiar el número de versión, así "
            "que se muestran con prioridad MEDIA como máximo y deben verificarse.")
    if _is_oval_stale():
        text += (" La fuente OVAL de avisos de distribución está desactualizada: "
                 "sincronizarla puede desmentir algunos.")
    return text


def _default_site_warning(findings: list) -> Optional[str]:
    """El aviso de portada de que la IP aloja varias webs y sólo se ven algunas.

    Cuando la IP sirve webs con nombre propio, lo que enseña a quien entra sin
    nombre es su sitio por defecto (en un hosting, la página genérica del
    panel). El escaneo por IP sólo ve las webs que la propia IP delata en sus
    certificados o en su DNS inverso; el resto hay que escanearlas por nombre.

    Args:
        findings: Los hallazgos del informe.

    Returns:
        Optional[str]: El texto del aviso, o ``None`` si ningún hallazgo es del
            sitio por defecto.
    """
    if not any(finding.get("vhost") == DEFAULT_SITE_VHOST for finding in findings):
        return None
    return ("<b>Aviso:</b> esta IP aloja varias webs. Los avisos de la página que "
            "responde a quien entra por la IP, sin nombre (el «sitio por defecto»), se "
            "muestran con prioridad baja, porque no es la que ven los visitantes. Solo se "
            "han auditado las webs que la propia IP delata; para auditar cualquier otra "
            "alojada aquí, escanéala por su nombre.")


def _is_oval_stale() -> bool:
    """Si alguna distribución OVAL de la KB está desactualizada.

    OVAL se registra por distribución (``oval:debian:12``…), así que basta con
    que una esté vieja. Best-effort: ``False`` ante error.

    Returns:
        bool: ``True`` si al menos una distribución OVAL está desactualizada.
    """
    from src.modules.features.themis.managers.kb_sync import KbSyncManager

    try:
        return any(entry["source"].startswith("oval:") and entry["isStale"]
                   for entry in KbSyncManager().status()["sources"])
    except Exception:  # noqa: BLE001 - el informe no puede caerse por esto
        logger.exception("No se pudo leer el estado de la base de conocimiento")
        return False


def _effective_frameworks(user_id: int) -> tuple:
    """Los marcos de cumplimiento que se aplican al dueño de un escaneo.

    Args:
        user_id: Dueño del escaneo.

    Returns:
        tuple[ComplianceFramework, ...]: En el orden del catálogo; vacía si ni
            el dueño ni su organización han elegido ninguno.
    """
    # Diferido: `managers` importa `services`, así que a nivel de módulo
    # sería un ciclo.
    from src.modules.features.themis.managers import ComplianceManager
    keys = set(ComplianceManager().resolve_effective_frameworks(user_id))
    return tuple(framework for framework in load_compliance_catalog().frameworks.values()
                 if framework.key in keys)


def _compliance_rows(theme: "ReportTheme", compliance, frameworks: tuple) -> list:
    """Las filas de la ficha de un hallazgo con sus técnicas y sus controles.

    El valor va como párrafo para que un título de control largo parta línea
    en vez de salirse de la celda.

    Args:
        theme: El tema del informe.
        compliance: El ``FindingCompliance`` del hallazgo, o ``None`` si el
            informe no traduce a cumplimiento.
        frameworks: Los ``ComplianceFramework`` del dueño, en el orden en que
            salen las filas.

    Returns:
        list[list]: Pares ``[rótulo, valor]``: uno de MITRE ATT&CK si el
            hallazgo tiene técnicas y uno por cada marco con controles
            afectados. Vacía si no hay nada que enseñar.
    """
    if compliance is None:
        return []
    value_style = ParagraphStyle("ComplianceValue", parent=theme.body, fontSize=8.5, leading=10.5,
                                 alignment=TA_LEFT)
    rows = []
    if compliance.techniques:
        rows.append(["MITRE ATT&CK:", Paragraph("<br/>".join(
            f"{technique.identifier} {safe_markup(technique.name)} "
            f"({safe_markup(', '.join(technique.tactics))})"
            for technique in compliance.techniques), value_style)])
    for framework in frameworks:
        controls = [control for control in compliance.controls if control.framework == framework.key]
        if controls:
            rows.append([f"{framework.short_name}:", Paragraph("<br/>".join(
                f"{safe_markup(control.identifier)} {safe_markup(control.title)}"
                for control in controls), value_style)])
    return rows


def _append_compliance_section(theme: "ReportTheme", elements: list, findings: list, frameworks: tuple,
                               palette: dict, outline_key: str) -> None:
    """La sección «Cumplimiento y técnicas de ataque».

    Agrega las fichas: por cada técnica de ATT&CK y por cada control afectado,
    cuántos hallazgos lo tocan y la prioridad más alta entre ellos. Los
    controles se agrupan bajo su control padre (``op.exp`` sobre ``op.exp.4``),
    que es como los lee quien prepara una auditoría. Los hallazgos que el
    usuario desmintió no cuentan, igual que en el resumen por prioridad.

    Args:
        theme: El tema del informe.
        elements: La lista de elementos del documento; se amplía en sitio.
        findings: Los hallazgos abiertos, ya con su clave ``compliance``.
        frameworks: Los ``ComplianceFramework`` del dueño; vacía, la sección
            sólo enseña ATT&CK y explica dónde elegirlos.
        palette: La paleta de colores del informe.
        outline_key: La clave del marcador de la sección en el índice del PDF.
    """
    live = [finding for finding in findings
            if finding.get("state") != "false_positive" and finding.get("compliance")
            and (finding["compliance"].techniques or finding["compliance"].controls)]
    if not live:
        return
    title = "Cumplimiento y técnicas de ataque"
    elements.append(CondPageBreak(2 * inch))
    elements.append(OutlineEntry(title, key=outline_key, level=0))
    elements.append(Paragraph(title, theme.subtitle))
    elements.append(Spacer(1, 0.1 * inch))
    cell = ParagraphStyle("ComplianceCell", parent=theme.body, fontSize=8, leading=10)

    techniques: Dict[str, tuple] = {}
    for finding in live:
        for technique in finding["compliance"].techniques:
            techniques.setdefault(technique.identifier, (technique, []))[1].append(finding)
    if techniques:
        elements.append(Paragraph("<b>MITRE ATT&amp;CK</b>", theme.body))
        rows = [[technique.identifier, Paragraph(safe_markup(technique.name), cell),
                 Paragraph(safe_markup(", ".join(technique.tactics)), cell), *_tally(related)]
                for _, (technique, related) in sorted(techniques.items())]
        elements.append(_compliance_table(palette, ["Técnica", "Nombre", "Táctica"], [0.8, 2.4, 1.1], rows, []))
        elements.append(Spacer(1, 0.2 * inch))

    if not frameworks:
        elements.append(Paragraph(
            "No hay marcos de cumplimiento elegidos. Si eliges ISO 27001, ENS o NIS2 en tu "
            "perfil, este informe dirá qué controles de cada uno afecta cada hallazgo.", theme.info))
        elements.append(Spacer(1, 0.3 * inch))
        return

    catalog = load_compliance_catalog()
    for framework in frameworks:
        affected: Dict[str, list] = {}
        for finding in live:
            for control in finding["compliance"].controls:
                if control.framework == framework.key:
                    affected.setdefault(control.code, []).append(finding)
        if not affected:
            continue
        rows, group_rows, current_parent = [], [], None
        # El orden del catálogo es el del propio marco: los hermanos salen juntos.
        for code in (code for code in catalog.controls if code in affected):
            control = catalog.controls[code]
            parent = catalog.controls.get(control.parent) if control.parent else None
            if parent is not None and parent.code != current_parent:
                current_parent = parent.code
                group_rows.append(len(rows) + 1)
                rows.append([Paragraph(f"<b>{safe_markup(parent.identifier)} "
                                       f"{safe_markup(parent.title)}</b>", cell), "", "", ""])
            rows.append([control.identifier, Paragraph(safe_markup(control.title), cell),
                         *_tally(affected[code])])
        elements.append(Paragraph(f"<b>{safe_markup(framework.name)}</b>", theme.body))
        elements.append(_compliance_table(palette, ["Control", "Título"], [0.8, 3.5], rows, group_rows))
        elements.append(Spacer(1, 0.2 * inch))
    elements.append(Spacer(1, 0.1 * inch))


def _tally(related: list) -> list:
    """Las dos últimas celdas de una fila de cumplimiento.

    Args:
        related: Los hallazgos que tocan la técnica o el control.

    Returns:
        list[str]: El número de hallazgos y el rótulo de su prioridad más alta.
    """
    order = FindingsPrintingStrategy._PRIORITY_ORDER  # pylint: disable=protected-access
    top = min((finding["priority"] for finding in related), key=lambda priority: order.get(priority, len(order)))
    return [str(len(related)), FindingsPrintingStrategy._PRIORITY_LABEL.get(top, top)]  # pylint: disable=protected-access


def _compliance_table(palette: dict, headers: list, widths: list, rows: list, group_rows: list) -> Table:
    """Una tabla de la sección de cumplimiento.

    Args:
        palette: La paleta de colores del informe.
        headers: Rótulos de las columnas descriptivas; se les añaden
            «Hallazgos» y «Prioridad máx.».
        widths: Anchos en pulgadas de las columnas descriptivas; las dos de
            recuento ocupan 1.7 pulgadas más.
        rows: Las filas, ya con sus celdas.
        group_rows: Índices (contando la cabecera como 0) de las filas que son
            un control padre: ocupan todo el ancho y van sombreadas.

    Returns:
        Table: La tabla lista para añadir al documento.
    """
    dark = colors.HexColor(palette[ColorType.DARK])
    light = colors.HexColor(palette[ColorType.LIGHT])
    table = Table([headers + ["Hallazgos", "Prioridad máx."], *rows],
                  colWidths=[width * inch for width in widths] + [0.75 * inch, 0.95 * inch],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette[ColorType.SECONDARY])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (-2, 1), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.4, dark),
        *[style for row in group_rows for style in (
            ("SPAN", (0, row), (-1, row)), ("BACKGROUND", (0, row), (-1, row), light))],
    ]))
    return table
