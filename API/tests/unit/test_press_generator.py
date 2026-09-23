"""Tests de ``tools.press``: la composición común de los informes PDF.

Lo que se protege aquí es el contrato de la clase abstracta —qué ganchos se
llaman, en qué orden y qué pasa cuando un módulo no redefine ninguno—, más las
dos cosas que antes estaban mal en algún módulo y ahora están en un solo sitio:
que la portada no lleva cabecera y que escribir a disco es atómico.
"""

from __future__ import annotations

import os

import pytest

from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table

from src.modules.tools.press import (
    ColorType, DocumentStyle, PdfGenerator, build_palette,
)

pytestmark = pytest.mark.unit


_FALLBACK = {
    "black": "#000000", "dark": "#111111", "main": "#222222",
    "secondary": "#333333", "light": "#444444", "white": "#ffffff",
}


class _MinimalGenerator(PdfGenerator):
    """El generador más pequeño que se puede escribir: título y cuerpo."""

    def __init__(self, **style_overrides) -> None:
        super().__init__(DocumentStyle(
            palette=build_palette({}, _FALLBACK),
            header_title="Ellysia · Prueba",
            **style_overrides,
        ))

    def cover_title(self) -> str:
        return "Informe de prueba"

    def append_body(self, elements: list, theme) -> None:
        elements.append(Paragraph("Cuerpo del informe.", theme.body))


class _FakeCanvas:
    """Lienzo de mentira que apunta lo que le mandan dibujar."""

    def __init__(self, page_number: int) -> None:
        self._page_number = page_number
        self.strings: list[str] = []
        self.rectangles: list[tuple] = []
        self.images: list[str] = []

    def getPageNumber(self) -> int:
        return self._page_number

    def drawString(self, x, y, text):
        self.strings.append(text)

    def drawRightString(self, x, y, text):
        self.strings.append(text)

    def drawImage(self, path, *args, **kwargs):
        self.images.append(path)

    def rect(self, *args, **kwargs):
        self.rectangles.append(args)

    def saveState(self):
        pass

    def restoreState(self):
        pass

    def setFillColor(self, *args):
        pass

    def setStrokeColor(self, *args):
        pass

    def setLineWidth(self, *args):
        pass

    def setFont(self, *args):
        pass

    def line(self, *args):
        pass


class _FakeDocument:
    """Lo único que ``draw_page_furniture`` mira de un documento."""

    pagesize = (595.27, 841.89)


# =============================================================================
# LA PALETA
# =============================================================================

def test_la_paleta_cae_al_respaldo_del_modulo_sin_configuracion():
    palette = build_palette({}, _FALLBACK)

    assert palette[ColorType.MAIN] == "#222222"
    assert set(palette) == set(ColorType)


def test_la_configuracion_manda_sobre_el_respaldo_color_a_color():
    palette = build_palette({"main": "#abcdef"}, _FALLBACK)

    assert palette[ColorType.MAIN] == "#abcdef"
    # Los otros cinco no se tocan: la configuración sobrescribe lo que trae,
    # no reemplaza la paleta entera.
    assert palette[ColorType.DARK] == "#111111"


def test_una_paleta_sin_configuracion_ninguna_no_revienta():
    assert build_palette(None, _FALLBACK)[ColorType.WHITE] == "#ffffff"


# =============================================================================
# EL DOCUMENTO COMPLETO
# =============================================================================

def test_el_generador_minimo_produce_un_pdf():
    pdf = _MinimalGenerator().generate()

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_generate_to_file_deja_el_pdf_en_su_sitio(tmp_path):
    destination = str(tmp_path / "sub" / "informe.pdf")

    returned = _MinimalGenerator().generate_to_file(destination)

    assert returned == destination
    assert os.path.exists(destination)
    with open(destination, "rb") as handle:
        assert handle.read(4) == b"%PDF"


def test_generate_to_file_no_deja_temporales_si_el_cuerpo_falla(tmp_path):
    class _Explosivo(_MinimalGenerator):
        def append_body(self, elements, theme):
            raise RuntimeError("el cuerpo no se pudo dibujar")

    destination = str(tmp_path / "informe.pdf")

    with pytest.raises(RuntimeError):
        _Explosivo().generate_to_file(destination)

    # Ni el fichero final a medio escribir ni el temporal huérfano: su nombre
    # lleva un UUID, así que no lo limpiaría nadie.
    assert list(tmp_path.iterdir()) == []


def test_regenerar_sobre_el_mismo_fichero_lo_reemplaza_entero(tmp_path):
    destination = str(tmp_path / "informe.pdf")

    _MinimalGenerator().generate_to_file(destination)
    _MinimalGenerator().generate_to_file(destination)

    assert os.listdir(tmp_path) == ["informe.pdf"]


