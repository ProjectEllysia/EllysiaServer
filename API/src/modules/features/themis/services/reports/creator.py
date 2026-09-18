"""
``PDFCreator``: arma el informe de un escaneo a partir de su estrategia.

La composición del documento —portada, aparejo de página, nota legal, pie— la
pone ``tools.press``. Aquí solo queda lo propio de Themis: de qué escaneo se
informa, con qué identidad visual y quién dibuja el cuerpo.
"""

import logging
import os

from datetime import datetime
from typing import Optional, Sequence, Tuple

import src.modules.system.config_reading as CR

from src.modules.tools.press import DocumentStyle, PdfGenerator, ReportTheme
from .base import PrintingStrategy

logger = logging.getLogger(__name__)

#: Texto de la declaración que cierra todos los informes de Themis. Un escaneo
#: se hace sobre sistemas ajenos, así que el informe tiene que dejar constancia
#: de quién respondía de esa autorización.
_CONSENT_TEXT = """
El usuario declara y confirma que ha otorgado su consentimiento expreso e
inequívoco para la realización del escaneo de seguridad sobre el sitio web
y/o sistema informático objeto del presente informe. El usuario acepta y
reconoce que es el titular legítimo o cuenta con la autorización necesaria
de los equipos, sistemas y redes escaneados.

El usuario asume la plena responsabilidad sobre las consecuencias derivadas
del escaneo realizado, incluyendo cualquier resultado, hallazgo o
vulnerabilidad identificada en el proceso. Asimismo, el usuario exonera
de toda responsabilidad a los ejecutores del análisis de seguridad respecto
al uso que se haga de la información contenida en este documento.

Este documento contiene información sensible de carácter confidencial y
debe ser tratado con las medidas de seguridad apropiadas conforme a la
normativa vigente en materia de protección de datos.
"""


