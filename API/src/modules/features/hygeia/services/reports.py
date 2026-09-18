"""
Informes PDF de Hygeia: inventario de activos y estadísticas.

Dibuja, no consulta: recibe los datos ya calculados y devuelve los bytes del
PDF. El manager es quien decide el alcance (qué activos, qué juego de datos) y
quien comprueba permisos; aquí solo se pinta lo que llega.

Cada documento se construye sobre un ``BytesIO``, sin tocar el disco. Es lo
que hace innecesarios un directorio de salida, una entrada en
``DirectoryType`` y cualquier limpieza posterior: el PDF se genera, se envía y
desaparece. Si algún día hiciera falta archivarlo, ese es el momento de darle
una fila en ``Document``, no antes.

Inventario (``build_inventory_report``):
    1. Portada — ámbito, autor, fecha y recuento por estado.
    2. Registro de activos — una fila por activo.
    3. Anexo de software — opcional, una tabla por activo, al final.

Estadísticas (``build_stats_report``):
    1. Portada — juego de datos, ámbito y periodo.
    2. Tabla de datos — las mismas cifras que exporta el CSV
       (``services/export.py``), del mismo ``payload`` ya serializado por el
       schema del endpoint: el PDF no puede decir un número distinto del que
       ve el usuario en pantalla porque no calcula nada, solo lo maqueta.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, NamedTuple, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

import src.modules.system.config_reading as CR
from src.modules.tools.press import ColorType, ReportTheme, build_palette

#: Logotipo de Hygeia, dentro del propio módulo.
#:
#: No usa un directorio de recursos configurable como Themis
#: (``DirectoryType.RESOURCES_THEMIS``) a propósito: esa ruta apunta a
#: ``API/resources/themis``, que no existe en el repositorio, así que el logo de
#: sus informes se salta en silencio (``if os.path.exists(...)``). Un recurso
#: que viaja con el código no puede faltar: está en el checkout, en la imagen de
#: Docker y en cualquier despliegue, sin configuración que cuadrar.
#:
#: Es una copia reducida y con paleta de 16 colores del original de la SPA
#: (``assets/images/hygeia/Hygeia-DarkGreen-BgW.png``): se embebe en cada PDF
#: que se genera, y 372 KB por documento para un dibujo de línea a dos tintas
#: no se sostienen.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "resources" / "hygeia-logo.png"

#: Colores de respaldo, iguales al acento de Hygeia en la SPA
#: (``[data-module="hygeia"]`` en ``shared.css``). Se usan si
#: ``features.hygeia.colorPalette`` no está en la configuración.
_FALLBACK_PALETTE = {
    "black":     "#121212",
    "dark":      "#24402c",
    "main":      "#3e6b4a",
    "secondary": "#555b6e",
    "light":     "#5a8f6d",
    "white":     "#f5f5f5",
}

#: Cómo se lee cada estado de presencia en el informe. Coincide con las
#: etiquetas de la SPA (``AssetList.vue``) a propósito: un mismo activo no
#: puede llamarse "stale" en el PDF y "Inestable" en pantalla.
_STATUS_LABELS = {
    "pending": "Pendiente",
    "online":  "En línea",
    "stale":   "Inestable",
    "offline": "Caído",
}

#: Orden en el que se presenta el recuento de la portada: de mejor a peor, que
#: es como se lee un semáforo.
_STATUS_ORDER = ("online", "stale", "offline", "pending")


def _palette() -> Dict[ColorType, str]:
    """Paleta del informe, de la configuración y con respaldo propio."""
    return build_palette(CR.get_hygeia_color_palette(), _FALLBACK_PALETTE)


def _status_label(asset) -> str:
    """El estado tal como debe leerse.

    Un activo que se apaga a propósito no está "caído": es la misma distinción
    que hace la lista de la SPA, y pintarlo como caído en un informe de
    auditoría sería inventarse una incidencia.
    """
    if asset.status == "offline" and asset.is_persistent is False:
        return "Apagado"
    return _STATUS_LABELS.get(asset.status, asset.status or "—")


def _format_datetime(value: Optional[datetime]) -> str:
    """Fecha y hora en formato local legible, o una raya si nunca ocurrió."""
    return value.strftime("%d/%m/%Y %H:%M") if value else "—"


def _cell(text: str, style) -> Paragraph:
    """Celda que sabe partirse en varias líneas.

    Un ``str`` suelto dentro de una ``Table`` de ReportLab no hace *wrap*: se
    sale de la columna. Con ``Paragraph`` sí, y en una tabla de hostnames y
    nombres de software eso pasa constantemente.
    """
    return Paragraph(text or "—", style)


def _data_table_style(theme: ReportTheme, header_rows: int = 1) -> TableStyle:
    """Estilo común de las tablas de datos: cabecera en color, filas cebradas.

    ``header_rows`` es 2 en el anexo de software, donde la primera fila es el
    nombre del activo abarcando las cuatro columnas y la segunda los títulos.
    """
    main = colors.HexColor(theme.palette[ColorType.MAIN])
    dark = colors.HexColor(theme.palette[ColorType.DARK])
    light = colors.HexColor(theme.palette[ColorType.LIGHT])
    white = colors.HexColor(theme.palette[ColorType.WHITE])
    last_header = header_rows - 1

    commands = [
        ("BACKGROUND",    (0, 0), (-1, last_header), main),
        ("TEXTCOLOR",     (0, 0), (-1, last_header), white),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.4, light),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1),
                          [colors.white, colors.HexColor("#f2f5f2")]),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    if header_rows == 2:
        # La fila del activo, más oscura y a todo lo ancho, para que se lea como
        # un título y no como una fila más de la tabla.
        commands += [
            ("SPAN",          (0, 0), (-1, 0)),
            ("BACKGROUND",    (0, 0), (-1, 0), dark),
            ("TOPPADDING",    (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("LEFTPADDING",   (0, 0), (-1, 0), 8),
        ]

    return TableStyle(commands)


def _cover(
    theme: ReportTheme, assets: Sequence, scope_label: str, author: str,
    generated_at: datetime,
) -> list:
    """Portada del informe.

    Sigue el molde de los informes de Themis (``reports/creator.py``,
    ``append_cover_page``): banda de título en color, subtítulo, ficha
    enmarcada y barra decorativa. Antes esto era una tabla clave-valor y
    parecía un formulario, no la primera página de un documento.
    """
    main = colors.HexColor(theme.palette[ColorType.MAIN])
    light = colors.HexColor(theme.palette[ColorType.LIGHT])
    white = colors.HexColor(theme.palette[ColorType.WHITE])
    black = colors.HexColor(theme.palette[ColorType.BLACK])

    elements: list = [Spacer(1, 0.9 * inch)]

    # El logo manda en la portada, encima del título. Si faltara el fichero se
    # imprime igual, sin él: un informe sin logotipo es feo, uno que revienta
    # al generarse es un fallo.
    if _LOGO_PATH.exists():
        logo = Image(str(_LOGO_PATH), width=1.15 * inch, height=1.23 * inch)
        logo.hAlign = "CENTER"
        elements.append(logo)
        elements.append(Spacer(1, 0.45 * inch))
    else:
        elements.append(Spacer(1, 1.0 * inch))

    title_style = ParagraphStyle(
        "CoverTitle", parent=theme.styles["Heading1"],
        fontSize=28, leading=32, textColor=white,
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    title_band = Table([[Paragraph("Inventario de activos", title_style)]], colWidths=[6 * inch])
    title_band.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), main),
        ("TOPPADDING",    (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING",   (0, 0), (-1, -1), 24),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 24),
    ]))
    elements.append(title_band)

    subtitle_style = ParagraphStyle(
        "CoverSubtitle", parent=theme.styles["Normal"],
        fontSize=13, leading=16, textColor=black, alignment=TA_CENTER,
    )
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(scope_label, subtitle_style))

    elements.append(Spacer(1, 0.9 * inch))
    info_table = Table(
        [["Generado por:", author], ["Fecha:", _format_datetime(generated_at)]],
        colWidths=[1.8 * inch, 3.2 * inch],
    )
    info_table.setStyle(TableStyle([
        ("TEXTCOLOR",     (0, 0), (0, -1), main),
        ("TEXTCOLOR",     (1, 0), (1, -1), black),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BOX",           (0, 0), (-1, -1), 1, light),
    ]))
    elements.append(info_table)

    elements.append(Spacer(1, 0.5 * inch))
    elements.append(_status_strip(theme, assets))

    elements.append(Spacer(1, 0.6 * inch))
    decoration = Table([[""]], colWidths=[6 * inch], rowHeights=[0.12 * inch])
    decoration.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), light)]))
    elements.append(decoration)

    elements.append(PageBreak())
    return elements


def _status_strip(theme: ReportTheme, assets: Sequence) -> Table:
    """Cifras de un vistazo: el total y el desglose por estado.

    Es la respuesta a "¿qué hay aquí dentro?" sin pasar de página, y lo que
    convierte la portada en algo que se mira en vez de leerse. Los estados sin
    ningún activo no se pintan: una columna a cero no informa, estorba.
    """
    main = colors.HexColor(theme.palette[ColorType.MAIN])
    light = colors.HexColor(theme.palette[ColorType.LIGHT])
    white = colors.HexColor(theme.palette[ColorType.WHITE])

    counts: Dict[str, int] = {}
    for asset in assets:
        counts[asset.status] = counts.get(asset.status, 0) + 1

    columns = [("Activos", len(assets))]
    columns.extend(
        (_STATUS_LABELS[status], counts[status])
        for status in _STATUS_ORDER
        if counts.get(status)
    )

    number_style = ParagraphStyle(
        "StatNumber", parent=theme.styles["Normal"],
        fontSize=20, leading=23, alignment=TA_CENTER,
        fontName="Helvetica-Bold", textColor=white,
    )
    label_style = ParagraphStyle(
        "StatLabel", parent=theme.styles["Normal"],
        fontSize=7.5, leading=10, alignment=TA_CENTER, textColor=white,
    )

    cells = [
        [Paragraph(str(value), number_style), Paragraph(label.upper(), label_style)]
        for label, value in columns
    ]
    inner = [
        Table([[cell[0]], [cell[1]]], colWidths=[6 * inch / len(columns)])
        for cell in cells
    ]

    strip = Table([inner], colWidths=[6 * inch / len(columns)] * len(columns))
    strip.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), main),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEAFTER",     (0, 0), (-2, -1), 0.6, light),
    ]))
    return strip


def _asset_register(theme: ReportTheme, assets: Sequence, owner_names: Dict[int, str]) -> list:
    """El registro: una fila por activo.

    ``owner_names`` vacío significa ámbito propio, y entonces la columna de
    dueño no se pinta: en un informe de los activos de uno mismo, repetir el
    propio nombre en cada fila es ruido.
    """
    show_owner = bool(owner_names)

    header = ["Hostname", "SO", "Kernel", "Estado", "Última señal", "Etiquetas"]
    widths = [1.35 * inch, 0.6 * inch, 0.95 * inch, 0.75 * inch, 1.0 * inch, 1.35 * inch]
    if show_owner:
        header.insert(1, "Dueño")
        widths = [1.15 * inch, 0.8 * inch, 0.5 * inch, 0.8 * inch, 0.7 * inch,
                  0.95 * inch, 1.1 * inch]

    rows = [[_cell(text, theme.label) for text in header]]
    for asset in assets:
        values = [
            asset.hostname,
            asset.os or "—",
            asset.kernel or "—",
            _status_label(asset),
            _format_datetime(asset.last_seen_at),
            ", ".join(tag.name for tag in asset.tags) or "—",
        ]
        if show_owner:
            values.insert(1, owner_names.get(asset.user_id, f"#{asset.user_id}"))
        rows.append([_cell(value, theme.body) for value in values])

    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(_data_table_style(theme))

    # Sin `PageBreak` aquí: la portada ya termina con uno.
    elements: list = list(theme.section_header("Registro de activos", "INVENTARIO"))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(table)
    return elements


def _software_appendix(theme: ReportTheme, assets: Sequence) -> list:
    """Anexo con el software instalado, una tabla por activo.

    Va al final y en su propia sección a propósito: así el registro se lee
    igual de bien con la opción activada que sin ella. Puede ser largo — el
    agente manda hasta ``features.hygeia.limits.maxInventoryItems`` entradas
    por activo — y por eso no se activa por defecto.
    """
    elements: list = [PageBreak()]
    elements.extend(theme.section_header("Software instalado", "ANEXO"))
    elements.append(Spacer(1, 0.15 * inch))

    with_inventory = [asset for asset in assets if asset.inventory]
    if not with_inventory:
        elements.append(Paragraph(
            "Ningún activo ha reportado todavía su inventario de software.",
            theme.body,
        ))
        return elements

    widths = [2.6 * inch, 1.6 * inch, 1.1 * inch, 0.7 * inch]

    # El nombre del activo va DENTRO de la tabla, como fila que abarca las
    # cuatro columnas, y no como párrafo suelto encima.
    #
    # Es la única forma de que no quede huérfano: tanto `KeepTogether` como
    # `keepWithNext` obligan al bloque título+tabla a caber entero en una
    # página, y una tabla de cientos de aplicaciones no cabe nunca — así que
    # ReportLab la empujaba a la siguiente y dejaba el encabezado solo, con
    # la página medio en blanco. Como fila de la propia tabla, hay un único
    # flowable, que se parte por donde haga falta.
    #
    # `repeatRows=2` remata la jugada: al continuar en la página siguiente se
    # repiten el nombre del activo y la cabecera de columnas, así que nunca hay
    # una página de aplicaciones sin saber de quién son.
    title_style = ParagraphStyle(
        "SoftwareAssetTitle", parent=theme.styles["Normal"],
        fontSize=10.5, leading=13, fontName="Helvetica-Bold",
        textColor=colors.HexColor(theme.palette[ColorType.WHITE]),
    )

    for asset in with_inventory:
        count = len(asset.inventory)
        caption = f"{asset.hostname} — {count} {'aplicación' if count == 1 else 'aplicaciones'}"

        rows = [
            [Paragraph(caption, title_style), "", "", ""],
            [_cell(text, theme.label) for text in ("Nombre", "Fabricante", "Versión", "Arq.")],
        ]
        for entry in asset.inventory:
            rows.append([
                _cell(entry.get("name") or "—", theme.body),
                _cell(entry.get("vendor") or "—", theme.body),
                _cell(entry.get("version") or "—", theme.body),
                _cell(entry.get("architecture") or "—", theme.body),
            ])

        table = Table(rows, colWidths=widths, repeatRows=2)
        table.setStyle(_data_table_style(theme, header_rows=2))
        elements.append(table)
        elements.append(Spacer(1, 0.3 * inch))

    return elements


def build_inventory_report(
    *,
    assets: Sequence,
    scope_label: str,
    author: str,
    include_software: bool = False,
    owner_names: Optional[Dict[int, str]] = None,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """
    Dibuja el informe de inventario y devuelve los bytes del PDF.

    Args:
        assets: Activos a incluir, ya cargados y en el orden en que deben salir.
        scope_label: Texto del ámbito para la portada ("Mis activos", el nombre
            de la organización...).
        author: Quién pide el informe, tal como debe figurar en la portada.
        include_software: Añade el anexo con el software instalado.
        owner_names: ``{user_id: nombre}`` para el ámbito de organización.
            Vacío o ``None`` en ámbito propio, y entonces no se pinta la
            columna de dueño.
        generated_at: Instante que figura en la portada. Se inyecta para que
            los tests puedan fijarlo.

    Returns:
        El PDF completo, en memoria.
    """
    generated_at = generated_at or datetime.now()
    theme = ReportTheme(getSampleStyleSheet(), _palette())

    elements = _cover(theme, assets, scope_label, author, generated_at)
    if assets:
        elements.extend(_asset_register(theme, assets, owner_names or {}))
        if include_software:
            elements.extend(_software_appendix(theme, assets))
    else:
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("No hay ningún activo que inventariar.", theme.body))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Inventario de activos — {scope_label}",
        author=author,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    )
    document.build(
        elements,
        onFirstPage=lambda canvas, doc: _draw_page_furniture(
            canvas, doc, theme, "Ellysia · Inventario de activos",
        ),
        onLaterPages=lambda canvas, doc: _draw_page_furniture(
            canvas, doc, theme, "Ellysia · Inventario de activos",
        ),
    )

    buffer.seek(0)
    return buffer.read()


def _draw_page_furniture(canvas, document, theme: ReportTheme, header_title: str) -> None:
    """Barra de acento, cabecera y número de página.

    Mismo aparejo que los informes de Themis (``creator.py::_on_page``), para
    que los dos documentos se reconozcan como del mismo producto.

    La portada se queda limpia: una cabecera y un pie en la página 1 son
    justamente lo que hace que una portada no parezca una portada.

    Args:
        header_title: Texto de la cabecera de las páginas interiores; distingue
            un informe de inventario de uno de estadísticas.
    """
    if canvas.getPageNumber() == 1:
        return

    width, height = document.pagesize
    main = colors.HexColor(theme.palette[ColorType.MAIN])
    dark = colors.HexColor(theme.palette[ColorType.DARK])

    canvas.saveState()

    canvas.setFillColor(main)
    canvas.rect(20, 20, 6, height - 40, stroke=0, fill=1)

    canvas.setFont("Helvetica-Bold", 12)
    canvas.setFillColor(dark)
    canvas.drawString(40, height - 30, header_title)

    canvas.setStrokeColor(colors.HexColor("#e0e0e0"))
    canvas.setLineWidth(0.5)
    canvas.line(36, height - 42, width - 36, height - 42)

    # Logo pequeño en la esquina, como en los informes de Themis. Dibujarlo en
    # todas las páginas no multiplica el peso: ReportLab cachea la imagen por
    # ruta, así que las N páginas interiores comparten un único objeto embebido
    # (medido: un PDF de 11 páginas lleva 2 imágenes, esta y la de la portada).
    if _LOGO_PATH.exists():
        canvas.drawImage(
            str(_LOGO_PATH), width - 52, height - 38,
            width=0.3 * inch, height=0.32 * inch, preserveAspectRatio=True,
        )

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#999999"))
    canvas.drawRightString(width - 40, 28, f"Página {canvas.getPageNumber()}")

    canvas.restoreState()


# =============================================================================
# INFORME DE ESTADÍSTICAS
# =============================================================================

#: Título de cada juego de datos, tal como lo lee la portada. Mismas claves que
#: ``CSV_RENDERERS`` (``services/export.py``): son los dos formatos del mismo
#: catálogo de consultas.
_STATS_TITLES = {
    "summary": "Resumen de un activo",
    "tag-stats": "Estadísticas de una etiqueta",
    "ranking": "Ranking del parque",
    "overview": "Panorama del parque",
}


def _format_number(value: Any) -> str:
    """Un valor numérico legible, o una raya si no hay dato.

    Los enteros (recuentos, muestras) salen sin decimales; el resto, con dos.
    Un ``bool`` se lee "Sí"/"No", que es lo que significa en este informe
    (``isPeriodClipped``).
    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}" if value % 1 else str(int(value))
    return str(value)


