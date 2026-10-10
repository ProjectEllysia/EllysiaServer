"""
La exportación de un registro en CSV y en PDF.

El CSV es una tabla plana para abrir en una hoja de cálculo (BOM UTF-8, sin el que Excel en
Windows estropea los acentos); el PDF es una ficha por registro, con la identidad de Eunomia.
"""

import csv
import io
from datetime import datetime
from typing import Optional, Sequence

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, Spacer

import src.modules.system.config_reading as CR
from src.modules.tools.press import ColorType, DocumentStyle, PdfGenerator, ReportTheme, build_palette, safe_markup

from ..registers import FIELD_SELECT, RegisterType
from .pdf import EUNOMIA_LOGO_PATH

_FALLBACK_PALETTE = {
    "black": "#121212", "dark": "#2b3a55", "light": "#7088b8",
    "main": "#3f5a8c", "secondary": "#555b6e", "white": "#f5f5f5",
}


def display_value(register: RegisterType, key: str, value: str) -> str:
    """El valor de un campo tal como se lee: la etiqueta de la opción en un ``select``."""
    field = register.field(key)
    if field is not None and field.type == FIELD_SELECT:
        return dict(field.options).get(value, value)
    return value


def build_csv(register: RegisterType, records: Sequence[dict]) -> bytes:
    """Compone el CSV de un registro: una fila por ficha, una columna por campo.

    Args:
        register: La definición.
        records: Fichas tal como las da el manager (``values`` y ``isArchived``).

    Returns:
        bytes: El CSV en UTF-8 con BOM.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([field.label for field in register.fields])
    for record in records:
        writer.writerow([display_value(register, field.key, record["values"].get(field.key, ""))
                         for field in register.fields])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


class RegisterPDF(PdfGenerator):
    """Compone el PDF de un registro: una ficha por entrada.

    Attributes:
        register: La definición.
        records: Fichas a imprimir.
        company_name: Razón social, para la portada.
        moment: Instante de la portada.
    """

    def __init__(self, *, register: RegisterType, records: Sequence[dict], company_name: str = "",
                 company_details: Sequence[tuple[str, str]] = (), author: str = "Ellysia Security Team", generated_at: Optional[datetime] = None) -> None:
        """Prepara el generador.

        Args:
            register: La definición.
            records: Fichas a imprimir, ya filtradas.
            company_name: Razón social de la empresa. Por defecto vacía.
            company_details: ``(etiqueta, valor)`` de la ficha de la portada (NIF, domicilio,
                contacto); los vacíos no salen. Por defecto, ninguno.
            author: Autor de los metadatos.
            generated_at: Instante de la portada. Por defecto ahora.
        """
        super().__init__(DocumentStyle(
            palette=build_palette(CR.eunomia_config().color_palette, _FALLBACK_PALETTE),
            header_title=f"Ellysia · {register.title}", author=author, logo_path=str(EUNOMIA_LOGO_PATH),
            left_margin=0.7 * inch, right_margin=0.7 * inch, top_margin=0.8 * inch, bottom_margin=0.7 * inch,
        ))
        self.register = register
        self.records = records
        self.company_name = company_name
        self.company_details = company_details
        self.moment = generated_at or datetime.now()

    def cover_title(self) -> str:
        """El nombre del registro."""
        return self.register.title

    def cover_subtitle(self) -> Optional[str]:
        """La razón social, si se conoce."""
        return self.company_name or None

    def cover_fields(self) -> Sequence[Sequence[str]]:
        """Los datos de la empresa que se conocen, la fecha y el número de fichas."""
        company = [[label, value] for label, value in self.company_details if value]
        return company + [["Fecha:", self.moment.strftime("%d/%m/%Y")], ["Fichas:", str(len(self.records))]]

    def generated_at(self) -> datetime:
        """La fecha de la portada."""
        return self.moment

    def append_body(self, elements: list, theme: ReportTheme) -> None:
        """Una ficha por entrada: título y tabla de campo y valor (todo saneado)."""
        heading = ParagraphStyle("RegisterHeading", parent=theme.body, fontName="Helvetica-Bold", fontSize=12,
                                 leading=15, spaceBefore=14, spaceAfter=6, textColor=self.style.palette[ColorType.DARK])
        cell = theme.cell_left
        width = self.style.page_size[0] - self.style.left_margin - self.style.right_margin
        for number, record in enumerate(self.records, 1):
            title = record["values"].get(self.register.title_field, "") or f"Ficha {number}"
            rows = [[Paragraph(safe_markup(field.label), cell),
                     Paragraph(safe_markup(display_value(self.register, field.key, record["values"].get(field.key, "")) or "—"), cell)]
                    for field in self.register.fields]
            elements.append(KeepTogether([Paragraph(safe_markup(f"{number}. {title}"), heading),
                                          theme.kv_table(rows, [width * 0.32, width * 0.68])]))
            elements.append(Spacer(1, 6))
