"""Exportación de Iris para un SOC: un análisis o una campaña, en JSON, STIX o MISP.

Ejecuta el catálogo real como el worker y exporta por la API. Comprueba que lo
exportado sale del índice de IOCs (así sobrevive a la purga del correo), que
el JSON va desactivado por defecto, que STIX y MISP son una acción explícita
(``POST``), y que nadie exporta lo que no es suyo.
"""

from __future__ import annotations

import pytest
import stix2

from src.modules.features.iris.managers.analysis import _run_analysis
from src.modules.features.iris.model import IrisAnalysis
from src.modules.features.iris.repositories import IrisAnalysisRepository
from src.modules.infrastructure import UnitOfWork
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE,
    AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]


def _phishing(invoice: int) -> str:
    return (
        "From: Soporte PayPal <avisos@paypa1-secure.example>\r\n"
        "To: ana@corp.example\r\n"
        f"Subject: Factura {invoice} pendiente de pago\r\n"
        "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
        f"Message-ID: <{invoice}@paypa1-secure.example>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        f"<p>La factura {invoice} vence hoy. Verifique su cuenta.</p>"
        "<a href=\"http://paypa1-secure.example/login\">https://www.paypal.com</a>\r\n"
    )


def _analyze(app, user_id: int, raw: str) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers=raw, user_id=user_id, status="pending")
            IrisAnalysisRepository(uow).save(analysis)
            analysis_id = analysis.id
        _run_analysis(analysis_id, raw)
    return analysis_id


@pytest.fixture
def analyst(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    return user, auth_headers(user)


def test_the_versioned_json_is_a_defanged_download(client, app, analyst):
    user, headers = analyst
    analysis_id = _analyze(app, user.id, _phishing(1))

    response = client.get(f"/iris/results/{analysis_id}/export/intel", headers=headers)

    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    document = response.get_json()
    assert document["schemaVersion"] == "iris-export/1" and document["defanged"] is True
    urls = [indicator["value"] for indicator in document["indicators"] if indicator["type"] == "url"]
    assert urls == ["hxxp://paypa1-secure[.]example/login"]
    assert document["subject"]["verdict"] == "Phishing"
    assert any(finding["ruleId"] for finding in document["findings"])


def test_stix_is_an_explicit_action_and_valid(client, app, analyst):
    user, headers = analyst
    analysis_id = _analyze(app, user.id, _phishing(1))

    response = client.post(f"/iris/results/{analysis_id}/export/intel", headers=headers, json={"format": "stix"})

    assert response.status_code == 200
    parsed = stix2.parse(response.get_json(), allow_custom=True)
    patterns = [stix_object.pattern for stix_object in parsed.objects if stix_object.type == "indicator"]
    assert "[url:value = 'http://paypa1-secure.example/login']" in patterns


def test_misp_export_of_an_analysis(client, app, analyst):
    user, headers = analyst
    analysis_id = _analyze(app, user.id, _phishing(1))

    event = client.post(f"/iris/results/{analysis_id}/export/intel", headers=headers,
                        json={"format": "misp"}).get_json()["Event"]

    url = next(attribute for attribute in event["Attribute"] if attribute["type"] == "url")
    assert url["value"] == "http://paypa1-secure.example/login" and url["to_ids"] is True


def test_an_unknown_format_is_rejected(client, app, analyst):
    user, headers = analyst
    analysis_id = _analyze(app, user.id, _phishing(1))

    response = client.post(f"/iris/results/{analysis_id}/export/intel", headers=headers, json={"format": "csv"})

    assert response.status_code in (400, 422)


def test_the_export_survives_the_raw_purge(client, app, analyst):
    user, headers = analyst
    analysis_id = _analyze(app, user.id, _phishing(1))
    with app.app_context():
        with UnitOfWork() as uow:
            IrisAnalysisRepository(uow).get_by_id(analysis_id).raw_headers = None

    document = client.get(f"/iris/results/{analysis_id}/export/intel?defang=false", headers=headers).get_json()

    assert "http://paypa1-secure.example/login" in {indicator["value"] for indicator in document["indicators"]}


def test_a_campaign_exports_as_one_document(client, app, analyst):
    user, headers = analyst
    first = _analyze(app, user.id, _phishing(1))
    second = _analyze(app, user.id, _phishing(2))
    campaign_id = client.get(f"/iris/results/{second}", headers=headers).get_json()["campaign"]["campaignId"]

    document = client.post(f"/iris/campaigns/{campaign_id}/export", headers=headers,
                           json={"format": "json", "defang": False}).get_json()

    assert {analysis["analysisId"] for analysis in document["analyses"]} == {first, second}
    url = next(indicator for indicator in document["indicators"] if indicator["type"] == "url")
    assert url["analysisIds"] == sorted([first, second])
    stix_bundle = client.post(f"/iris/campaigns/{campaign_id}/export", headers=headers,
                              json={"format": "stix"}).get_json()
    assert "campaign" in {stix_object.type for stix_object in stix2.parse(stix_bundle, allow_custom=True).objects}


def test_nobody_exports_what_is_not_theirs(client, app, analyst, make_user, auth_headers):
    user, _ = analyst
    analysis_id = _analyze(app, user.id, _phishing(1))
    other_headers = auth_headers(make_user(role="role_user", attributes=_IRIS_ATTRIBUTES))

    assert client.get(f"/iris/results/{analysis_id}/export/intel", headers=other_headers).status_code == 404
    assert client.post(f"/iris/results/{analysis_id}/export/intel", headers=other_headers,
                       json={"format": "stix"}).status_code == 404