def _format_iso_instant(value: Optional[str]) -> str:
    """Un instante ISO 8601 (tal como lo deja el schema al serializar) en formato local.

    ``payload`` ya viene serializado por el mismo schema Marshmallow del
    endpoint JSON, así que las fechas llegan como texto, no como ``datetime``.
    Un valor que no se pueda parsear se imprime tal cual: es preferible a
    perder el dato.
    """
    if not value:
        return "—"
    try:
        return _format_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return str(value)


def _stats_window_caption(payload: Mapping[str, Any]) -> str:
    """Frase con la ventana cubierta, o cadena vacía si el juego de datos no tiene una."""
    covered_from, covered_to = payload.get("periodCoveredFrom"), payload.get("periodCoveredTo")
    if not covered_from and not covered_to:
        return ""
    clipped = " (recortada al histórico disponible)" if payload.get("isPeriodClipped") else ""
    return f"Del {_format_iso_instant(covered_from)} al {_format_iso_instant(covered_to)}{clipped}"


def _summary_table(theme: ReportTheme, payload: Mapping[str, Any]) -> Optional[Table]:
    """Una fila por métrica del resumen de un activo. ``None`` si no hay ninguna.

    Lleva ``timestampOfMax``, igual que la tabla en pantalla, que lo enseña
    como segunda línea bajo el máximo: cuándo ocurrió el pico es parte de la
    lectura, no un dato de repuesto que solo vive en el CSV.
    """
    metrics: Dict[str, Any] = payload.get("metrics") or {}
    if not metrics:
        return None
    header = ["Métrica", "Mín", "Media", "P95", "Máx", "Máx. el", "Actual", "Muestras"]
    rows = [[_cell(text, theme.label) for text in header]]
    for name, aggregate in sorted(metrics.items()):
        rows.append([_cell(value, theme.body) for value in (
            name,
            _format_number(aggregate.get("min")), _format_number(aggregate.get("avg")),
            _format_number(aggregate.get("p95")), _format_number(aggregate.get("max")),
            _format_iso_instant(aggregate.get("timestampOfMax")),
            _format_number(aggregate.get("current")), _format_number(aggregate.get("sampleCount")),
        )])
    table = Table(
        rows, colWidths=[1.15 * inch] + [0.62 * inch] * 4 + [0.95 * inch, 0.62 * inch, 0.65 * inch],
        repeatRows=1,
    )
    table.setStyle(_data_table_style(theme))
    return table


