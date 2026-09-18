"""
``PdfGenerator``: la composición de un informe, una sola vez.

Todos los informes de Ellysia tienen la misma anatomía —portada con banda de
título y ficha de datos, cuerpo, nota legal, pie, y en cada página una barra de
acento, una cabecera y el número de página—, y hasta ahora cada módulo la
dibujaba por su cuenta. Aquí se escribe una vez.

Es un **método plantilla**: ``generate()`` fija el orden del documento y llama
a una serie de ganchos. Casi todos traen implementación por defecto, así que un
generador concreto solo escribe lo suyo; los dos que no pueden tener valor por
defecto —el título de la portada y el cuerpo— son abstractos.
"""

import logging
import os
import uuid

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Dict, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import src.modules.system.config_reading as CR

from .theme import ColorType, ReportTheme

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentStyle:
    """Identidad visual y geometría de los informes de un módulo.

    Es lo que no cambia entre dos documentos del mismo módulo: los colores, el
    logotipo, el rótulo de la cabecera y los márgenes. Lo que sí cambia de un
    documento a otro —el título, la fecha, los datos de la ficha— sale de los
    ganchos de ``PdfGenerator``, no de aquí.

    Attributes:
        palette: Los seis colores del informe, indexados por ``ColorType``.
            Normalmente construida con ``build_palette``.
        header_title: Rótulo de la cabecera de las páginas interiores, por
            ejemplo ``"Ellysia · Inventario de activos"``. Es lo que distingue
            de un vistazo dos informes del mismo producto.
        logo_path: Ruta absoluta del logotipo, que se dibuja en la portada y en
            la esquina de cada página interior. Por defecto ``None``, y
            entonces el informe se imprime sin él. Si la ruta apunta a un
            fichero que no existe se avisa por el log y se sigue igual: un
            informe sin logotipo es feo, uno que revienta al generarse es un
            fallo.
        page_size: Tamaño de página como ``(ancho, alto)`` en puntos. Por
            defecto ``A4``.
        left_margin: Margen izquierdo en puntos. Por defecto ``36`` (media
            pulgada).
        right_margin: Margen derecho en puntos. Por defecto ``36``.
        top_margin: Margen superior en puntos. Por defecto ``60``, que deja
            sitio a la cabecera de las páginas interiores.
        bottom_margin: Margen inferior en puntos. Por defecto ``40``, que deja
            sitio al número de página.
        author: Autor que se graba en los metadatos del PDF. Por defecto
            ``"Ellysia Security Team"``.
    """

    palette: Dict[ColorType, str]
    header_title: str
    logo_path: Optional[str] = None
    page_size: Tuple[float, float] = A4
    left_margin: float = 36
    right_margin: float = 36
    top_margin: float = 60
    bottom_margin: float = 40
    author: str = "Ellysia Security Team"


