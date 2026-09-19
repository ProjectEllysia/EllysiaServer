"""
Informe PDF del análisis de cabeceras de correo de Iris.

Lleva al papel lo mismo que muestra el visor web —veredicto, puntuación,
resultado de cada regla, recomendaciones, cadena Received y cabeceras en
crudo—. La composición del documento (portada, aparejo de página, nota legal,
pie) no está aquí: la pone ``tools.press``, que es la que garantiza que este
informe y los de Themis y Hygeia se reconozcan como del mismo producto.

Dibuja, no consulta: recibe el informe ya serializado por
``IrisManager.get_analysis_results`` y la cadena por ``get_analysis_path``, así
que no toca la base de datos ni comprueba permisos. De eso se encarga el
manager.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Dict, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
)

import src.modules.system.config_reading as CR
from src.modules.tools.press import (
    ColorType, DocumentStyle, PdfGenerator, ReportTheme, build_palette, safe_markup,
)
from .parsers import parse_raw_headers, decode_mime_words
from .redaction import redact_pii

logger = logging.getLogger(__name__)


#: Identidad visual de Iris: violeta, para distinguirse del azul y el verde de
#: las herramientas de Themis.
#:
#: A diferencia de Themis y Hygeia, no hay un bloque
#: ``features.iris.colorPalette`` en la configuración, así que hoy estos seis
#: colores son los únicos posibles. Darle esa palanca al operador sería añadir
#: el bloque al JSON y pasarlo aquí como primer argumento.
_BRAND_COLORS = {
    "black":     "#1A1330",
    "dark":      "#3B2768",
    "main":      "#5B3FA8",
    "secondary": "#8A6FD1",
    "light":     "#B89EE8",
    "white":     "#F1ECFB",
}

_PALETTE = build_palette(None, _BRAND_COLORS)

#: Ancho de las píldoras de las cabeceras de sección. Iris usa rótulos más
#: largos que el resto ("CADENA DE ENTREGA", "CABECERAS EN CRUDO"), así que
#: necesita más sitio que el valor por defecto de ``press``.
_PILL_WIDTH = 2.2 * inch

_VERDICT_COLORS = {
    "Legitimate": colors.HexColor("#388e3c"),
    "Suspicious": colors.HexColor("#f57c00"),
    "Phishing":   colors.HexColor("#d32f2f"),
}

_VERDICT_LABELS = {
    "Legitimate": "Correo verificado",
    "Suspicious": "Posible amenaza",
    "Phishing":   "Phishing detectado",
}


def _rule_cell(rule: Dict[str, Any]) -> str:
    """Celda de la tabla de reglas: nombre visible y, debajo, el id estable.

    Args:
        rule: Regla serializada del informe.

    Returns:
        str: Marcado de reportlab, con el texto ya escapado.
    """
    text = safe_markup(rule.get("ruleName", ""))
    if rule.get("ruleId"):
        text += f"<br/><font size='7' color='#6b7280'>{safe_markup(rule['ruleId'])}</font>"
    return text


def _rule_reference(rule: Dict[str, Any]) -> str:
    """Referencia estable de un hallazgo para el detalle: id y técnicas ATT&CK.

    Args:
        rule: Regla serializada del informe.

    Returns:
        str: `` (<id> · ATT&CK T1566.002)`` ya escapado; cadena vacía si la
            regla no tiene id (análisis anteriores a la taxonomía).
    """
    if not rule.get("ruleId"):
        return ""
    reference = f"<font face='Courier'>{safe_markup(rule['ruleId'])}</font>"
    techniques = rule.get("mitreTechniques") or []
    if techniques:
        reference += " · ATT&amp;CK " + ", ".join(safe_markup(technique) for technique in techniques)
    return f" ({reference})"


class IrisPDFCreator(PdfGenerator):
    """Compone el informe PDF de un análisis de correo de Iris.

    Solo aporta lo propio de Iris —la portada, el cuerpo y la nota final—;
    todo lo demás lo pone ``PdfGenerator``.

    Attributes:
        report: Informe ya serializado por ``IrisManager.get_analysis_results``.
        path: Cadena de entrega ya serializada por
            ``IrisManager.get_analysis_path``. Vacía si no se pidió.
        document_id: Clave primaria del ``IrisDocument`` al que pertenece este
            PDF. Va en el nombre del fichero, así que dos documentos del mismo
            análisis nunca escriben encima el uno del otro.
        directory: Directorio de salida de los informes de Iris.
    """

    def __init__(self, report: Dict[str, Any], path: Optional[Dict[str, Any]] = None,
                 document_id: Optional[int] = None) -> None:
        """Prepara el generador con los datos del análisis.

        Args:
            report: Informe ya serializado. De él salen el título, el
                veredicto, las reglas y las cabeceras.
            path: Cadena Received ya serializada. Por defecto ``None``, y
                entonces la sección de la cadena de entrega no se imprime.
            document_id: Clave primaria del ``IrisDocument``. Por defecto
                ``None``, y entonces el nombre del fichero cae a un sufijo
                aleatorio; ningún camino de la aplicación llega así hoy, queda
                para que la clase siga siendo usable a pelo.
        """
        super().__init__(DocumentStyle(
            palette=_PALETTE,
            header_title="Iris Email Security Report",
        ))
        self.report = report
        self.path = path or {}
        self.document_id = document_id
        self.directory = CR.get_directory_of(CR.DirectoryType.OUTPUT_IRIS)

    # =========================================================================
    # LO QUE APORTA IRIS
    # =========================================================================

    def cover_title(self) -> str:
        """Título de la portada: el asunto del correo analizado.

        Returns:
            str: El título del análisis ya saneado, o un rótulo genérico si el
                correo no traía asunto.
        """
        return safe_markup(self.report.get("title") or "Análisis de Correo Electrónico")

    def cover_fields(self) -> Sequence[Sequence[str]]:
        """Ficha de la portada: número de análisis, fecha y usuario.

        Returns:
            Sequence[Sequence[str]]: Las tres filas de la ficha.
        """
        started = self.report.get("startedAt")
        date_str = started[:10] if started else datetime.now().strftime("%Y-%m-%d")
        return [
            ["Análisis:", f"#{self.report.get('analysisId')}"],
            ["Fecha:", date_str],
            ["Usuario:", str(self.report.get("user", ""))],
        ]

    def document_title(self) -> str:
        """Título de los metadatos del PDF.

        No es el de la portada: aquí conviene el identificador del análisis,
        que es lo que distingue dos informes en la barra de un lector de PDF.

        Returns:
            str: ``"Informe de Análisis Iris - <id>"``.
        """
        return f"Informe de Análisis Iris - {self.report.get('analysisId')}"

    def document_subject(self) -> str:
        """Asunto de los metadatos del PDF.

        Returns:
            str: Una descripción fija de qué es este documento.
        """
        return "Análisis de cabeceras de correo (anti-phishing)"

    def legal_notice(self) -> Tuple[str, str]:
        """Nota que cierra el informe: qué es y qué no es este análisis.

        Returns:
            Tuple[str, str]: El título del recuadro y su texto.
        """
        return ("NOTA SOBRE EL ANÁLISIS", """
        Este informe se ha generado automáticamente a partir del análisis de
        las cabeceras (y, cuando estaba disponible, el cuerpo) del correo
        electrónico indicado. El veredicto y la puntuación reflejan el resultado
        de las reglas heurísticas aplicadas y deben interpretarse como una ayuda
        a la decisión, no como una determinación legal o definitiva sobre la
        naturaleza del mensaje. Iris no garantiza la exactitud o completitud
        del análisis frente a técnicas de evasión no contempladas por las reglas
        vigentes en el momento de la ejecución.

        Este documento puede contener información sensible extraída del correo
        analizado y debe tratarse con las medidas de seguridad apropiadas.
        """)

    def append_body(self, elements: list, theme: ReportTheme) -> None:
        """Añade el cuerpo del informe, sección a sección.

        El orden importa: el veredicto va primero porque es la respuesta a la
        pregunta que trae quien abre el informe, y las cabeceras en crudo al
        final porque son la evidencia que casi nadie lee pero tiene que estar.

        Args:
            elements: Lista de flowables del documento en construcción.
            theme: Los estilos del informe.
        """
        self.append_verdict_hero(elements, theme)
        self.append_confidence(elements, theme)
        self.append_quality_warning(elements, theme)
        self.append_email_preview(elements, theme)
        self.append_gate_reasons(elements, theme)
        self.append_rules(elements, theme)
        self.append_recommendations(elements, theme)
        self.append_path(elements, theme)
        self.append_raw_headers(elements, theme)

    def output_path(self) -> str:
        """Ruta del PDF, única por **documento** y no por análisis.

        El modelo permite N ``IrisDocument`` por análisis, pero el nombre solo
        dependía del ``analysis_id``, así que todos escribían el mismo fichero:
        dos generaciones a la vez se pisaban, y borrar un documento destruía el
        PDF del otro (``delete_document_with_file`` borra por ``filename``, que
        era el mismo para ambos).

        Returns:
            str: La ruta absoluta del fichero.
        """
        analysis_id = self.report.get("analysisId")
        suffix = self.document_id if self.document_id is not None else uuid.uuid4().hex
        return os.path.join(self.directory, f"{analysis_id}_{suffix}_Iris.pdf")

    def print_pdf(self) -> str:
        """Genera el informe y lo deja escrito en disco.

        Returns:
            str: La ruta del PDF generado.
        """
        return self.generate_to_file(self.output_path())

    def append_verdict_hero(self, elements: list, theme: ReportTheme) -> None:
        verdict = self.report.get("verdict") or "Suspicious"
        score = self.report.get("totalScore")
        risk_color = _VERDICT_COLORS.get(verdict, colors.HexColor("#757575"))
        label = _VERDICT_LABELS.get(verdict, "")

        score_style = ParagraphStyle(
            "IrisScore", parent=theme.styles["Normal"],
            fontSize=26, leading=30, textColor=risk_color,
            alignment=TA_LEFT, fontName="Helvetica-Bold",
        )
        verdict_style = ParagraphStyle(
            "IrisVerdict", parent=theme.styles["Normal"],
            fontSize=15, leading=18, textColor=risk_color,
            alignment=TA_LEFT, fontName="Helvetica-Bold",
        )
        label_style = ParagraphStyle(
            "IrisVerdictLabel", parent=theme.styles["Normal"],
            fontSize=9.5, leading=12, textColor=colors.HexColor(theme.palette[ColorType.DARK]),
            alignment=TA_LEFT,
        )

        score_cell = Paragraph(f"{score if score is not None else 'N/A'}", score_style)
        verdict_cell = [Paragraph(verdict, verdict_style)]
        if label:
            verdict_cell.append(Paragraph(label, label_style))

        hero = Table([[score_cell, verdict_cell]], colWidths=[2 * inch, 4 * inch])
        hero.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, risk_color),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
            ("TOPPADDING", (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ]))
        elements.append(hero)
        elements.append(Spacer(1, 0.25 * inch))

    def append_email_preview(self, elements: list, theme: ReportTheme) -> None:
        """Vista previa del correo: De / Para / Responder-a / Asunto / Fecha.

        Va de las primeras secciones del informe (justo tras el veredicto)
        para dar contexto inmediato de "qué correo es este" antes de entrar
        en el detalle de reglas y evidencia. El contraste De vs. Responder-a
        se resalta porque una discrepancia entre ambos es una señal clásica
        de fraude BEC (el atacante quiere que las respuestas vayan a un
        buzón distinto del remitente que se ve a simple vista).

        Las cabeceras salen de ``previewHeaders``, que el manager toma del
        contexto que produjo el veredicto; si el informe no las trae (un
        informe construido a mano), se leen del raw.
        """
        preview = self.report.get("previewHeaders")
        if preview is None:
            raw = self.report.get("rawHeaders")
            if not raw:
                return
            headers = parse_raw_headers(raw)
            preview = {
                key: (decode_mime_words(headers[name]) if headers.get(name) else None)
                for name, key in (("subject", "subject"), ("from", "from"), ("to", "to"),
                                  ("reply-to", "replyTo"), ("return-path", "returnPath"),
                                  ("date", "date"))
            }

        subject = preview.get("subject")
        from_ = preview.get("from")
        to_address = preview.get("to")
        reply_to = preview.get("replyTo")
        return_path = preview.get("returnPath")
        date = preview.get("date")

        if not any([subject, from_, to_address, reply_to, return_path, date]):
            return

        elements.extend(theme.section_header("Vista Previa del Correo", "CONTENIDO", pill_width=_PILL_WIDTH))
        elements.append(Spacer(1, 0.1 * inch))

        main = colors.HexColor(theme.palette[ColorType.MAIN])
        white = colors.HexColor(theme.palette[ColorType.WHITE])
        light = colors.HexColor(theme.palette[ColorType.LIGHT])
        dark = colors.HexColor(theme.palette[ColorType.DARK])
        alert = colors.HexColor("#d32f2f")

        value_style = ParagraphStyle(
            "IrisPreviewValue", parent=theme.styles["Normal"],
            fontSize=9, leading=12, textColor=dark,
            alignment=TA_LEFT, wordWrap="CJK",
        )
        mismatch_style = ParagraphStyle(
            "IrisPreviewMismatch", parent=value_style,
            textColor=alert, fontName="Helvetica-Bold",
        )

        rows: list = []
        if subject:
            rows.append(["Asunto:", Paragraph(safe_markup(subject), value_style)])
        if from_:
            rows.append(["De:", Paragraph(safe_markup(from_), value_style)])
        if to_address:
            rows.append(["Para:", Paragraph(safe_markup(to_address), value_style)])
        if reply_to:
            # Compara solo la dirección (sin el nombre visible) para no
            # marcar como discrepancia un simple cambio de formato.
            mismatch = bool(from_) and parseaddr(reply_to)[1].lower() != parseaddr(from_)[1].lower()
            if mismatch:
                text = f"{safe_markup(reply_to)}  [!] distinto del remitente (De:)"
                rows.append(["Responder a:", Paragraph(text, mismatch_style)])
            else:
                rows.append(["Responder a:", Paragraph(safe_markup(reply_to), value_style)])
        if return_path:
            rows.append(["Return-Path:", Paragraph(safe_markup(return_path), value_style)])
        if date:
            rows.append(["Fecha:", Paragraph(safe_markup(date), value_style)])

        preview_table = Table(rows, colWidths=[1.3 * inch, 5.1 * inch])
        preview_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), white),
            ("BACKGROUND", (1, 0), (1, -1), colors.white),
            ("TEXTCOLOR", (0, 0), (0, -1), main),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.4, light),
        ]))
        elements.append(preview_table)

        if self.report.get("unwrappedFromForward"):
            elements.append(Spacer(1, 0.1 * inch))
            wrapper_from = self.report.get("wrapperFrom")
            wrapper_subject = self.report.get("wrapperSubject")
            if self.report.get("winningContext") == "wrapper":
                note = "Este análisis corresponde al envoltorio del reenvío"
            else:
                note = "Este análisis corresponde al correo original reenviado"
            if wrapper_from:
                note += f" por {safe_markup(wrapper_from)}"
            if wrapper_subject:
                note += f" (asunto del reenvío: «{safe_markup(wrapper_subject)}»)"
            note += "."
            winning_reason = self.report.get("winningReason")
            if winning_reason:
                note += f" {safe_markup(winning_reason)}"
            secondary = self.report.get("secondaryContext")
            if secondary:
                note += (
                    f" El otro mensaje ({'envoltorio' if secondary.get('contextType') == 'wrapper' else 'original'})"
                    f" obtuvo {safe_markup(secondary.get('verdict'))} con {safe_markup(secondary.get('totalScore'))} puntos."
                )
            elements.append(Paragraph(note, theme.body))

        elements.append(Spacer(1, 0.22 * inch))

    _CONFIDENCE_LABELS = {"high": "Alta", "medium": "Media", "low": "Baja"}

    #: Extractos de evidencia por hallazgo en el PDF; el resto se resume.
    _EVIDENCE_PER_RULE = 3

    def append_confidence(self, elements: list, theme: ReportTheme) -> None:
        """Confianza y cobertura del veredicto, justo debajo de él.

        Usa la misma semántica que la API y la UI: una confianza ordinal
        (alta/media/baja), nunca un porcentaje, con sus motivos, y si se
        inspeccionó el mensaje completo o solo sus cabeceras. No aparece en
        informes de análisis anteriores a que se calculara.

        Args:
            elements: Lista de flowables del documento, a la que se añade.
            theme: Tema del informe (estilos y paleta).
        """
        label = self._CONFIDENCE_LABELS.get(self.report.get("confidence") or "")
        if label is None:
            return

        coverage = self.report.get("coverage") or {}
        if coverage.get("mode") == "headers_only":
            uncovered = coverage.get("uncoveredRules") or []
            coverage_text = (
                "solo cabeceras. Estas reglas no tuvieron cuerpo, enlaces ni "
                f"adjuntos que inspeccionar: {safe_markup(', '.join(uncovered)) or 'ninguna'}."
            )
        else:
            coverage_text = "mensaje completo."

        text = (
            f"<b>Confianza del análisis: {label}.</b> Es una escala ordinal, no "
            "una probabilidad: el score mide riesgo y no está calibrado "
            f"estadísticamente.<br/><b>Cobertura:</b> {coverage_text}"
        )
        for reason in self.report.get("uncertaintyReasons") or []:
            text += f"<br/>• {safe_markup(reason)}"

        card = Table([[Paragraph(text, theme.body)]], colWidths=[6.4 * inch])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(theme.palette[ColorType.WHITE])),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(theme.palette[ColorType.LIGHT])),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        elements.append(card)
        elements.append(Spacer(1, 0.22 * inch))

    def append_quality_warning(self, elements: list, theme: ReportTheme) -> None:
        """Aviso de análisis degradado, justo debajo del veredicto.

        Va aquí y no entre las señales de más abajo porque contradice
        parcialmente lo que el lector acaba de leer: el veredicto grande de la
        portada se calculó sin una parte del examen, y quien imprima el
        informe tiene que verlo antes de actuar sobre él.
        """
        failed_rules = self.report.get("failedRules") or []
        if self.report.get("analysisQuality") != "degraded" and not failed_rules:
            return

        names = ", ".join(rule.get("name", "?") for rule in failed_rules) or "desconocidas"
        warning_style = ParagraphStyle(
            "IrisQualityWarning", parent=theme.body,
            textColor=colors.HexColor("#7a4100"),
        )
        text = (
            f"<b>Análisis incompleto.</b> No se pudieron ejecutar estas reglas: "
            f"{safe_markup(names)}. La parte del mensaje que les correspondía no se ha "
            "inspeccionado, así que este informe describe menos de lo que "
            "describiría un análisis completo."
        )

        card = Table([[Paragraph(text, warning_style)]], colWidths=[6.4 * inch])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4E5")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#f57c00")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#FFD8A8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        elements.append(card)
        elements.append(Spacer(1, 0.22 * inch))

    def append_gate_reasons(self, elements: list, theme: ReportTheme) -> None:
        """Señales de alta confianza que fijaron el veredicto.

        Solo aparece cuando algún gate se disparó — explica el "por qué"
        del veredicto más allá de la puntuación numérica.
        """
        reasons = self.report.get("gateReasons") or []
        if not reasons:
            return

        verdict = self.report.get("verdict") or "Suspicious"
        risk_color = _VERDICT_COLORS.get(verdict, colors.HexColor("#757575"))

        elements.extend(theme.section_header("Por qué este veredicto", "SEÑALES CLAVE", pill_width=_PILL_WIDTH))
        elements.append(Spacer(1, 0.1 * inch))

        reason_style = ParagraphStyle(
            "IrisGateReason", parent=theme.body,
            textColor=colors.HexColor(theme.palette[ColorType.BLACK]),
            spaceAfter=4,
        )
        reason_paras = [Paragraph(f"•  {safe_markup(reason)}", reason_style) for reason in reasons]

        card = Table([[reason_paras]], colWidths=[6.4 * inch])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFAFA")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, risk_color),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E0E0E0")),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        elements.append(card)
        elements.append(Spacer(1, 0.22 * inch))

    def append_rules(self, elements: list, theme: ReportTheme) -> None:
        rules = self.report.get("rules") or []
        elements.extend(theme.section_header("Reglas Aplicadas", "VERIFICACIONES", pill_width=_PILL_WIDTH))
        elements.append(Spacer(1, 0.1 * inch))

        if not rules:
            elements.append(Paragraph("No se ejecutaron reglas.", theme.body))
            return

        main = colors.HexColor(theme.palette[ColorType.MAIN])
        light = colors.HexColor(theme.palette[ColorType.LIGHT])
        white = colors.HexColor(theme.palette[ColorType.WHITE])

        rule_data = [[
            Paragraph("Regla", theme.cell_header),
            Paragraph("Categoría", theme.cell_header),
            Paragraph("Puntuación", theme.cell_header),
            Paragraph("Veredicto", theme.cell_header),
        ]]
        for rule in rules:
            score = rule.get("score", 0)
            sign = "+" if score > 0 else ""
            rule_data.append([
                Paragraph(_rule_cell(rule), theme.cell_left),
                Paragraph(safe_markup(rule.get("category") or "-"), theme.cell_left),
                Paragraph(f"{sign}{score}", theme.cell_center),
                Paragraph(safe_markup(rule.get("verdict", "")), theme.cell_center),
            ])

        rule_table = Table(
            rule_data,
            colWidths=[2.1 * inch, 1.6 * inch, 1.1 * inch, 1.2 * inch],
            repeatRows=1,
        )
        rule_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), main),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
            ("BACKGROUND", (0, 1), (-1, -1), white),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, white]),
            ("GRID", (0, 0), (-1, -1), 0.4, light),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, main),
        ]))
        elements.append(rule_table)
        elements.append(Spacer(1, 0.2 * inch))

        # Recommendations attached to failing rules.
        flagged = [rule for rule in rules if rule.get("recommendation")]
        if flagged:
            elements.append(Paragraph("Detalle de hallazgos", theme.subtitle))
            elements.append(Spacer(1, 0.08 * inch))
            for flagged_rule in flagged:
                text = (f"<b>{safe_markup(flagged_rule.get('ruleName'))}</b>{_rule_reference(flagged_rule)}: "
                        f"{safe_markup(flagged_rule.get('recommendation'))}")
                # El extracto ya viene desactivado (hxxp, [.], [@]): el PDF sale
                # del panel autenticado y no debe llevar enlaces vivos.
                evidence = flagged_rule.get("evidence") or []
                for item in evidence[:self._EVIDENCE_PER_RULE]:
                    text += f"<br/>Evidencia: <font face='Courier'>{safe_markup(item.get('excerpt'))}</font>"
                if len(evidence) > self._EVIDENCE_PER_RULE:
                    text += f"<br/>(y {len(evidence) - self._EVIDENCE_PER_RULE} fragmentos más)"
                if not evidence and flagged_rule.get("evidenceUnavailableReason"):
                    text += f"<br/><i>Sin evidencia anclada: {safe_markup(flagged_rule['evidenceUnavailableReason'])}</i>"
                elements.append(Paragraph(text, theme.body))
            elements.append(Spacer(1, 0.15 * inch))

    def append_recommendations(self, elements: list, theme: ReportTheme) -> None:
        recommendations = self.report.get("recommendations") or []
        if not recommendations:
            return
        elements.append(PageBreak())
        elements.extend(theme.section_header("Recomendaciones", "ACCIONES SUGERIDAS", pill_width=_PILL_WIDTH))
        elements.append(Spacer(1, 0.1 * inch))
        for rec in recommendations:
            elements.append(Paragraph(f"• {safe_markup(rec)}", theme.body))
        elements.append(Spacer(1, 0.15 * inch))

    def append_path(self, elements: list, theme: ReportTheme) -> None:
        if not self.path or not self.path.get("available"):
            return
        hops = self.path.get("hops") or []
        if not hops:
            return

        elements.append(PageBreak())
        elements.extend(theme.section_header("Recorrido del Correo", "CADENA RECEIVED", pill_width=_PILL_WIDTH))
        elements.append(Spacer(1, 0.1 * inch))

        main = colors.HexColor(theme.palette[ColorType.MAIN])
        light = colors.HexColor(theme.palette[ColorType.LIGHT])
        white = colors.HexColor(theme.palette[ColorType.WHITE])

        hop_data = [[
            Paragraph("#", theme.cell_header),
            Paragraph("Desde", theme.cell_header),
            Paragraph("IP", theme.cell_header),
            Paragraph("TLS", theme.cell_header),
            Paragraph("Fecha", theme.cell_header),
        ]]
        for hop in hops:
            hop_data.append([
                Paragraph(safe_markup(hop.get("hop", "")), theme.cell_center),
                Paragraph(safe_markup(hop.get("from") or "-"), theme.cell_left),
                Paragraph(safe_markup(hop.get("fromIp") or "-"), theme.cell_left),
                Paragraph("Sí" if hop.get("tls") else "No", theme.cell_center),
                Paragraph(safe_markup(hop.get("timestamp") or "-"), theme.cell_left),
            ])

        hop_table = Table(
            hop_data,
            colWidths=[0.4 * inch, 2.2 * inch, 1.3 * inch, 0.5 * inch, 1.6 * inch],
            repeatRows=1,
        )
        hop_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), main),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, -1), white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, white]),
            ("GRID", (0, 0), (-1, -1), 0.4, light),
        ]))
        elements.append(hop_table)

        transitions = self.path.get("transitions") or []
        suspicious = [transition for transition in transitions if transition.get("suspicious")]
        if suspicious:
            elements.append(Spacer(1, 0.15 * inch))
            elements.append(Paragraph("Transiciones sospechosas detectadas", theme.subtitle))
            elements.append(Spacer(1, 0.05 * inch))
            for suspicious_transition in suspicious:
                reasons = safe_markup(", ".join(suspicious_transition.get("reasons") or []))
                elements.append(Paragraph(
                    f"Salto {safe_markup(suspicious_transition.get('from'))} → "
                    f"{safe_markup(suspicious_transition.get('to'))}: {reasons}", theme.body
                ))

    def append_raw_headers(self, elements: list, theme: ReportTheme) -> None:
        """Vuelca el raw completo del correo -- la única vista de Iris que
        sale del panel autenticado tal cual una vez descargado el PDF, así
        que es la que se redacta (``iris.redactPiiInReports``): no se
        toca el remitente/destinatario/responder-a/return-path, que son la
        evidencia del informe (ya mostrados en "Vista Previa del Correo"),
        pero sí cualquier otra dirección, teléfono o número con forma de
        tarjeta que aparezca en cabeceras de reenvío, listas de distribución
        o el cuerpo (en ``full_message_mode``)."""
        raw = self.report.get("rawHeaders")
        if not raw:
            return
        elements.append(PageBreak())
        elements.extend(theme.section_header("Cabeceras Originales", "EVIDENCIA RAW", pill_width=_PILL_WIDTH))
        elements.append(Spacer(1, 0.1 * inch))

        body = raw
        if CR.iris_config().redact_pii_in_reports:
            headers = parse_raw_headers(raw)
            surfaced_addresses = [
                parseaddr(headers.get(name, ""))[1]
                for name in ("from", "to", "reply-to", "return-path")
            ]
            body = redact_pii(raw, keep_emails=surfaced_addresses)

        # Escape so reportlab's mini-markup doesn't choke on raw header text.
        escaped = (
            body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        for line in escaped.splitlines():
            elements.append(Paragraph(line if line.strip() else "&nbsp;", theme.mono))