def _tag_stats_table(theme: ReportTheme, payload: Mapping[str, Any]) -> Optional[Table]:
    """Una fila por métrica de una etiqueta: valor combinado y activos que aportaron datos."""
    metrics: Dict[str, Any] = payload.get("metrics") or {}
    if not metrics:
        return None
    header = ["Métrica", "Unidad", "Valor", "Activos con datos"]
    rows = [[_cell(text, theme.label) for text in header]]
    for name, aggregate in sorted(metrics.items()):
        rows.append([_cell(value, theme.body) for value in (
            name, aggregate.get("unit") or "—",
            _format_number(aggregate.get("value")), _format_number(aggregate.get("assetsWithData")),
        )])
    table = Table(rows, colWidths=[2.2 * inch, 1.2 * inch, 1.2 * inch, 1.6 * inch], repeatRows=1)
    table.setStyle(_data_table_style(theme))
    return table


def _ranking_table(theme: ReportTheme, payload: Mapping[str, Any]) -> Optional[Table]:
    """Una fila por activo del ranking, en el orden que decidió el servidor."""
    assets = payload.get("assets") or []
    if not assets:
        return None
    header = ["#", "Activo", "Valor", "Muestras"]
    rows = [[_cell(text, theme.label) for text in header]]
    for position, entry in enumerate(assets, start=1):
        rows.append([_cell(value, theme.body) for value in (
            str(position), entry.get("hostname") or f"#{entry.get('assetId')}",
            _format_number(entry.get("value")), _format_number(entry.get("sampleCount")),
        )])
    table = Table(rows, colWidths=[0.5 * inch, 2.9 * inch, 1.3 * inch, 1.5 * inch], repeatRows=1)
    table.setStyle(_data_table_style(theme))
    return table


