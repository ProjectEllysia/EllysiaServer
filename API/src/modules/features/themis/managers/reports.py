"""Gestión de documentos de Themis y generación asíncrona de sus informes PDF."""

import logging
from src.modules.accounts import LimitKey, QuotaManager
from src.modules.system.taskqueue import job_context
from src.modules.shared import assert_owned
from src.modules.shared._exceptions import DocumentError, ValidationError
from src.modules.shared._documents import run_report_generation, submit_report_generation, DocumentManager
from src.modules.infrastructure import UnitOfWork, build_repository
from ..exceptions import ScanNotFoundError
from ..repositories import OsintScanRepository, ThemisReportRepository
from ..model import OsintScanMode, ScanStatus, ThemisDocument
from ..services import CloudExposurePDFCreator, PDFCreator
from ..services.reports.findings import effective_frameworks

from .scan import ScanManager


logger = logging.getLogger(__name__)


def _create_domain_document(osint_scan) -> int:
    """Crea el ``ThemisDocument`` de un escaneo de dominio y lo confirma ya.

    Args:
        osint_scan: La fila ``OsintScan`` de la que se va a informar.

    Returns:
        int: La clave primaria del documento creado.
    """
    with UnitOfWork() as uow:
        document = ThemisDocument(
            osint_scan_id   = osint_scan.id,
            scan_type       = osint_scan.mode,
            document_type   = "themis",
            filename        = "",
            format          = "pdf",
            status          = "running",
            user_id         = osint_scan.user_id,
            is_ai_generated = 0,
        )
        ThemisReportRepository(uow).save(document)
        # Durable antes de encolar: el worker corre en otro proceso.
        uow.commit_for_handoff()
    return document.id  # type: ignore


def _run_domain_report(document_id: int, osint_scan_id: int) -> None:
    """Cuerpo del job: dibuja el informe de un escaneo de dominio y marca el documento.

    Los marcos de cumplimiento se leen aquí, en el worker, y no al pedir el
    informe: si el dueño los cambia mientras el job espera en la cola, el
    informe sale con los vigentes al generarlo, igual que el de un escaneo.

    Args:
        document_id: Clave primaria del ``ThemisDocument``.
        osint_scan_id: Clave primaria del ``OsintScan``.
    """
    def render() -> str:
        """Carga el escaneo y escribe el PDF; devuelve su ruta."""
        osint_scan = build_repository(OsintScanRepository).get_by_id(osint_scan_id)
        if osint_scan is None:
            raise ScanNotFoundError(osint_scan_id)
        frameworks = effective_frameworks(osint_scan.user_id)
        generator = CloudExposurePDFCreator(osint_scan, frameworks=frameworks,
                                            document_id=document_id)
        return generator.print_pdf()

    run_report_generation(document_id=document_id, repo_cls=ThemisReportRepository, render=render)


