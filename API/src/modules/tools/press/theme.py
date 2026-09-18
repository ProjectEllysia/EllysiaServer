"""
Tema visual de los informes PDF: paleta y estilos.

Nació en Themis (extraído del antiguo ``reports.py`` de 85 KB, el fichero más
grande del repositorio), pasó por ``shared/`` cuando Hygeia también empezó a
imprimir y vive aquí desde que existe ``tools/press``. No sabe nada de
escaneos, activos ni correos: solo importa ``reportlab``, así que cualquier
módulo que genere un PDF puede heredarlo y salir con la misma cara que el
resto del producto.

A propósito **no** se reexporta desde ``src.modules.tools``: ese ``__init__``
es una hoja sin imports, y colgar de él la carga de ``reportlab`` la pagaría
todo el que importe cualquier otra herramienta. Quien imprime, importa
``tools.press``.
"""

from enum import Enum
from typing import Dict, Mapping, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Table, TableStyle


class ColorType(Enum):
    """Los seis papeles de color que usa cualquier informe.

    Un informe no elige colores sueltos: elige un papel para cada uno, y la
    paleta de cada módulo dice qué tinta le corresponde. Así el mismo código
    de composición sirve para el azul de Nmap y para el violeta de Iris.
    """
    BLACK       = "black"
    DARK        = "dark"
    MAIN        = "main"
    SECONDARY   = "secondary"
    LIGHT       = "light"
    WHITE       = "white"


def build_palette(
    configured: Optional[Mapping[str, str]],
    fallback: Mapping[str, str],
) -> Dict[ColorType, str]:
    """Compone la paleta de un informe a partir de la configuración y su respaldo.

    Cada consumidor tenía escrito su propio bucle de seis líneas idénticas
    (``ColorType.BLACK: config.get("black", defaults["black"])``, y así con los
    seis). Aquí se escribe una vez: el módulo aporta sus colores de respaldo
    —los que definen su identidad visual y viajan con el código— y la
    configuración solo los sobrescribe si el operador los ha tocado.

    Args:
        configured: Colores leídos de ``SecOpsConfig.json``, indexados por el
            nombre del papel en minúsculas (``"black"``, ``"dark"``, ``"main"``,
            ``"secondary"``, ``"light"``, ``"white"``). Puede venir vacío o
            ``None`` si ese bloque no está en el JSON, y entonces se usa el
            respaldo entero. Las claves que no correspondan a un ``ColorType``
            se ignoran.
        fallback: Colores de respaldo del módulo, con las mismas claves. Debe
            traer los seis: un papel sin tinta es un ``KeyError`` al componer
            el tema, y es preferible que salte aquí.

    Returns:
        Dict[ColorType, str]: Los seis papeles con su color en hexadecimal
            (``"#RRGGBB"``), listos para ``ReportTheme``.
    """
    configured = configured or {}
    return {
        color_type: configured.get(color_type.value, fallback[color_type.value])
        for color_type in ColorType
    }