def _overview_table(theme: ReportTheme, payload: Mapping[str, Any]) -> Optional[Table]:
    """El panorama del parque como tabla de dos columnas: medida y valor.

    Nunca es ``None``: a diferencia de los otros tres juegos de datos, el
    panorama siempre tiene una fila (``assetCount``), aunque el parque esté
    vacío — es una foto del estado actual, no una serie que pueda quedar sin
    puntos.
    """
    rows = [[_cell(text, theme.label) for text in ("Medida", "Valor")]]
    rows.append([_cell(value, theme.body) for value in (
        "Activos", _format_number(payload.get("assetCount")),
    )])
    for group, title in (
        ("assetsByStatus", "Activos por estado"), ("openAnomaliesBySeverity", "Anomalías abiertas"),
    ):
        for key, count in sorted((payload.get(group) or {}).items()):
            rows.append([_cell(value, theme.body) for value in (f"{title} · {key}", str(count))])
    rows.append([_cell(value, theme.body) for value in (
        "Anomalías reconocidas", _format_number(payload.get("acknowledgedAnomalyCount")),
    )])
    rows.append([_cell(value, theme.body) for value in (
        "Disponibilidad media (s)", _format_number(payload.get("averageUptimeSec")),
    )])
    rows.append([_cell(value, theme.body) for value in (
        "Última actividad", _format_iso_instant(payload.get("lastActivityAt")),
    )])
    table = Table(rows, colWidths=[3.0 * inch, 3.0 * inch], repeatRows=1)
    table.setStyle(_data_table_style(theme))
    return table