class PdfGenerator(ABC):
    """Compone un informe PDF a partir de las piezas que aporte cada módulo.

    Un generador concreto hereda de aquí, pasa su ``DocumentStyle`` al
    constructor del padre y recibe por el suyo propio lo que necesite para
    dibujar su contenido —ya cargado: esta capa dibuja, no consulta—. De los
    ganchos solo tiene que implementar los dos abstractos; el resto ya hacen
    algo razonable y se redefinen cuando el documento lo pida.

    El orden del documento lo fija ``generate()`` y no se puede alterar sin
    redefinirlo:

    1. Portada: logotipo, banda de título, subtítulo, ficha de datos, bloque
       libre y barra decorativa.
    2. Cuerpo (``append_body``).
    3. Nota legal, si el módulo aporta una.
    4. Pie.

    Y en cada página interior, ``draw_page_furniture`` pinta la barra de
    acento, la cabecera, el logotipo pequeño y el número de página. La portada
    se queda limpia a propósito: una cabecera y un pie en la página 1 son
    justamente lo que hace que una portada no parezca una portada.

    Attributes:
        style: La identidad visual y la geometría del documento.
        theme: Los estilos de párrafo y de tabla derivados de la paleta. Se
            construye una vez, la primera vez que se pide.
    """

    def __init__(self, style: DocumentStyle) -> None:
        """Prepara el generador.

        Args:
            style: Identidad visual y geometría del documento.
        """
        self.style = style
        self._theme: Optional[ReportTheme] = None

    @property
    def theme(self) -> ReportTheme:
        """Los estilos del informe, construidos a demanda.

        Returns:
            ReportTheme: El tema derivado de ``style.palette``. Siempre la
                misma instancia dentro de un generador.
        """
        if self._theme is None:
            self._theme = ReportTheme(getSampleStyleSheet(), self.style.palette)
        return self._theme

    # =========================================================================
    # LO QUE APORTA CADA MÓDULO
    # =========================================================================

    @abstractmethod
    def cover_title(self) -> str:
        """El título que va en la banda de color de la portada.

        Es abstracto porque no tiene valor por defecto honrado: el rótulo de la
        cabecera nombra al módulo ("Ellysia · Inventario de activos") y usarlo
        como título de portada diría el nombre del producto donde debería decir
        el del documento.

        Returns:
            str: El título, tal cual debe imprimirse. Si viene de datos que no
                hemos escrito nosotros, pásalo antes por ``safe_markup``.
        """

    @abstractmethod
    def append_body(self, elements: list, theme: ReportTheme) -> None:
        """Añade el cuerpo del informe: lo único que no puede vivir aquí.

        Args:
            elements: Lista de flowables del documento en construcción, a la
                que hay que añadir. Ya trae la portada.
            theme: Los estilos del informe, por comodidad; es el mismo objeto
                que ``self.theme``.
        """

    def cover_subtitle(self) -> Optional[str]:
        """El subtítulo que va bajo la banda de título de la portada.

        Returns:
            Optional[str]: El subtítulo, o ``None`` —el valor por defecto— para
                no imprimir ninguno.
        """
        return None

    def cover_caption(self) -> Optional[str]:
        """La apostilla que va bajo el subtítulo de la portada, más pequeña.

        Es para la precisión que el subtítulo no debe cargar: el periodo que
        cubre un informe de estadísticas, por ejemplo, cuando el subtítulo ya
        dice de qué activo habla.

        Returns:
            Optional[str]: La apostilla, o ``None`` —el valor por defecto— para
                no imprimir ninguna. Se ignora si no hay subtítulo: sin él no
                hay nada que apostillar.
        """
        return None

    def cover_fields(self) -> Sequence[Sequence[str]]:
        """Las filas de la ficha enmarcada de la portada.

        Por defecto, solo la fecha de generación.

        Returns:
            Sequence[Sequence[str]]: Filas de dos celdas, ``[etiqueta, valor]``.
                La etiqueta lleva sus dos puntos ("Cliente:"). Una secuencia
                vacía deja la portada sin ficha.
        """
        return [["Fecha:", self.generated_at().strftime("%d/%m/%Y")]]

    def cover_extra(self) -> list:
        """Bloque libre de la portada, entre la ficha y la barra decorativa.

        Es donde cabe un resumen que merece verse antes de abrir el documento:
        el recuento de activos por estado del inventario de Hygeia, por
        ejemplo.

        Returns:
            list: Flowables a intercalar. Vacía por defecto.
        """
        return []

    def legal_notice(self) -> Optional[Tuple[str, str]]:
        """La nota legal que cierra el documento, si el módulo tiene una.

        Returns:
            Optional[Tuple[str, str]]: ``(título, texto)`` de la nota, o
                ``None`` —el valor por defecto— para no imprimirla. El texto se
                imprime justificado dentro de un recuadro; los saltos de línea
                simples del código fuente no se respetan.
        """
        return None

    def document_title(self) -> str:
        """El título que se graba en los metadatos del PDF.

        Es lo que ve un lector de PDF en la barra de la ventana, y no tiene por
        qué coincidir con el de la portada: aquí suele convenir el
        identificador del documento.

        Returns:
            str: El título. Por defecto, el de la portada.
        """
        return self.cover_title()

    def document_subject(self) -> str:
        """El asunto que se graba en los metadatos del PDF.

        Returns:
            str: El asunto. Por defecto, el rótulo de la cabecera.
        """
        return self.style.header_title

    def generated_at(self) -> datetime:
        """El instante que figura como fecha de generación del documento.

        Se aísla en un gancho para que un test pueda fijarlo y comparar dos
        documentos byte a byte.

        Returns:
            datetime: Por defecto, ahora.
        """
        return datetime.now()

    # =========================================================================
    # LA COMPOSICIÓN
    # =========================================================================

    def generate(self) -> bytes:
        """Compone el documento entero y devuelve el PDF.

        Returns:
            bytes: El PDF completo, en memoria. No toca el disco; para eso
                está ``generate_to_file``.
        """
        buffer = BytesIO()
        _build_document(self, buffer)
        buffer.seek(0)
        return buffer.read()

    def generate_to_file(self, path: str) -> str:
        """Compone el documento y lo deja escrito en ``path``.

        Escribe primero en un temporal del mismo directorio y lo mueve con
        ``os.replace()``, que es atómico dentro de un mismo sistema de
        ficheros. Sin eso, quien descargue el informe mientras se regenera
        recibe un PDF a medio escribir: el documento consta como terminado una
        sola vez, pero el fichero al que apunta se reescribe en sitio en cada
        regeneración.

        Args:
            path: Ruta final del PDF. Su directorio se crea si no existe.

        Returns:
            str: La misma ``path`` recibida, por comodidad del llamante.

        Raises:
            Exception: Lo que levante la composición del documento. El temporal
                se borra antes de propagar: su nombre lleva un UUID, así que no
                lo limpiaría nadie ni lo pisaría el siguiente intento.
        """
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"

        try:
            with open(temporary, "wb") as handle:
                _build_document(self, handle)
            os.replace(temporary, path)
        except Exception:
            if os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    logger.warning("No se pudo borrar el temporal %s", temporary)
            raise

        return path

    def append_cover(self, elements: list, theme: ReportTheme) -> None:
        """Añade la portada completa a partir de los ganchos del módulo.

        Args:
            elements: Lista de flowables del documento en construcción.
            theme: Los estilos del informe.
        """
        palette = self.style.palette
        main = colors.HexColor(palette[ColorType.MAIN])
        light = colors.HexColor(palette[ColorType.LIGHT])
        white = colors.HexColor(palette[ColorType.WHITE])
        black = colors.HexColor(palette[ColorType.BLACK])

        logo = _cover_logo(self.style.logo_path)
        if logo is not None:
            elements.append(Spacer(1, 0.9 * inch))
            elements.append(logo)
            elements.append(Spacer(1, 0.45 * inch))
        else:
            elements.append(Spacer(1, 2.5 * inch))

        title_style = ParagraphStyle(
            "CoverTitle",
            parent=theme.styles["Heading1"],
            fontSize=28,
            leading=32,
            textColor=white,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            # Un título largo sin espacios —el asunto de un correo, un
            # hostname— desborda la banda si no se le permite partir palabra.
            wordWrap="CJK",
        )
        title_band = Table([[Paragraph(self.cover_title(), title_style)]], colWidths=[6 * inch])
        title_band.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), main),
            ("TOPPADDING", (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ("LEFTPADDING", (0, 0), (-1, -1), 24),
            ("RIGHTPADDING", (0, 0), (-1, -1), 24),
        ]))
        elements.append(title_band)

        # Como en la nota legal: el gancho devuelve None en la base, que es lo
        # que ve pylint, pero aquí importa lo que devuelva la subclase.
        subtitle = self.cover_subtitle()  # pylint: disable=assignment-from-none
        if subtitle:
            subtitle_style = ParagraphStyle(
                "CoverSubtitle",
                parent=theme.styles["Normal"],
                fontSize=13,
                leading=16,
                textColor=black,
                alignment=TA_CENTER,
            )
            elements.append(Spacer(1, 0.3 * inch))
            elements.append(Paragraph(subtitle, subtitle_style))

            caption = self.cover_caption()  # pylint: disable=assignment-from-none
            if caption:
                caption_style = ParagraphStyle(
                    "CoverCaption",
                    parent=subtitle_style,
                    fontSize=10,
                    textColor=main,
                )
                elements.append(Spacer(1, 0.05 * inch))
                elements.append(Paragraph(caption, caption_style))

        elements.append(Spacer(1, 0.9 * inch if logo is not None else 1.3 * inch))

        fields = self.cover_fields()
        if fields:
            info_table = Table([list(row) for row in fields], colWidths=[1.8 * inch, 3.2 * inch])
            info_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), white),
                ("TEXTCOLOR", (0, 0), (0, -1), main),
                ("TEXTCOLOR", (1, 0), (1, -1), black),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 1, light),
            ]))
            elements.append(info_table)

        extra = self.cover_extra()
        if extra:
            elements.append(Spacer(1, 0.5 * inch))
            elements.extend(extra)
            elements.append(Spacer(1, 0.6 * inch))
        else:
            elements.append(Spacer(1, 1.0 * inch))

        decoration = Table([[""]], colWidths=[6 * inch], rowHeights=[0.12 * inch])
        decoration.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), light)]))
        elements.append(decoration)

        elements.append(PageBreak())

    def append_legal_notice(self, elements: list, theme: ReportTheme) -> None:
        """Añade la nota legal del módulo, si tiene una.

        Args:
            elements: Lista de flowables del documento en construcción.
            theme: Los estilos del informe.
        """
        # El gancho devuelve None en la base, que es justo lo que pylint ve; lo
        # que importa aquí es lo que devuelva la subclase.
        notice = self.legal_notice()  # pylint: disable=assignment-from-none
        if notice is None:
            return

        title_text, body_text = notice
        palette = self.style.palette
        main = colors.HexColor(palette[ColorType.MAIN])
        dark = colors.HexColor(palette[ColorType.DARK])
        white = colors.HexColor(palette[ColorType.WHITE])

        elements.append(PageBreak())

        title_style = ParagraphStyle(
            "LegalNoticeTitle",
            parent=theme.styles["Heading2"],
            fontSize=11,
            textColor=main,
            spaceAfter=10,
            fontName="Helvetica-Bold",
        )
        text_style = ParagraphStyle(
            "LegalNoticeText",
            parent=theme.styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=dark,
            alignment=TA_JUSTIFY,
        )

        elements.append(Paragraph(title_text, title_style))

        box = Table([[Paragraph(body_text.strip(), text_style)]], colWidths=[6 * inch])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), white),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("BOX", (0, 0), (-1, -1), 1.2, main),
        ]))
        elements.append(box)
        elements.append(Spacer(1, 0.3 * inch))

    def append_footer(self, elements: list, theme: ReportTheme) -> None:
        """Añade el pie que cierra el documento.

        Args:
            elements: Lista de flowables del documento en construcción.
            theme: Los estilos del informe.
        """
        timestamp = self.generated_at().strftime("%d/%m/%Y %H:%M:%S")
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(
            Paragraph(f"Informe generado automáticamente | {timestamp}", theme.footer)
        )

    def draw_page_furniture(self, canvas, document) -> None:
        """Pinta el aparejo de las páginas interiores: barra, cabecera y número.

        La portada se salta entera, por lo dicho en la clase.

        Args:
            canvas: Lienzo de la página que ReportLab está cerrando.
            document: El ``SimpleDocTemplate`` en curso; de él sale el tamaño
                de página.
        """
        page_number = canvas.getPageNumber()
        if page_number == 1:
            return

        width, height = document.pagesize
        palette = self.style.palette
        main = colors.HexColor(palette[ColorType.MAIN])
        dark = colors.HexColor(palette[ColorType.DARK])

        canvas.saveState()

        canvas.setFillColor(main)
        canvas.rect(20, 20, 6, height - 40, stroke=0, fill=1)

        canvas.setFont("Helvetica-Bold", 12)
        canvas.setFillColor(dark)
        canvas.drawString(40, height - 30, self.style.header_title)

        canvas.setStrokeColor(colors.HexColor("#e0e0e0"))
        canvas.setLineWidth(0.5)
        canvas.line(36, height - 42, width - 36, height - 42)

        # Dibujar el logotipo en todas las páginas no multiplica el peso:
        # ReportLab cachea la imagen por ruta, así que las N páginas interiores
        # comparten un único objeto embebido.
        logo_path = self.style.logo_path
        if logo_path and os.path.exists(logo_path):
            canvas.drawImage(
                logo_path, width - 52, height - 38,
                width=0.3 * inch, height=0.32 * inch, preserveAspectRatio=True,
            )

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawRightString(width - 40, 28, f"Página {page_number}")

        canvas.restoreState()