# =============================================================================
# LA PORTADA
# =============================================================================

def _cover_of(generator: PdfGenerator) -> list:
    elements: list = []
    generator.append_cover(elements, generator.theme)
    return elements


def test_la_portada_termina_en_salto_de_pagina():
    assert isinstance(_cover_of(_MinimalGenerator())[-1], PageBreak)


def test_la_portada_por_defecto_lleva_la_fecha_y_nada_mas():
    generator = _MinimalGenerator()

    assert generator.cover_fields() == [
        ["Fecha:", generator.generated_at().strftime("%d/%m/%Y")]
    ]


def test_el_subtitulo_solo_aparece_si_el_modulo_lo_da():
    class _ConSubtitulo(_MinimalGenerator):
        def cover_subtitle(self):
            return "Mis activos"

    sin_subtitulo = _cover_of(_MinimalGenerator())
    con_subtitulo = _cover_of(_ConSubtitulo())

    assert len(con_subtitulo) == len(sin_subtitulo) + 2  # Spacer + Paragraph


def test_el_bloque_libre_de_la_portada_se_intercala_donde_toca():
    marca = Spacer(1, 1 * inch)

    class _ConBloque(_MinimalGenerator):
        def cover_extra(self):
            return [marca]

    elements = _cover_of(_ConBloque())
    posicion = elements.index(marca)

    # Entre la ficha (una Table) y la barra decorativa, que es el penúltimo
    # elemento antes del salto de página.
    assert isinstance(elements[posicion - 2], Table)
    assert isinstance(elements[-2], Table)
    assert isinstance(elements[-1], PageBreak)


def test_un_logotipo_que_no_existe_no_tumba_la_portada(tmp_path):
    generator = _MinimalGenerator(logo_path=str(tmp_path / "no-existe.png"))

    assert isinstance(_cover_of(generator)[-1], PageBreak)
    assert generator.generate().startswith(b"%PDF")


# =============================================================================
# LA NOTA LEGAL
# =============================================================================

def test_sin_nota_legal_no_se_imprime_nada():
    generator = _MinimalGenerator()
    elements: list = []

    generator.append_legal_notice(elements, generator.theme)

    assert elements == []


def test_la_nota_legal_va_en_su_propia_pagina_y_enmarcada():
    class _ConNota(_MinimalGenerator):
        def legal_notice(self):
            return ("AVISO", "El texto de la nota.")

    generator = _ConNota()
    elements: list = []
    generator.append_legal_notice(elements, generator.theme)

    assert isinstance(elements[0], PageBreak)
    assert isinstance(elements[1], Paragraph)
    assert isinstance(elements[2], Table)


# =============================================================================
# EL APAREJO DE PÁGINA
# =============================================================================

def test_la_portada_no_lleva_cabecera_ni_numero_de_pagina():
    canvas = _FakeCanvas(page_number=1)

    _MinimalGenerator().draw_page_furniture(canvas, _FakeDocument())

    # Una cabecera y un pie en la página 1 son justamente lo que hace que una
    # portada no parezca una portada.
    assert canvas.strings == []
    assert canvas.rectangles == []


def test_las_paginas_interiores_llevan_rotulo_y_numero():
    canvas = _FakeCanvas(page_number=3)

    _MinimalGenerator().draw_page_furniture(canvas, _FakeDocument())

    assert "Ellysia · Prueba" in canvas.strings
    assert "Página 3" in canvas.strings
    assert canvas.rectangles  # la barra de acento del margen


def test_sin_logotipo_no_se_dibuja_ninguna_imagen():
    canvas = _FakeCanvas(page_number=2)

    _MinimalGenerator().draw_page_furniture(canvas, _FakeDocument())

    assert canvas.images == []


# =============================================================================
# EL CONTRATO DE LA CLASE ABSTRACTA
# =============================================================================

def test_un_generador_sin_cuerpo_no_se_puede_instanciar():
    class _SinCuerpo(PdfGenerator):
        def cover_title(self):
            return "x"

    with pytest.raises(TypeError):
        _SinCuerpo(DocumentStyle(palette=build_palette({}, _FALLBACK), header_title="x"))


def test_un_generador_sin_titulo_de_portada_no_se_puede_instanciar():
    class _SinTitulo(PdfGenerator):
        def append_body(self, elements, theme):
            pass

    with pytest.raises(TypeError):
        _SinTitulo(DocumentStyle(palette=build_palette({}, _FALLBACK), header_title="x"))