class ReportTheme:
    """Estilos de párrafo y de tabla compartidos por todos los informes.

    Traduce una paleta en el juego de estilos concreto con el que se compone un
    documento —títulos, cuerpo, etiquetas, celdas, tablas clave-valor— y ofrece
    las piezas compuestas que se repiten en todos los informes (cabecera de
    sección, tarjeta con banda de color, cabecera de severidad).

    Attributes:
        palette: Los seis colores del informe, indexados por ``ColorType``.
            Normalmente viene de ``build_palette``.
        styles: Hoja de estilos base de ReportLab
            (``getSampleStyleSheet()``), de la que heredan todos los estilos
            propios.
        title: Título de sección: 20 puntos, centrado, en negro.
        subtitle: Subtítulo de bloque: 9 puntos, centrado, en el color
            principal.
        pill: Texto de una píldora o etiqueta: 7 puntos, centrado, en blanco
            —va siempre sobre un fondo de color.
        info: Texto informativo suelto: 9 puntos, alineado a la izquierda, en
            el color principal.
        body: Cuerpo del informe: 9 puntos, justificado, en negro.
        label: Pie de figura o aclaración: 7 puntos, en negrita y en el color
            principal.
        footer: Pie de página: 8 puntos, centrado, en gris.
        mono: Texto que debe respetarse carácter a carácter (cabeceras de
            correo en crudo, volcados): 7,5 puntos en Courier.
        cell_left: Celda de tabla alineada a la izquierda. Parte las palabras
            si una sola no cabe en la columna (``wordWrap="CJK"``), que es lo
            que pasa con un hostname o un nombre de fichero largo.
        cell_center: Igual que ``cell_left``, centrada.
        cell_header: Igual que ``cell_left``, centrada, en negrita y en blanco
            —va sobre el fondo de color de la fila de cabecera.
        kv_table_style: Estilo de las tablas de dos columnas clave-valor.
    """

    def __init__(self, base_styles, palette: Mapping[ColorType, str]) -> None:
        """Construye el juego de estilos de un informe.

        Args:
            base_styles: Hoja de estilos base de ReportLab, tal como la
                devuelve ``getSampleStyleSheet()``.
            palette: Los seis colores del informe, indexados por ``ColorType``
                y en hexadecimal. Deben estar los seis.
        """
        self.palette = palette
        self.styles = base_styles

        main = colors.HexColor(palette[ColorType.MAIN])
        light = colors.HexColor(palette[ColorType.LIGHT])
        white = colors.HexColor(palette[ColorType.WHITE])
        black = colors.HexColor(palette[ColorType.BLACK])

        self._accent_color = light

        self.title = ParagraphStyle(
            "ReportTitle",
            parent=base_styles["Heading1"],
            fontSize=20,
            leading=24,
            textColor=black,
            alignment=TA_CENTER,
            spaceBefore=6,
            spaceAfter=4,
            fontName="Helvetica-Bold",
        )

        self.subtitle = ParagraphStyle(
            "ReportSubtitle",
            parent=base_styles["Heading2"],
            fontSize=9,
            leading=12,
            textColor=main,
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=2,
            fontName="Helvetica-Bold",
        )

        self.pill = ParagraphStyle(
            "Pill",
            parent=base_styles["Normal"],
            fontSize=7,
            leading=9,
            textColor=white,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
        )

        self.info = ParagraphStyle(
            "Info",
            parent=base_styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=main,
            alignment=TA_LEFT,
        )

        self.body = ParagraphStyle(
            "Body",
            parent=base_styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=black,
            alignment=TA_JUSTIFY,
            spaceAfter=5,
        )

        self.label = ParagraphStyle(
            "Label",
            parent=base_styles["Normal"],
            fontSize=7,
            leading=9,
            textColor=main,
            alignment=TA_LEFT,
            fontName="Helvetica-Bold",
        )

        self.footer = ParagraphStyle(
            "Footer",
            parent=base_styles["Normal"],
            fontSize=8,
            leading=9,
            textColor=colors.HexColor("#aaaaaa"),
            alignment=TA_CENTER,
        )

        self.mono = ParagraphStyle(
            "Mono",
            parent=base_styles["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=black,
            fontName="Courier",
        )

        # Celdas de tabla: envuelven (y, si una sola palabra es más ancha que
        # la columna, la parten) en vez de desbordar el ancho fijo. Un `str`
        # suelto dentro de una `Table` de ReportLab no hace wrap: se sale de la
        # columna, y en una tabla de hostnames o de nombres de software eso
        # pasa constantemente.
        self.cell_left = ParagraphStyle(
            "CellLeft",
            parent=base_styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=black,
            alignment=TA_LEFT,
            wordWrap="CJK",
        )

        self.cell_center = ParagraphStyle(
            "CellCenter",
            parent=self.cell_left,
            alignment=TA_CENTER,
        )

        self.cell_header = ParagraphStyle(
            "CellHeader",
            parent=self.cell_left,
            textColor=white,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
        )

        self.kv_table_style = TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), white),
            ("TEXTCOLOR", (0, 0), (0, -1), main),
            ("TEXTCOLOR", (1, 0), (1, -1), black),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.4, light),
        ])

    def kv_table(self, data, col_widths) -> Table:
        """Compone una tabla de dos columnas clave-valor.

        Args:
            data: Filas de la tabla, cada una ``[clave, valor]``.
            col_widths: Anchos de las dos columnas, en unidades de ReportLab.

        Returns:
            Table: La tabla con el estilo clave-valor ya aplicado.
        """
        table = Table(data, colWidths=col_widths)
        table.setStyle(self.kv_table_style)
        return table

    def section_header(
        self,
        title_text: str,
        tag_text: str,
        pill_width: float = 1.8 * inch,
    ) -> list:
        """Compone la cabecera de una sección: píldora, título y línea de acento.

        Args:
            title_text: Título de la sección, centrado y a 20 puntos.
            tag_text: Rótulo de la píldora que va encima del título. Se imprime
                en mayúsculas.
            pill_width: Ancho de la píldora, en unidades de ReportLab. Por
                defecto ``1.8 * inch``, que acoge rótulos de hasta unos 25
                caracteres; los informes con rótulos más largos lo suben.

        Returns:
            list: Los tres flowables de la cabecera, en orden — píldora
                centrada, título centrado y línea de acento.
        """
        main = colors.HexColor(self.palette[ColorType.MAIN])
        accent = self._accent_color

        # Píldora centrada
        pill_para = Paragraph(tag_text.upper(), self.pill)
        pill_table = Table([[pill_para]], colWidths=[pill_width])
        pill_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), main),
            ("BOX", (0, 0), (-1, -1), 0.7, main),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

        pill_wrapper = Table([[pill_table]], colWidths=[6 * inch])
        pill_wrapper.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

        # Título centrado
        title_para = Paragraph(title_text, self.title)
        title_wrapper = Table([[title_para]], colWidths=[6 * inch])
        title_wrapper.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

        # Línea de acento
        divider = Table([[""]], colWidths=[2.5 * inch], rowHeights=[0.035 * inch])
        divider.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        divider_wrapper = Table([[divider]], colWidths=[6 * inch])
        divider_wrapper.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        return [pill_wrapper, title_wrapper, divider_wrapper]

    def card(self, inner_flowables, severity_color=None) -> Table:
        """Envuelve un bloque en una tarjeta con borde y banda de color.

        Es la presentación de todo lo que se enumera: una vulnerabilidad, un
        incidente, una recomendación.

        Args:
            inner_flowables: Contenido de la tarjeta; una lista de flowables de
                ReportLab, o un único flowable.
            severity_color: Color de la banda vertical izquierda, que es lo que
                permite leer la gravedad de un vistazo sin llegar al texto.
                Por defecto ``None``, y entonces se usa el color principal de
                la paleta.

        Returns:
            Table: La tarjeta completa, de 6 pulgadas de ancho.
        """
        white = colors.HexColor(self.palette[ColorType.WHITE])
        border = colors.HexColor("#DDDDDD")
        band_color = severity_color or colors.HexColor(self.palette[ColorType.MAIN])

        # banda vertical + contenido
        band = Table([[""]], colWidths=[0.12 * inch])
        band.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), band_color),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        content_table = Table([[inner_flowables]], colWidths=[5.8 * inch])
        content_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))

        outer = Table([[band, content_table]], colWidths=[0.12 * inch, 5.88 * inch])
        outer.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.7, border),
            ("BACKGROUND", (0, 0), (-1, -1), white),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return outer

    def severity_header_table(self, left_text: str, right_text: str, bg_color) -> Table:
        """Compone la barra que encabeza un grupo de hallazgos de la misma gravedad.

        Args:
            left_text: Texto de la izquierda; normalmente el nombre de la
                gravedad.
            right_text: Texto de la derecha; normalmente el recuento del grupo.
            bg_color: Color de fondo de la barra, ya como objeto de color de
                ReportLab.

        Returns:
            Table: La barra, de 6 pulgadas de ancho repartidas a partes
                iguales entre los dos textos.
        """
        data = [[left_text, right_text]]
        table = Table(data, colWidths=[3 * inch, 3 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_color),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(self.palette[ColorType.BLACK])),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(self.palette[ColorType.LIGHT])),
        ]))
        return table