def _cover_logo(logo_path: Optional[str]) -> Optional[Image]:
    """El logotipo de la portada, si el módulo tiene uno y está en su sitio.

    Args:
        logo_path: Ruta del logotipo declarada en el ``DocumentStyle``, o
            ``None`` si el módulo no tiene.

    Returns:
        Optional[Image]: La imagen centrada y a 1,15 × 1,23 pulgadas, o
            ``None`` si no hay ruta o el fichero no existe. En este segundo
            caso queda un aviso en el log: un informe sin logotipo es feo, uno
            que revienta al generarse es un fallo.
    """
    if not logo_path:
        return None
    if not os.path.exists(logo_path):
        logger.warning("No se ha encontrado el logotipo del informe: %s", logo_path)
        return None

    logo = Image(logo_path, width=1.15 * inch, height=1.23 * inch)
    logo.hAlign = "CENTER"
    return logo


def _build_document(generator: PdfGenerator, target) -> None:
    """Monta el documento de un generador sobre un destino de ReportLab.

    Args:
        generator: El generador que aporta el estilo y las secciones.
        target: Ruta, fichero abierto en binario o ``BytesIO`` — cualquier cosa
            que acepte ``SimpleDocTemplate``.
    """
    style = generator.style
    theme = generator.theme

    document = SimpleDocTemplate(
        target,
        pagesize=style.page_size,
        leftMargin=style.left_margin,
        rightMargin=style.right_margin,
        topMargin=style.top_margin,
        bottomMargin=style.bottom_margin,
    )
    document.title = generator.document_title()
    document.author = style.author
    document.subject = generator.document_subject()
    document.creator = f"Ellysia {CR.get_app_version()}"

    elements: list = []
    generator.append_cover(elements, theme)
    generator.append_body(elements, theme)
    generator.append_legal_notice(elements, theme)
    generator.append_footer(elements, theme)

    document.build(
        elements,
        onFirstPage=generator.draw_page_furniture,
        onLaterPages=generator.draw_page_furniture,
    )
