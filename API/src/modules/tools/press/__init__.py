"""
src.modules.tools.press — Composición de documentos PDF.

Módulo transversal que reúne lo que todos los informes de Ellysia tienen en
común: el tema visual (paleta y estilos), el saneado del texto ajeno y la clase
abstracta que compone el documento. Cada módulo de funcionalidad aporta solo lo
suyo: su paleta, su portada y su cuerpo.

La tríada de ``tools/`` se lee sola: **scribe** escribe (generación con IA),
**press** imprime y **herald** reparte (envío de correo).

``press`` no sabe nada de escaneos, activos ni correos, y no puede saberlo: las
reglas de capas del repositorio (``CONVENCIONES.md`` § 3.4) prohíben que
``tools/`` importe ``features/``. Los generadores concretos viven en su propio
módulo de funcionalidad.

Uso típico:
    >>> from src.modules.tools.press import DocumentStyle, PdfGenerator, build_palette
    >>> class InventoryGenerator(PdfGenerator):
    ...     def __init__(self, assets):
    ...         super().__init__(DocumentStyle(
    ...             palette=build_palette(CR.get_hygeia_color_palette(), _FALLBACK_PALETTE),
    ...             header_title="Ellysia · Inventario de activos",
    ...         ))
    ...         self.assets = assets
    ...     def cover_title(self):
    ...         return "Inventario de activos"
    ...     def append_body(self, elements, theme):
    ...         ...
    >>> pdf = InventoryGenerator(assets).generate()
"""

from .generator import DocumentStyle, PdfGenerator
from .markup import safe_markup
from .theme import ColorType, ReportTheme, build_palette

__all__ = [
    "ColorType",
    "DocumentStyle",
    "PdfGenerator",
    "ReportTheme",
    "build_palette",
    "safe_markup",
]
