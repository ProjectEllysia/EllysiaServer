"""
Saneado del texto ajeno que acaba impreso en un PDF.

``Paragraph`` de ReportLab interpreta un mini-HTML, así que ningún texto que no
hayamos escrito nosotros —la prosa de un modelo, una descripción de NVD, un
hallazgo de Nikto, el asunto de un correo— puede llegar hasta él sin pasar por
aquí.
"""

import re

from xml.etree import ElementTree
from xml.sax.saxutils import escape

_MARKDOWN_BOLD = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", re.DOTALL)


def safe_markup(text: str) -> str:
    """Convierte texto no confiable en el mini-HTML que entiende ``Paragraph``.

    Todo lo que un informe imprime sin haberlo escrito nosotros pasa por aquí:
    la prosa del modelo, las descripciones de NVD y los hallazgos de Nikto.
    Dos motivos, y el primero no es cosmético:

    1. ``Paragraph`` parsea sus marcas como XML, así que un ``<`` seguido de
       letra aborta el build entero con ValueError — no imprime el texto en
       crudo, tumba el PDF. No es hipotético: unas 4.000 descripciones de NVD
       traen construcciones así ("Listen to !nick <source>"), y una de cada
       diez basta para reventar el informe entero.
    2. Los modelos escriben markdown por costumbre aunque se les pida que no.
       ``**Apache 2.4.7**`` salía literal en el papel, y traducirlo aquí es
       más fiable que confiar en que el prompt se respete siempre.

    Solo se traduce ``**negrita**``. Ni ``__x__`` ni ``*cursiva*``: sobre texto
    arbitrario disparan constantemente — los volcados de kernel de NVD están
    llenos de ``****`` y de ``__mutex_lock_common``, y emparejarlos generaba
    etiquetas cruzadas que rompían justo lo que esta función debía evitar.

    Por eso el resultado se valida antes de devolverlo: si la conversión no ha
    quedado bien formada, se descarta y sale el texto escapado a secas. Feo
    antes que caído — ninguna entrada puede tumbar el PDF.

    Args:
        text: Texto a sanear. Acepta cualquier objeto convertible a ``str``;
            si es vacío o ``None`` el resultado es la cadena vacía.

    Returns:
        str: El texto escapado, con los saltos de línea convertidos en
            ``<br/>`` y ``**negrita**`` traducido a ``<b>…</b>``. Si esa
            traducción no produce XML bien formado, se devuelve solo la
            versión escapada, sin negritas.
    """
    if not text:
        return ""

    plain = escape(str(text)).replace("\n", "<br/>")
    markup = _MARKDOWN_BOLD.sub(r"<b>\1</b>", plain)

    if markup != plain:
        try:
            ElementTree.fromstring(f"<p>{markup}</p>")
        except ElementTree.ParseError:
            return plain

    return markup
