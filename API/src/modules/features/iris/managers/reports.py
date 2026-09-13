"""
IrisReportManager — ciclo de vida de IrisDocument y generación asíncrona
del informe PDF.

El CRUD y la comprobación de propiedad los comparte con Themis vía
``DocumentManager``; aquí queda solo lo propio de Iris: crear el
``IrisDocument`` y renderizar su PDF con :class:`IrisPDFCreator`.
"""

from __future__ import annotations

import logging

from src.modules.shared._exceptions import DocumentNotFoundError
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared._documents import run_report_generation, submit_report_generation, DocumentManager
from src.modules.system.taskqueue import job_context

from ..exceptions import IrisAnalysisNotReadyError
from ..model import IrisAnalysis, IrisDocument
from ..repositories import IrisAnalysisRepository, IrisReportRepository
from ..services import parse_raw_message
from ..services.parsers import build_path
from ..services.reports import IrisPDFCreator

from .analysis import IrisManager


logger = logging.getLogger(__name__)


def _generate_pdf_async(document_id: int, analysis_id: int) -> None:
    """Genera el PDF del informe en el worker y sincroniza el estado del documento.

    Delega en ``run_report_generation`` (helper compartido con Themis) que
    gestiona el marcado ``done``/``error`` y el re-lanzamiento de la
    excepción para que el job de RQ termine como FAILED si algo falla.

    Args:
        document_id: Primary key del ``IrisDocument`` ya creado (en estado
            ``running``) al que se le sincroniza el resultado.
        analysis_id: Análisis ya terminado a partir del cual se construye
            el informe.

    Returns:
        None.
    """
    def _render() -> str:
        """Renderiza el PDF a partir del análisis y devuelve la ruta del fichero.

        Returns:
            str: Ruta del PDF generado, tal y como la entrega
                ``IrisPDFCreator.print_pdf``.
        """
        report = IrisManager().get_analysis_results(analysis_id)
        analysis = build_repository(IrisAnalysisRepository).get_by_id(analysis_id)
        path = None
        if analysis is not None:
            context = parse_raw_message(analysis.raw_headers or "")
            path = {"analysisId": analysis_id, **build_path(context.received_headers)}
        return IrisPDFCreator(report=report, path=path,
                                document_id=document_id).print_pdf()

    run_report_generation(
        document_id=document_id,
        repo_cls=IrisReportRepository,
        render=_render,
    )


def _create_document(analysis: IrisAnalysis) -> int:
    """Crea el ``IrisDocument`` de un análisis terminado, en estado ``running``.

    Args:
        analysis: Análisis (``finished``) para el que se genera el informe;
            se copian su dueño y su veredicto al documento.

    Returns:
        int: Primary key del ``IrisDocument`` creado.
    """
    with UnitOfWork() as uow:
        document = IrisDocument(
            analysis_id=analysis.id,
            document_type="iris",
            filename="",
            format="pdf",
            status="running",
            user_id=analysis.user_id,
            verdict=analysis.verdict,
            is_ai_generated=0,
        )
        IrisReportRepository(uow).save(document)
        # Durable antes de encolar: el worker corre en otro proceso.
        uow.commit_for_handoff()
    return document.id  # type: ignore


class IrisReportManager(DocumentManager):
    """Ciclo de vida de ``IrisDocument`` y generación asíncrona de su PDF.

    El CRUD y la comprobación de propiedad los hereda de ``DocumentManager``,
    compartido con Themis; esta clase añade solo lo propio de Iris: crear el
    ``IrisDocument`` y renderizar su PDF con :class:`IrisPDFCreator`.

    Attributes:
        EXTERNAL_ID_PREFIX: Prefijo del ``external_id`` de TaskQueue para los
            jobs de este manager (``iris-doc:``).
        TASK_CATEGORY: Categoría de TaskQueue en la que se encolan
            (``iris.report``).
    """

    EXTERNAL_ID_PREFIX = "iris-doc:"
    TASK_CATEGORY = "iris.report"

    _REPOSITORY = IrisReportRepository
    _NOT_FOUND_ERROR = DocumentNotFoundError

    def generate_report(self, analysis_id: int, user_id: int) -> int:
        """Crea el ``IrisDocument`` y arranca la generación asíncrona del PDF.

        Args:
            analysis_id: Primary key del análisis ya terminado.
            user_id: Dueño del análisis; aquí se comprueba la propiedad.

        Returns:
            int: Primary key del ``IrisDocument`` creado.

        Raises:
            IrisAnalysisNotFoundError: Si el análisis no existe o no es de
                ``user_id``.
            IrisAnalysisNotReadyError: Si el análisis no está ``finished``.
        """
        analysis = IrisManager.assert_analysis_ownership(analysis_id, user_id)
        if analysis.status != "finished":
            raise IrisAnalysisNotReadyError(analysis_id, analysis.status)

        doc_id = _create_document(analysis)

        submit_report_generation(
            self._task_queue, doc_id, self._REPOSITORY,
            func=IrisReportManager.execute_report_generation,
            args=(doc_id, analysis_id),
            name=f"PDFGeneration-Analysis-{analysis_id}",
            category=self.TASK_CATEGORY,
            external_id=self.external_id_for(doc_id),
        )
        return doc_id  # type: ignore

    @staticmethod
    def execute_report_generation(doc_id: int, analysis_id: int) -> None:
        """
        Punto de entrada que ejecuta el worker para generar el PDF en segundo plano.

        Args:
            doc_id: Primary key del ``IrisDocument`` creado por
                ``generate_report``.
            analysis_id: Análisis a partir del cual se renderiza el informe.
        """
        with job_context():
            _generate_pdf_async(doc_id, analysis_id)
