"""
src.modules.tools.press — Composición de documentos PDF.

Módulo transversal que reúne lo que todos los informes de Ellysia tienen en
común: el tema visual (paleta y estilos), el saneado del texto ajeno y —cuando
llegue la fase siguiente— la clase abstracta que compone el documento. Cada
módulo de funcionalidad aporta solo lo suyo: su paleta, su portada y su cuerpo.

La tríada de ``tools/`` se lee sola: **scribe** escribe (generación con IA),
**press** imprime y **herald** reparte (envío de correo).

``press`` no sabe nada de escaneos, activos ni correos, y no puede saberlo: las
reglas de capas del repositorio (``CONVENCIONES.md`` § 3.4) prohíben que
``tools/`` importe ``features/``. Los generadores concretos viven en su propio
módulo de funcionalidad.

Uso típico:
    >>> from src.modules.tools.press import ReportTheme, build_palette
    >>> palette = build_palette(CR.get_hygeia_color_palette(), _FALLBACK_PALETTE)
    >>> theme = ReportTheme(getSampleStyleSheet(), palette)
"""

from .markup import safe_markup
from .theme import ColorType, ReportTheme, build_palette

__all__ = [
    "ColorType",
    "ReportTheme",
    "build_palette",
    "safe_markup",
]