#: Qué función dibuja la tabla de cada juego de datos. Añadir un dataset
#: exportable a PDF es añadir una entrada aquí, igual que en
#: ``services/export.py::CSV_RENDERERS``.
_STATS_TABLE_BUILDERS = {
    "summary": _summary_table,
    "tag-stats": _tag_stats_table,
    "ranking": _ranking_table,
    "overview": _overview_table,
}


class _StatsCoverInfo(NamedTuple):
    """Lo que necesita la portada del informe de estadísticas, agrupado.

    Attributes:
        title: Título de la portada, ya resuelto (``_STATS_TITLES``).
        scope_label: Nombre del activo o de la etiqueta; ``None`` en
            ``ranking``/``overview``, que no tienen uno.
        period_caption: Frase con la ventana cubierta, o cadena vacía.
        author: Quién pide el informe.
        generated_at: Instante que figura en la portada.
    """
    title: str
    scope_label: Optional[str]
    period_caption: str
    author: str
    generated_at: datetime


def _stats_cover(theme: ReportTheme, cover_info: _StatsCoverInfo) -> list:
    """Portada del informe de estadísticas.

    Mismo molde que la del inventario (``_cover``), sin la ficha de recuento
    por estado: no hay activos que contar, hay una tabla que presentar.
    """
    title, scope_label, period_caption, author, generated_at = cover_info
    main = colors.HexColor(theme.palette[ColorType.MAIN])
    light = colors.HexColor(theme.palette[ColorType.LIGHT])
    white = colors.HexColor(theme.palette[ColorType.WHITE])
    black = colors.HexColor(theme.palette[ColorType.BLACK])

    elements: list = [Spacer(1, 0.9 * inch)]

    if _LOGO_PATH.exists():
        logo = Image(str(_LOGO_PATH), width=1.15 * inch, height=1.23 * inch)
        logo.hAlign = "CENTER"
        elements.append(logo)
        elements.append(Spacer(1, 0.45 * inch))
    else:
        elements.append(Spacer(1, 1.0 * inch))

    title_style = ParagraphStyle(
        "StatsCoverTitle", parent=theme.styles["Heading1"],
        fontSize=28, leading=32, textColor=white,
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    title_band = Table([[Paragraph(title, title_style)]], colWidths=[6 * inch])
    title_band.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), main),
        ("TOPPADDING",    (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING",   (0, 0), (-1, -1), 24),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 24),
    ]))
    elements.append(title_band)

    subtitle_style = ParagraphStyle(
        "StatsCoverSubtitle", parent=theme.styles["Normal"],
        fontSize=13, leading=16, textColor=black, alignment=TA_CENTER,
    )
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(scope_label or "—", subtitle_style))
    if period_caption:
        elements.append(Spacer(1, 0.05 * inch))
        elements.append(Paragraph(period_caption, ParagraphStyle(
            "StatsCoverPeriod", parent=subtitle_style, fontSize=10, textColor=main,
        )))

    elements.append(Spacer(1, 0.9 * inch))
    info_table = Table(
        [["Generado por:", author], ["Fecha:", _format_datetime(generated_at)]],
        colWidths=[1.8 * inch, 3.2 * inch],
    )
    info_table.setStyle(TableStyle([
        ("TEXTCOLOR",     (0, 0), (0, -1), main),
        ("TEXTCOLOR",     (1, 0), (1, -1), black),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BOX",           (0, 0), (-1, -1), 1, light),
    ]))
    elements.append(info_table)

    elements.append(Spacer(1, 0.6 * inch))
    decoration = Table([[""]], colWidths=[6 * inch], rowHeights=[0.12 * inch])
    decoration.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), light)]))
    elements.append(decoration)

    elements.append(PageBreak())
    return elements


