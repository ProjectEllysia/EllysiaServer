"""La consulta pública de CVE: ``GET /themis/kb/cve``, sin sesión.

Es la herramienta gratuita «Consulta de CVE». Se comprueba que responde sin
credenciales, que solo acepta un identificador de CVE completo (no un texto
libre) y que la respuesta no crece sin límite para una CVE que afecta a muchos
productos.
"""

from __future__ import annotations

import pytest

from src.modules.features.themis.managers.kb_sync import PUBLIC_CVE_LIST_LIMIT
from src.modules.features.themis.repositories import KbRepository
from src.modules.infrastructure import UnitOfWork

pytestmark = pytest.mark.integration


def _match(vendor: str, product: str) -> dict:
    """Una coincidencia CPE de rango, con el formato que espera ``upsert_cve``."""
    return {"vendor": vendor, "product": product, "exact_version": None,
            "version_start_including": "1.0", "version_start_excluding": None,
            "version_end_including": None, "version_end_excluding": "2.0"}


def _seed_cve(app, cve_id: str, matches: list[dict]) -> None:
    """Guarda una CVE de NVD con las coincidencias dadas."""
    with app.app_context():
        with UnitOfWork() as uow:
            KbRepository(uow).upsert_cve(
                {"cve_id": cve_id, "cvss_score": 9.8, "severity": "CRITICAL",
                 "description": "Una vulnerabilidad de prueba", "source": "nvd"},
                matches,
            )


def test_anyone_can_look_up_a_known_cve_without_a_session(client, app):
    _seed_cve(app, "CVE-2024-6387", [_match("openbsd", "openssh")])

    response = client.get("/themis/kb/cve?id=CVE-2024-6387")

    assert response.status_code == 200
    cve = response.get_json()["cve"]
    assert cve["cveId"] == "CVE-2024-6387"
    assert cve["cvssScore"] == 9.8
    assert cve["severity"] == "CRITICAL"
    assert cve["inKev"] is False
    assert cve["products"] == [{"vendor": "openbsd", "product": "openssh"}]
    assert cve["productsTotal"] == 1


def test_the_identifier_is_accepted_in_lowercase(client, app):
    _seed_cve(app, "CVE-2023-4863", [_match("google", "chrome")])

    cve = client.get("/themis/kb/cve?id=cve-2023-4863").get_json()["cve"]

    assert cve["cveId"] == "CVE-2023-4863"


def test_a_cve_the_knowledge_base_does_not_know_is_not_an_error(client):
    response = client.get("/themis/kb/cve?id=CVE-2099-0001")

    assert response.status_code == 200
    assert response.get_json() == {"cve": None}


@pytest.mark.parametrize("query", [
    "",
    "?id=",
    "?id=openssh",
    "?id=CVE-24-1",
    "?id=CVE-2024-6387%20OR%201=1",
    "?id=CVE-2024-6387%0A",
    "?id=CVE-2024-12345678",
])
def test_only_a_complete_cve_identifier_is_accepted(client, query):
    assert client.get(f"/themis/kb/cve{query}").status_code == 422


def test_a_cve_with_many_products_comes_back_trimmed_with_its_total(client, app):
    many = [_match("vendor", f"product{index:03d}") for index in range(PUBLIC_CVE_LIST_LIMIT + 25)]
    _seed_cve(app, "CVE-2022-0847", many)

    cve = client.get("/themis/kb/cve?id=CVE-2022-0847").get_json()["cve"]

    assert len(cve["products"]) == PUBLIC_CVE_LIST_LIMIT
    assert cve["productsTotal"] == PUBLIC_CVE_LIST_LIMIT + 25
    assert cve["distroStatusesTotal"] == 0
