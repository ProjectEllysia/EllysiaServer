"""
``CloudExposurePDFCreator``: el informe de un escaneo de exposición cloud.

Un escaneo cloud no es un ``Scan``: no tiene equipo ni puertos, y sus hallazgos
viajan dentro de la fila ``OsintScan``. Por eso no entra por el registro de
``PrintingStrategy`` —que resuelve el cuerpo a partir del tipo de un
``Scan``— sino que es un generador propio sobre ``tools.press``, con la misma
identidad visual que el informe de Lybra, que es el motor que hizo las
comprobaciones.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import CondPageBreak, Paragraph, Spacer, Table, TableStyle

import src.modules.system.config_reading as CR

from src.modules.tools.press import ColorType, DocumentStyle, PdfGenerator, ReportTheme, build_palette, safe_markup
from ...lybra.compliance import map_finding_compliance
from ...model import ScanType
from .creator import CONSENT_TEXT, LOGO_DIRECTORY
from .findings import SEVERITY_BACKGROUNDS, compliance_rows
from .lybra import LYBRA_DEFAULT_PALETTE

#: Orden de las fichas: de la más grave a la menos.
_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

#: Rótulo de cada gravedad, igual que en el informe de hallazgos de Lybra.
_SEVERITY_LABEL = {"CRITICAL": "CRÍTICA", "HIGH": "ALTA", "MEDIUM": "MEDIA", "LOW": "BAJA", "INFO": "INFO"}

#: Cómo se nombra cada gravedad en el recuento del alcance, en singular y plural.
_SEVERITY_COUNT_WORDS = {
    "CRITICAL": ("crítica", "críticas"), "HIGH": ("alta", "altas"), "MEDIUM": ("media", "medias"),
    "LOW": ("baja", "bajas"), "INFO": ("informativa", "informativas"),
}

#: Mismo logotipo que el informe de un escaneo Lybra.
_LOGO_FILENAME = "Themis-Turqoise-BgW.png"


@dataclass(frozen=True)
class _Explanation:
    """Lo que significa una clase de exposición y cómo se corrige, en lenguaje llano.

    Attributes:
        kind: Qué se comprobó, como rótulo corto («Bucket de Amazon S3 que
            lista su contenido»).
        meaning: Qué puede hacer cualquiera por culpa de esta exposición.
        remedy: Qué hay que hacer para cerrarla.
    """

    kind: str
    meaning: str
    remedy: str


_STORAGE_MEANING = ("Cualquier persona en Internet, sin cuenta ni contraseña, puede ver la lista de "
                    "ficheros que guarda y descargar los que no tengan permisos propios.")

#: Explicación de cada comprobación, por el nombre del check sin espacio de
#: nombres ni versión. Los de takeover se reconocen por su prefijo, porque hay
#: uno por proveedor del catálogo de firmas.
_EXPLANATIONS: Dict[str, _Explanation] = {
    "cloud-s3-public-bucket": _Explanation(
        "Bucket de Amazon S3 que lista su contenido", _STORAGE_MEANING,
        "Activa el bloqueo de acceso público del bucket (Block Public Access), retira las "
        "políticas que den lectura a todo el mundo y revisa qué ficheros han podido descargarse."),
    "cloud-gcs-public-bucket": _Explanation(
        "Bucket de Google Cloud Storage que lista su contenido", _STORAGE_MEANING,
        "Activa la prevención de acceso público del bucket, quita los permisos de «allUsers» y "
        "«allAuthenticatedUsers» y revisa qué ficheros han podido descargarse."),
    "cloud-azure-public-container": _Explanation(
        "Contenedor de Azure Blob que lista su contenido", _STORAGE_MEANING,
        "Cambia el nivel de acceso del contenedor a «Privado», desactiva el acceso anónimo en la "
        "cuenta de almacenamiento y revisa qué ficheros han podido descargarse."),
    "cloud-firebase-open-database": _Explanation(
        "Base de datos de Firebase sin reglas de acceso",
        "Cualquier persona en Internet puede leer la base de datos entera con una sola petición, "
        "sin cuenta ni contraseña.",
        "Define reglas de seguridad que exijan autenticación para leer y escribir, y revisa qué "
        "datos han estado expuestos y durante cuánto tiempo."),
}

_TAKEOVER_EXPLANATION = _Explanation(
    "Subdominio que se puede secuestrar",
    "El subdominio apunta a un servicio de terceros donde el recurso ya no existe. Cualquiera "
    "puede darlo de alta a su nombre en ese servicio y publicar contenido bajo tu dominio: una "
    "página de phishing creíble o una trampa para robar las cookies de tus usuarios.",
    "Borra el registro DNS (el CNAME) que apunta al servicio si ya no lo usas, o vuelve a crear "
    "el recurso en el proveedor para que nadie más pueda reclamarlo.")

_UNKNOWN_EXPLANATION = _Explanation(
    "Exposición en la nube",
    "Un recurso en la nube responde a cualquiera sin credenciales.",
    "Revisa los permisos de acceso público del recurso.")


def _check_name(check_id: Optional[str]) -> str:
    """El nombre de un check sin espacio de nombres ni versión.

    Args:
        check_id: El ``check_id`` del hallazgo (``"lybra:cloud-s3-public-bucket@1"``),
            o ``None``.

    Returns:
        str: ``"cloud-s3-public-bucket"``; cadena vacía si no hay check.
    """
    name = (check_id or "").split(":", 1)[-1]
    return name.split("@", 1)[0]


def _explanation_for(finding: dict) -> _Explanation:
    """La explicación en lenguaje llano de un hallazgo cloud.

    Args:
        finding: El hallazgo tal como se guarda en ``OsintScan.findings``.

    Returns:
        _Explanation: La de su comprobación; la de takeover para cualquier
            ``cloud-takeover-*``, y una genérica para un check que este informe
            aún no conoce.
    """
    name = _check_name(finding.get("check_id"))
    if name.startswith("cloud-takeover-"):
        return _TAKEOVER_EXPLANATION
    return _EXPLANATIONS.get(name, _UNKNOWN_EXPLANATION)


def _sorted_findings(findings: List[dict]) -> List[dict]:
    """Los hallazgos de más grave a menos, y a igual gravedad por su sujeto.

    Args:
        findings: Los hallazgos del escaneo.

    Returns:
        List[dict]: Una lista nueva, ordenada.
    """
    return sorted(findings, key=lambda finding: (_SEVERITY_ORDER.get(finding.get("severity"), 5),
                                                 finding.get("service") or ""))


def _scan_date(osint_scan) -> datetime:
    """La fecha del escaneo, para la portada y los metadatos.

    Args:
        osint_scan: La fila ``OsintScan``.

    Returns:
        datetime: El inicio del escaneo, o ahora si no consta.
    """
    return osint_scan.started_at or datetime.now()


def _scope_rows(osint_scan, findings: List[dict]) -> List[List[str]]:
    """Las filas de la tabla de alcance: qué se comprobó y cuánto se encontró.

    Args:
        osint_scan: La fila ``OsintScan``.
        findings: Sus hallazgos.

    Returns:
        List[List[str]]: Pares ``[rótulo, valor]``.
    """
    parameters = osint_scan.parameters or {}
    resources = list(parameters.get("cloud_resources") or [])
    subdomains = osint_scan.subdomains or []
    if parameters.get("check_subdomains"):
        subdomain_text = (f"Comprobados: {len(subdomains)} conocidos" if subdomains
                          else "Comprobado el propio dominio; no había subdominios conocidos")
    else:
        subdomain_text = "No se pidió comprobarlos"
    counts: Dict[str, int] = {}
    for finding in findings:
        severity = finding.get("severity") or "INFO"
        counts[severity] = counts.get(severity, 0) + 1
    summary = ", ".join(f"{counts[level]} {_SEVERITY_COUNT_WORDS[level][counts[level] != 1]}"
                        for level in _SEVERITY_ORDER if counts.get(level))
    return [
        ["Dominio:", osint_scan.domain],
        ["Recursos comprobados:", ", ".join(resources) if resources else "Ninguno declarado"],
        ["Subdominios:", subdomain_text],
        ["Hallazgos:", f"{len(findings)} ({summary})" if findings else "Ninguno"],
    ]


def _append_finding_card(theme: ReportTheme, elements: list, finding: dict, position: int, *,
                         palette, frameworks: tuple) -> None:
    """La ficha de un hallazgo: gravedad, título y qué hacer con él.

    Args:
        theme: Los estilos del informe.
        elements: Lista de flowables; se amplía en sitio.
        finding: El hallazgo, tal como se guarda en ``OsintScan.findings``.
        position: Su número dentro del informe, desde 1.
        palette: La paleta del informe, indexada por ``ColorType``.
        frameworks: Los marcos de cumplimiento del dueño.
    """
    severity = finding.get("severity") or "INFO"
    explanation = _explanation_for(finding)
    elements.append(CondPageBreak(2.5 * inch))
    elements.append(theme.severity_header_table(
        left_text=f"Hallazgo #{position}: {_SEVERITY_LABEL.get(severity, severity)}",
        right_text="Comprobado",
        bg_color=SEVERITY_BACKGROUNDS.get(severity, SEVERITY_BACKGROUNDS["INFO"]),
    ))
    title = Table([[Paragraph(safe_markup(finding.get("title") or ""), ParagraphStyle(
        "CloudFindingTitle", parent=theme.styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, textColor=colors.whitesmoke, alignment=TA_LEFT))]], colWidths=[6 * inch])
    title.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(palette[ColorType.MAIN])),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(palette[ColorType.DARK])),
    ]))
    elements.append(title)

    compliance = map_finding_compliance(finding.get("category"), finding.get("check_id"),
                                        [framework.key for framework in frameworks])
    value_style = ParagraphStyle("CloudFindingValue", parent=theme.body, fontSize=8.5,
                                 leading=10.5, alignment=TA_LEFT)
    rows = [
        ["Qué se comprobó:", Paragraph(safe_markup(explanation.kind), value_style)],
        ["Afecta a:", Paragraph(safe_markup(finding.get("service") or "—"), value_style)],
        ["Qué significa:", Paragraph(safe_markup(explanation.meaning), value_style)],
        ["Cómo corregirlo:", Paragraph(safe_markup(explanation.remedy), value_style)],
    ]
    rows.extend(compliance_rows(theme, compliance, frameworks))
    details = Table(rows, colWidths=[1.7 * inch, 4.3 * inch])
    details.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9f9f9")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(palette[ColorType.BLACK])),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(details)
    elements.append(Spacer(1, 0.2 * inch))


class CloudExposurePDFCreator(PdfGenerator):
    """Compone el informe PDF de un escaneo de exposición cloud.

    Recibe los datos ya cargados, como los generadores de Iris y Hygeia: el
    manager lee la fila y los marcos de cumplimiento del dueño, y el generador
    solo dibuja.

    Attributes:
        osint_scan: La fila ``OsintScan`` del escaneo, en modo ``cloud`` y ya
            terminado.
        frameworks: Los ``ComplianceFramework`` del dueño, en el orden del
            catálogo; vacía si no ha elegido ninguno, y entonces cada ficha
            solo enseña las técnicas de MITRE ATT&CK.
        document_id: Clave primaria del ``ThemisDocument``; va en el nombre del
            fichero para que dos informes del mismo escaneo no se pisen.
        directory: Directorio de salida de los informes de Themis.
    """

    def __init__(self, osint_scan, frameworks: tuple = (), document_id: Optional[int] = None) -> None:
        """Prepara el generador con la identidad visual de Lybra.

        Args:
            osint_scan: La fila ``OsintScan`` del escaneo cloud.
            frameworks: Los marcos de cumplimiento del dueño. Por defecto
                ninguno.
            document_id: Clave primaria del ``ThemisDocument``. Por defecto
                ``None``, y entonces el nombre del fichero depende solo del
                escaneo.
        """
        super().__init__(DocumentStyle(
            palette=build_palette(CR.get_tool_color_palette(ScanType.LYBRA), LYBRA_DEFAULT_PALETTE),
            header_title="Ellysia Security Report",
            logo_path=str(LOGO_DIRECTORY / _LOGO_FILENAME),
        ))
        self.osint_scan = osint_scan
        self.frameworks = frameworks
        self.document_id = document_id
        self.directory = CR.get_directory_of(CR.DirectoryType.OUTPUT_THEMIS)

    def cover_title(self) -> str:
        """Título de la portada.

        Returns:
            str: ``"Exposición en la nube"``.
        """
        return "Exposición en la nube"

    def cover_subtitle(self) -> Optional[str]:
        """Subtítulo de la portada: el dominio del que se informa.

        Returns:
            Optional[str]: El dominio normalizado.
        """
        return self.osint_scan.domain

    def cover_fields(self) -> Sequence[Sequence[str]]:
        """Ficha de la portada: el dominio y la fecha del escaneo.

        Returns:
            Sequence[Sequence[str]]: Dos filas.
        """
        return [["Dominio:", self.osint_scan.domain], ["Fecha:", _scan_date(self.osint_scan).strftime("%d/%m/%Y")]]

    def document_title(self) -> str:
        """Título de los metadatos del PDF.

        Returns:
            str: ``"Exposición en la nube - <dominio>"``.
        """
        return f"Exposición en la nube - {self.osint_scan.domain}"

    def document_subject(self) -> str:
        """Asunto de los metadatos del PDF.

        Returns:
            str: Una frase con la fecha del escaneo.
        """
        return f"Comprobación de exposición en la nube realizada el {_scan_date(self.osint_scan).strftime('%d/%m/%Y')}"

    def legal_notice(self) -> Tuple[str, str]:
        """La misma declaración de consentimiento que el resto de informes de Themis.

        Returns:
            Tuple[str, str]: El título del recuadro y su texto.
        """
        return ("DECLARACIÓN DE CONFORMIDAD Y CONSENTIMIENTO", CONSENT_TEXT)

    def append_body(self, elements: list, theme: ReportTheme) -> None:
        """Dibuja el alcance, el resumen y una ficha por hallazgo.

        Args:
            elements: Lista de flowables del documento en construcción.
            theme: Los estilos del informe.
        """
        findings = _sorted_findings(list(self.osint_scan.findings or []))
        elements.extend(theme.section_header("Exposición en la nube", "Lybra · Nube"))
        elements.append(Spacer(1, 0.12 * inch))
        elements.append(Paragraph(
            "Este informe recoge lo que Lybra comprobó, sin usar credenciales, sobre los recursos en "
            f"la nube que declaraste de <b>{safe_markup(self.osint_scan.domain)}</b> y sobre sus "
            "subdominios conocidos. Una comprobación sin credenciales es exactamente lo que puede "
            "hacer cualquier persona en Internet.", theme.body))
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(theme.kv_table(_scope_rows(self.osint_scan, findings), [1.9 * inch, 4.1 * inch]))
        elements.append(Spacer(1, 0.2 * inch))

        if not findings:
            elements.append(Paragraph(
                "No se encontró ningún recurso que liste su contenido ni ningún subdominio que se "
                "pueda secuestrar.", theme.info))
        for position, finding in enumerate(findings, start=1):
            _append_finding_card(theme, elements, finding, position,
                                 palette=self.style.palette, frameworks=self.frameworks)

        elements.append(Spacer(1, 0.1 * inch))
        elements.append(Paragraph(
            "Lybra solo comprueba los recursos que declaras: no busca buckets ni bases de datos por "
            "su cuenta. Un recurso que no aparece en el alcance no se ha comprobado, y su ausencia en "
            "este informe no significa que esté bien protegido.", theme.body))

    def output_path(self) -> str:
        """Ruta del PDF, única por documento.

        Returns:
            str: ``<dir>/domain_<escaneo>_<documento>_Nube.pdf``.
        """
        stem = (f"domain_{self.osint_scan.id}_{self.document_id}" if self.document_id
                else f"domain_{self.osint_scan.id}")
        return os.path.join(self.directory, f"{stem}_Nube.pdf")

    def print_pdf(self) -> str:
        """Genera el informe y lo deja escrito en disco.

        Returns:
            str: La ruta del PDF generado.
        """
        return self.generate_to_file(self.output_path())
