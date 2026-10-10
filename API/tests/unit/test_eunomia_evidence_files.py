"""Lo que se acepta como evidencia: tipo real, tamaño y ausencia de contenido activo."""

import io
import zipfile

import pytest

from src.modules.features.eunomia.exceptions import (
    EvidenceActiveContentError,
    EvidenceTooLargeError,
    EvidenceTypeMismatchError,
    EvidenceTypeNotAllowedError,
)
from src.modules.features.eunomia.services.evidence_files import check_upload, sanitize_filename

pytestmark = pytest.mark.unit

ALLOWED = ["pdf", "png", "jpg", "jpeg", "docx", "xlsx", "odt", "ods", "txt", "csv"]
LIMIT = 1024 * 1024


def _zip(entries: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _docx(**extra) -> bytes:
    return _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": "<w:document/>", **extra})


def test_a_clean_pdf_is_accepted():
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"

    assert check_upload("politica.pdf", pdf, LIMIT, ALLOWED) == "application/pdf"


def test_an_executable_renamed_to_pdf_is_rejected():
    with pytest.raises(EvidenceTypeMismatchError):
        check_upload("politica.pdf", b"MZ\x90\x00\x03" + b"\x00" * 100, LIMIT, ALLOWED)


def test_a_pdf_with_javascript_is_rejected():
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>\nendobj\n%%EOF\n"

    with pytest.raises(EvidenceActiveContentError):
        check_upload("politica.pdf", pdf, LIMIT, ALLOWED)


def test_a_docx_with_macros_is_rejected():
    document = _docx(**{"word/vbaProject.bin": b"\x00macro"})

    with pytest.raises(EvidenceActiveContentError):
        check_upload("informe.docx", document, LIMIT, ALLOWED)


def test_a_clean_docx_is_accepted():
    assert check_upload("informe.docx", _docx(), LIMIT, ALLOWED).endswith("wordprocessingml.document")


def test_a_macro_enabled_extension_is_not_in_the_list():
    with pytest.raises(EvidenceTypeNotAllowedError):
        check_upload("informe.docm", _docx(), LIMIT, ALLOWED)


def test_a_zip_pretending_to_be_a_docx_is_rejected():
    with pytest.raises(EvidenceTypeMismatchError):
        check_upload("informe.docx", _zip({"otra/cosa.txt": "hola"}), LIMIT, ALLOWED)


def test_a_file_over_the_limit_is_rejected():
    with pytest.raises(EvidenceTooLargeError):
        check_upload("big.txt", b"a" * (LIMIT + 1), LIMIT, ALLOWED)


def test_text_with_null_bytes_is_not_text():
    with pytest.raises(EvidenceTypeMismatchError):
        check_upload("notas.txt", b"hola\x00mundo", LIMIT, ALLOWED)


def test_plain_text_and_csv_are_accepted():
    assert check_upload("notas.txt", "acción".encode("utf-8"), LIMIT, ALLOWED) == "text/plain"
    assert check_upload("datos.csv", b"a,b\n1,2\n", LIMIT, ALLOWED) == "text/csv"


def test_the_filename_loses_paths_and_control_characters():
    assert sanitize_filename("../../etc/pass\x00wd.pdf").endswith("passwd.pdf") or "/" not in sanitize_filename("../../etc/pass\x00wd.pdf")
    assert sanitize_filename("") == "evidencia"