def build_stats_report(
    *,
    dataset: str,
    payload: Mapping[str, Any],
    scope_label: Optional[str],
    author: str,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """
    Dibuja el informe de estadísticas y devuelve los bytes del PDF.

    ``payload`` es el mismo diccionario ya serializado por el schema
    Marshmallow del endpoint JSON (el que también consume
    ``services/export.py::build_csv``), así que el PDF no puede decir un
    número distinto del que exporta el CSV o del que se ve en el panel: los
    tres leen la misma respuesta, no recalculan nada por su cuenta. El
    periodo pedido no hace falta como argumento aparte: ya viaja dentro de
    ``payload`` como ``periodCoveredFrom``/``periodCoveredTo``, que es lo que
    pinta la portada.

    Args:
        dataset: Juego de datos (``summary``, ``tag-stats``, ``ranking`` u
            ``overview``); decide el título de la portada y la forma de la
            tabla.
        payload: Respuesta ya serializada del juego de datos.
        scope_label: Texto del ámbito para la portada (el hostname, el nombre
            de la etiqueta, o ``None`` en ``ranking``/``overview``, que no
            tienen uno).
        author: Quién pide el informe, tal como debe figurar en la portada.
        generated_at: Instante que figura en la portada. Se inyecta para que
            los tests puedan fijarlo.

    Returns:
        El PDF completo, en memoria.
    """
    generated_at = generated_at or datetime.now()
    theme = ReportTheme(getSampleStyleSheet(), _palette())
    title = _STATS_TITLES.get(dataset, "Estadísticas")

    elements = _stats_cover(theme, _StatsCoverInfo(
        title, scope_label, _stats_window_caption(payload), author, generated_at,
    ))

    table = _STATS_TABLE_BUILDERS[dataset](theme, payload)
    if table is not None:
        elements.extend(theme.section_header(title, "DATOS"))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(table)
    else:
        elements.append(Paragraph(
            "No hay datos para el alcance y el periodo elegidos.", theme.body,
        ))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Estadísticas Hygeia — {title}",
        author=author,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    )
    document.build(
        elements,
        onFirstPage=lambda canvas, doc: _draw_page_furniture(
            canvas, doc, theme, "Ellysia · Estadísticas",
        ),
        onLaterPages=lambda canvas, doc: _draw_page_furniture(
            canvas, doc, theme, "Ellysia · Estadísticas",
        ),
    )

    buffer.seek(0)
    return buffer.read()