class ThemisReportManager(DocumentManager):
    """
    Manager for Themis document lifecycle and PDF report generation.

    Handles document CRUD operations, ownership verification, and async
    PDF generation for security scan reports. CRUD/ownership are shared with
    Iris via ``DocumentManager`` (A3); this class keeps only what is really
    Themis-specific: creating a ``ThemisDocument`` and rendering its PDF.
    """

    EXTERNAL_ID_PREFIX = "themis-doc:"
    TASK_CATEGORY = "themis.report"

    _REPOSITORY = ThemisReportRepository
    _NOT_FOUND_ERROR = staticmethod(lambda eid: DocumentError(f"Documento {eid} no encontrado"))

    @staticmethod
    def _create_document(scan, ai_report: bool) -> int:
        """Create a ThemisDocument for a scan and return its ID."""
        with UnitOfWork() as uow:
            document = ThemisDocument(
                scan_id         = scan.id,
                scan_type       = scan.scan_type,
                document_type   = "themis",
                filename        = "",
                format          = "pdf",
                status          = "running",
                user_id         = scan.user_id,
                is_ai_generated = 1 if ai_report else 0,
            )
            ThemisReportRepository(uow).save(document)
            # Durable antes de encolar: el worker corre en otro proceso.
            uow.commit_for_handoff()

        return document.id  # type: ignore

    # get_documents_by_parent: usa el default de DocumentManager (A9).

    def generate_report(self, scan_id: int, ai_report: bool = False) -> int:
        """
        Create a ThemisDocument and start async PDF generation.

        Args:
            scan_id:   Primary key of the scan.
            ai_report: Include AI-generated analysis.

        Returns:
            Primary key of the created ThemisDocument.
        """
        scan_manager = ScanManager.resolve_manager(scan_id)
        scan = scan_manager.get_scan_by_id(scan_id)
        if not scan:
            raise ValueError(f"Escaneo {scan_id} no encontrado")

        # Solo el informe con IA cuesta dinero; el PDF a secas no consume nada.
        # Se cobra al pedirlo y no al terminarlo: el trabajo se encola aquí, y
        # esperar al worker dejaría un hueco para pedir mil informes a la vez.
        #
        # Dos claves por la misma acción, y es intencionado: la concreta es la
        # que el usuario ve en su plan, y ai.requests es el techo agregado que
        # protege el coste de la IA aunque cada módulo por separado sea
        # generoso. Primero la concreta, para que el 402 nombre lo que el
        # usuario estaba intentando hacer.
        if ai_report:
            quota_manager = QuotaManager()
            quota_manager.consume(scan.user_id, LimitKey.THEMIS_REPORTS_AI)
            quota_manager.consume(scan.user_id, LimitKey.AI_REQUESTS)

        doc_id = self._create_document(scan, ai_report)

        submit_report_generation(
            self._task_queue, doc_id, self._REPOSITORY,
            func=ThemisReportManager.execute_report_generation,
            args=(doc_id, scan.id, ai_report),
            name=f"PDFGeneration-Scan-{scan.id}",
            category=self.TASK_CATEGORY,
            external_id=self.external_id_for(doc_id),
        )
        return doc_id  # type: ignore

    @staticmethod
    def execute_report_generation(doc_id: int, scan_id: int, ai_report: bool) -> None:
        """Entry point submitted to the TaskQueue for background PDF generation."""
        with job_context():
            ThemisReportManager()._generate_pdf_async(doc_id, scan_id, ai_report)

    def _generate_pdf_async(
        self,
        document_id: int,
        scan_id: int,
        ai_report: bool,
    ) -> None:
        """Genera el PDF del informe en el worker y sincroniza el estado del documento.

        Delega en ``run_report_generation`` (helper compartido con Iris) que
        gestiona el marcado ``done``/``error`` y la re-lanzamiento de la
        excepción para que el job de RQ termine como FAILED si algo falla.
        """
        run_report_generation(
            document_id=document_id,
            repo_cls=ThemisReportRepository,
            render=lambda: PDFCreator(scan_id, document_id, ai_report=ai_report).print_pdf(),
        )

    def generate_domain_report(self, osint_scan_id: int, user_id: int) -> int:
        """Crea el informe de un escaneo de dominio y encola su generación.

        Solo los escaneos de exposición cloud tienen informe: el pasivo no
        comprueba nada que se pueda corregir, solo reúne lo que se sabe del
        dominio. El informe no lleva análisis con IA, así que no consume cuota.

        Args:
            osint_scan_id: Clave primaria del ``OsintScan``.
            user_id: Quien lo pide; tiene que ser el dueño del escaneo.

        Returns:
            int: La clave primaria del ``ThemisDocument`` creado, en ``running``.

        Raises:
            ScanNotFoundError: Si el escaneo no existe o es de otro usuario.
            ValidationError: Si el escaneo no es cloud o aún no ha terminado.
        """
        osint_scan = assert_owned(OsintScanRepository, osint_scan_id, user_id, ScanNotFoundError)
        if osint_scan.mode != OsintScanMode.CLOUD.value:
            raise ValidationError(
                f"El escaneo {osint_scan_id} es de modo {osint_scan.mode}, sin informe",
                field="osint_scan_id", value=osint_scan_id,
                user_message="Solo los escaneos de exposición en la nube tienen informe.")
        if osint_scan.status != ScanStatus.FINISHED.value:
            raise ValidationError(
                f"El escaneo {osint_scan_id} no está terminado ({osint_scan.status})",
                field="osint_scan_id", value=osint_scan_id,
                user_message="El escaneo aún no ha terminado: pide el informe cuando acabe.")
        document_id = _create_domain_document(osint_scan)
        submit_report_generation(
            self._task_queue, document_id, self._REPOSITORY,
            func=ThemisReportManager.execute_domain_report_generation,
            args=(document_id, osint_scan_id),
            name=f"PDFGeneration-Domain-{osint_scan_id}-{document_id}",
            category=self.TASK_CATEGORY,
            external_id=self.external_id_for(document_id),
        )
        return document_id

    def get_domain_documents(self, osint_scan_id: int, user_id: int) -> list:
        """Los informes de un escaneo de dominio, del más nuevo al más viejo.

        Args:
            osint_scan_id: Clave primaria del ``OsintScan``.
            user_id: Quien lo pide; tiene que ser el dueño del escaneo.

        Returns:
            list[ThemisDocument]: Sus informes; vacía si no tiene ninguno.

        Raises:
            ScanNotFoundError: Si el escaneo no existe o es de otro usuario.
        """
        assert_owned(OsintScanRepository, osint_scan_id, user_id, ScanNotFoundError)
        return build_repository(ThemisReportRepository).get_documents_by_osint_scan(osint_scan_id)

    @staticmethod
    def execute_domain_report_generation(doc_id: int, osint_scan_id: int) -> None:
        """Punto de entrada que ejecuta el worker de la TaskQueue.

        Args:
            doc_id: Clave primaria del ``ThemisDocument``.
            osint_scan_id: Clave primaria del ``OsintScan``.
        """
        with job_context():
            _run_domain_report(doc_id, osint_scan_id)
