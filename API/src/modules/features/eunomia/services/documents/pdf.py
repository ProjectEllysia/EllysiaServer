"""
El documento de una plantilla en PDF, compuesto con ``tools/press``.

Hereda de ``PdfGenerator``: la portada, la cabecera, el número de página y el pie ya los pone la
capa común. Aquí solo se dice qué lleva la portada de un documento de cumplimiento y cómo se
dibujan sus secciones.
"""

import base64
import binascii
import logging
import os
import tempfile
from dataclasses import replace
from datetime import datetime
from typing import Optional, Sequence, Tuple

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, Spacer

import src.modules.system.config_reading as CR
from src.modules.tools.press import (
    ColorType, DocumentStyle, PdfGenerator, ReportTheme, build_palette, safe_markup,
)

from .render import KIND_BULLETS, RenderedDocument

logger = logging.getLogger(__name__)

#: Colores de respaldo si ``features.eunomia.colorPalette`` no los define.
_FALLBACK_PALETTE = {
    "black": "#121212", "dark": "#2b3a55", "light": "#7088b8",
    "main": "#3f5a8c", "secondary": "#555b6e", "white": "#f5f5f5",
}

_LEGAL_TITLE = "Borrador para revisión"
_LEGAL_TEXT = (
    "Este documento es un borrador generado por Ellysia a partir de los datos de la empresa. "
    "La dirección debe revisarlo, adaptarlo a la realidad de la organización y aprobarlo antes de "
    "darlo por vigente. No constituye asesoramiento jurídico."
)

_LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg"}


def decode_logo(data_uri: Optional[str]) -> Optional[Tuple[bytes, str]]:
    """Decodifica el logotipo de la empresa, guardado como ``data:`` URI en base64.

    Args:
        data_uri: El contenido de ``CompanyProfile.brand_logo``; ``None`` o vacío si no hay.

    Returns:
        Optional[Tuple[bytes, str]]: ``(bytes, extensión)`` de un PNG o JPEG; ``None`` si no hay
            logotipo, no es de esos tipos o no se puede decodificar.
    """
    if not data_uri or not data_uri.startswith("data:"):
        return None
    header, _, payload = data_uri.partition(",")
    media_type = header[len("data:"):].split(";")[0].lower()
    extension = _LOGO_TYPES.get(media_type)
    if extension is None:
        return None
    try:
        return base64.b64decode(payload, validate=True), extension
    except (binascii.Error, ValueError):
        return None