class PDFCreator(PdfGenerator):
    """Compone el informe PDF de un escaneo de Themis.

    Themis no tiene un cuerpo, tiene cuatro: Nmap, Nikto, Nuclei y Lybra
    imprimen cosas distintas. Por eso el cuerpo no se escribe aquí sino en la
    ``PrintingStrategy`` de cada tipo de escaneo, que además aporta la paleta,
    el logotipo y el título. Esta clase es la costura entre ese registro de
    estrategias y la composición común de ``press``.

    Attributes:
        printing_strategy: La estrategia del tipo de escaneo, ya resuelta por
            el registro. De ella salen el cuerpo, la paleta, el título y el
            sufijo del nombre de fichero.
        scan: El escaneo del que se informa, ya cargado por la estrategia.
        document_id: Clave primaria del ``ThemisDocument`` al que pertenece
            este PDF.
        ai_report: Si el cuerpo incluye el análisis generado con IA.
        client_name: Nombre del cliente para la ficha de la portada.
        directory: Directorio de salida de los informes de Themis.
    """

    def __init__(
        self,
        scan_id: int,
        document_id: Optional[int] = None,
        ai_report: bool = False,
        client_name: Optional[str] = None,
    ) -> None:
        """Resuelve la estrategia del escaneo y prepara el generador.

        A diferencia de Iris y Hygeia, que reciben los datos ya cargados, aquí
        se entra por identificador: hasta saber de qué tipo es el escaneo no se
        puede elegir la estrategia que lo dibuja, y el tipo está en la base de
        datos. La carga queda confinada a ``resolve_printing_strategy``, que
        actúa de fábrica; la capa que dibuja —la estrategia— sí recibe un
        escaneo ya cargado.

        Args:
            scan_id: Clave primaria del escaneo del que se informa.
            document_id: Clave primaria del ``ThemisDocument``. Va en el nombre
                del fichero, así que dos documentos del mismo escaneo —uno
                simple y otro con IA, o una regeneración— nunca escriben encima
                el uno del otro. Por defecto ``None``, y entonces el nombre
                depende solo del escaneo.
            ai_report: Añade al cuerpo el análisis de seguridad generado con
                IA. Por defecto ``False``.
            client_name: Nombre del cliente, que sale en la ficha de la
                portada. Por defecto ``None``, y entonces esa fila no se
                imprime. Ninguna ruta de la aplicación lo rellena hoy.

        Raises:
            ValidationError: Si el escaneo es de un tipo desconocido o sin
                estrategia de impresión registrada.
        """
        strategy = PrintingStrategy.resolve_printing_strategy(scan_id)
        resource_directory = CR.get_directory_of(CR.DirectoryType.RESOURCES_THEMIS)

        super().__init__(DocumentStyle(
            palette=strategy.color_palette,
            header_title="Ellysia Security Report",
            logo_path=os.path.join(resource_directory, strategy.get_picture_name()),
        ))
        self.printing_strategy = strategy
        self.scan = strategy.scan
        self.document_id = document_id
        self.ai_report = ai_report
        self.client_name = client_name
        self.directory = CR.get_directory_of(CR.DirectoryType.OUTPUT_THEMIS)

    def cover_title(self) -> str:
        """Título de la portada: el que declare la estrategia del escaneo.

        Returns:
            str: "Análisis de Seguridad de Red" para Nmap, "Veredicto del Motor
                Lybra" para Lybra, y así con cada tipo.
        """
        return self.printing_strategy.get_report_title()

    def cover_fields(self) -> Sequence[Sequence[str]]:
        """Ficha de la portada: el cliente, si lo hay, y la fecha del escaneo.

        La fecha es la de inicio del escaneo, no la de generación del informe:
        un informe regenerado meses después sigue hablando de lo que se
        encontró aquel día.

        Returns:
            Sequence[Sequence[str]]: Una o dos filas, según haya cliente.
        """
        started = getattr(self.scan, "started_at", None)
        fields = []
        if self.client_name:
            fields.append(["Cliente:", self.client_name])
        fields.append(["Fecha:", (started or datetime.now()).strftime("%d/%m/%Y")])
        return fields

    def document_title(self) -> str:
        """Título de los metadatos del PDF.

        Returns:
            str: ``"Informe de Seguridad - <id del escaneo>"``.
        """
        return f"Informe de Seguridad - {self.scan.id}"

    def document_subject(self) -> str:
        """Asunto de los metadatos del PDF.

        Returns:
            str: Una frase con la fecha en que se hizo el análisis.
        """
        started = getattr(self.scan, "started_at", None)
        date_str = (started or datetime.now()).strftime("%d/%m/%Y")
        return f"Análisis de seguridad realizado el {date_str}"

    def legal_notice(self) -> Tuple[str, str]:
        """Declaración de conformidad y consentimiento que cierra el informe.

        Returns:
            Tuple[str, str]: El título del recuadro y su texto.
        """
        return ("DECLARACIÓN DE CONFORMIDAD Y CONSENTIMIENTO", _CONSENT_TEXT)

    def append_body(self, elements: list, theme: ReportTheme) -> None:
        """Delega el cuerpo en la estrategia del tipo de escaneo.

        Args:
            elements: Lista de flowables del documento en construcción.
            theme: Los estilos del informe.
        """
        self.printing_strategy.append_body(
            theme=theme, elements=elements, ai_report=self.ai_report,
        )

    def output_path(self) -> str:
        """Ruta del PDF, única por **documento** y no por escaneo.

        Sin el identificador del documento, una generación posterior para el
        mismo escaneo sobrescribía en silencio el fichero al que seguían
        apuntando las filas anteriores.

        Returns:
            str: La ruta absoluta del fichero.
        """
        stem = f"{self.scan.id}_{self.document_id}" if self.document_id else str(self.scan.id)
        return os.path.join(
            self.directory,
            f"{stem}{self.printing_strategy.get_filename_suffix()}",
        )

    def print_pdf(self) -> str:
        """Genera el informe y lo deja escrito en disco.

        Returns:
            str: La ruta del PDF generado.
        """
        return self.generate_to_file(self.output_path())