class EunomiaTemplatePDF(PdfGenerator):
    """Compone el PDF de un documento de cumplimiento ya relleno.

    Attributes:
        document: Título y secciones, con los valores puestos.
        company_name: Razón social, para la portada.
        tax_id: NIF, para la portada; vacío si no se conoce.
        framework_label: Nombre corto del marco (``"NIS2"``).
        logo: Logotipo de la empresa como ``(bytes, extensión)``, o ``None``.
        moment: Instante que figura como fecha de generación.
    """

    def __init__(
        self,
        *,
        document: RenderedDocument,
        company_name: str,
        tax_id: str = "",
        framework_label: str = "",
        logo: Optional[Tuple[bytes, str]] = None,
        author: str = "Ellysia Security Team",
        generated_at: Optional[datetime] = None,
    ) -> None:
        """Prepara el generador.

        Args:
            document: El documento ya sin marcadores (``render_document``).
            company_name: Razón social que va en la portada.
            tax_id: NIF de la empresa. Por defecto vacío.
            framework_label: Nombre corto del marco de la plantilla. Por defecto vacío.
            logo: Logotipo de la empresa (``decode_logo``). Por defecto ``None``: sin logotipo.
            author: Autor de los metadatos del PDF.
            generated_at: Instante de la portada. Por defecto ahora; se inyecta en los tests.
        """
        super().__init__(DocumentStyle(
            palette=build_palette(CR.eunomia_config().color_palette, _FALLBACK_PALETTE),
            header_title=f"Ellysia · {company_name}" if company_name else "Ellysia · Eunomia",
            author=author,
            left_margin=0.8 * inch,
            right_margin=0.8 * inch,
            top_margin=0.8 * inch,
            bottom_margin=0.7 * inch,
        ))
        self.document = document
        self.company_name = company_name
        self.tax_id = tax_id
        self.framework_label = framework_label
        self.logo = logo
        self.moment = generated_at or datetime.now()

    def cover_title(self) -> str:
        """El título del documento."""
        return self.document.title

    def cover_subtitle(self) -> Optional[str]:
        """La razón social, o ``None`` si no se conoce."""
        return self.company_name or None

    def cover_fields(self) -> Sequence[Sequence[str]]:
        """La ficha de la portada: empresa, NIF, marco y fecha; solo lo que se conoce."""
        rows = [["Empresa:", self.company_name], ["NIF:", self.tax_id], ["Marco:", self.framework_label],
                ["Fecha:", self.generated_at().strftime("%d/%m/%Y")]]
        return [row for row in rows if row[1]]

    def legal_notice(self) -> Tuple[str, str]:
        """La nota que avisa de que es un borrador que la dirección debe aprobar."""
        return _LEGAL_TITLE, _LEGAL_TEXT

    def generated_at(self) -> datetime:
        """La fecha de la portada."""
        return self.moment

    def append_body(self, elements: list, theme: ReportTheme) -> None:
        """Dibuja las secciones: encabezado, párrafos y listas con viñetas.

        Todo valor pasa por ``safe_markup``: un ``<`` o un ``&`` escritos por el usuario no
        rompen el documento.

        Args:
            elements: Flowables del documento; se le añaden las secciones.
            theme: Estilos derivados de la paleta.
        """
        palette = self.style.palette
        heading = ParagraphStyle(
            "EunomiaHeading", parent=theme.body, fontName="Helvetica-Bold", fontSize=12, leading=15,
            alignment=TA_LEFT, spaceBefore=16, spaceAfter=6, textColor=palette[ColorType.DARK],
        )
        body = ParagraphStyle("EunomiaBody", parent=theme.body, fontSize=10, leading=14, spaceAfter=6)
        bullet = ParagraphStyle("EunomiaBullet", parent=body, leftIndent=16, bulletIndent=4, spaceAfter=3)

        for section in self.document.sections:
            block_elements = [Paragraph(safe_markup(section.heading), heading)]
            for block in section.blocks:
                if block.kind == KIND_BULLETS:
                    block_elements.extend(Paragraph(safe_markup(text), bullet, bulletText="•") for text in block.texts)
                    block_elements.append(Spacer(1, 4))
                else:
                    block_elements.extend(Paragraph(safe_markup(text), body) for text in block.texts)
            # El encabezado va siempre con su primer bloque: no se queda huérfano al final de página.
            elements.append(KeepTogether(block_elements[:2]))
            elements.extend(block_elements[2:])

    def generate(self) -> bytes:
        """Compone el PDF, con el logotipo de la empresa si lo hay.

        ``PdfGenerator`` lee el logotipo de un fichero, así que el de la empresa se vuelca a un
        temporal que se borra al terminar.

        Returns:
            bytes: El PDF.
        """
        if self.logo is None:
            return super().generate()
        content, extension = self.logo
        handle = tempfile.NamedTemporaryFile(suffix=extension, delete=False)
        try:
            handle.write(content)
            handle.close()
            self.style = replace(self.style, logo_path=handle.name)
            try:
                return super().generate()
            except Exception:  # noqa: BLE001 — un logotipo corrupto no debe impedir el documento
                logger.warning("El logotipo de la empresa no se pudo dibujar; se genera sin él", exc_info=True)
                self.style = replace(self.style, logo_path=None)
                return super().generate()
        finally:
            self.style = replace(self.style, logo_path=None)
            try:
                os.remove(handle.name)
            except OSError:
                logger.warning("No se pudo borrar el logotipo temporal %s", handle.name)
