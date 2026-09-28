"""Canal de reporte: un correo reportado desde el cliente de correo crea su análisis intacto.

Recorre el camino de un complemento de Outlook o Gmail: el usuario crea un
token de integración en el panel, el complemento manda el mensaje con él
(como fichero o tal cual en el cuerpo) y consulta después cómo acabó. Fija que
el token solo vale para esto, que se puede revocar y caduca, que no sirve como
sesión, que el análisis es del dueño del token y que, cuando el cliente manda
el correo reenviado como adjunto, se analiza el original y se conserva quién lo
reenvió.
"""

from __future__ import annotations

import dataclasses
import io
from datetime import timedelta

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.iris.managers.analysis import _run_analysis
from src.modules.features.iris.model import IrisAnalysis, IrisIntegrationToken
from src.modules.features.iris.repositories import IrisAnalysisRepository, IrisIntegrationTokenRepository
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE, AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]

_ORIGINAL = (
    "From: Soporte PayPal <avisos@paypa1-secure.example>\r\n"
    "To: ana@corp.example\r\n"
    "Subject: Verifique su cuenta\r\n"
    "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
    "Message-ID: <orig-1@paypa1-secure.example>\r\n"
    "Received: from mx.paypa1-secure.example (mx.paypa1-secure.example [203.0.113.7]) by mx.corp.example\r\n"
    "MIME-Version: 1.0\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    "Su cuenta será suspendida. Verifique aquí: http://paypa1-secure.example/login\r\n"
)


def _forward_as_attachment(original: str) -> str:
    """Lo que produce «reenviar como adjunto»: un mensaje que lleva el original como message/rfc822."""
    return (
        "From: Ana <ana@corp.example>\r\n"
        "To: seguridad@corp.example\r\n"
        "Subject: Fwd: Verifique su cuenta\r\n"
        "Date: Mon, 1 Jan 2026 11:00:00 +0000\r\n"
        "Message-ID: <fwd-1@corp.example>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=\"frontera\"\r\n\r\n"
        "--frontera\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Me parece phishing.\r\n"
        "--frontera\r\n"
        "Content-Type: message/rfc822\r\n"
        "Content-Disposition: attachment; filename=\"original.eml\"\r\n\r\n"
        f"{original}\r\n"
        "--frontera--\r\n"
    )


@pytest.fixture
def analyst(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    return user, auth_headers(user)


def _create_token(client, headers, **body) -> dict:
    response = client.post("/iris/integration-tokens", headers=headers, json={"name": "Outlook", **body})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _token_headers(token: str, channel: str = "outlook_addin") -> dict:
    return {"Authorization": f"Bearer {token}", "X-Ellysia-Report-Channel": channel}


def _report_raw(client, token: str, raw: str, channel: str = "gmail_addon"):
    return client.post("/iris/reports", headers=_token_headers(token, channel),
                       data=raw.encode("utf-8"), content_type="message/rfc822")


def _report_file(client, token: str, raw: bytes, filename: str = "sospechoso.eml"):
    return client.post("/iris/reports", headers=_token_headers(token),
                       data={"message": (io.BytesIO(raw), filename)}, content_type="multipart/form-data")


def _analysis(app, analysis_id: int) -> IrisAnalysis:
    with app.app_context():
        return build_repository(IrisAnalysisRepository).get_by_id(analysis_id)


# --------------------------------------------------------------------------- tokens

def test_the_token_is_shown_once_and_only_its_hash_is_stored(client, app, analyst):
    _, headers = analyst
    created = _create_token(client, headers)

    assert created["token"].startswith("irt_") and created["status"] == "active"
    listing = client.get("/iris/integration-tokens", headers=headers).get_json()["tokens"]
    assert "token" not in listing[0] and listing[0]["keyId"] == created["keyId"]
    with app.app_context():
        stored = build_repository(IrisIntegrationTokenRepository).get_by_id(created["tokenId"])
    secret = created["token"].split(".", 1)[1]
    assert secret not in stored.secret_sha256


def test_a_token_lifetime_is_capped(client, analyst):
    _, headers = analyst
    response = client.post("/iris/integration-tokens", headers=headers, json={"name": "x", "lifetimeDays": 5000})
    assert response.status_code == 400


def test_the_number_of_valid_tokens_is_capped(client, analyst, monkeypatch):
    _, headers = analyst
    monkeypatch.setattr(CR, "iris_reporting_config", lambda: CR.IrisReportingConfig(max_tokens_per_user=1))
    first = _create_token(client, headers)

    response = client.post("/iris/integration-tokens", headers=headers, json={"name": "otro"})
    assert response.status_code == 409 and response.get_json()["messageKey"] == "irisIntegrationTokenLimitReached"

    client.delete(f"/iris/integration-tokens/{first['tokenId']}", headers=headers)
    assert client.post("/iris/integration-tokens", headers=headers, json={"name": "otro"}).status_code == 201


def test_a_token_of_another_user_cannot_be_revoked(client, analyst, make_user, auth_headers):
    _, headers = analyst
    created = _create_token(client, headers)
    intruder = auth_headers(make_user(role="role_user", attributes=_IRIS_ATTRIBUTES))

    assert client.delete(f"/iris/integration-tokens/{created['tokenId']}", headers=intruder).status_code == 404


# --------------------------------------------------------------------------- reportar

def test_a_reported_message_creates_its_analysis_with_the_channel(client, app, analyst):
    user, headers = analyst
    token = _create_token(client, headers)

    response = _report_raw(client, token["token"], _ORIGINAL, channel="gmail_addon")

    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["status"] == "pending" and body["isDuplicate"] is False and body["reportChannel"] == "gmail_addon"
    analysis = _analysis(app, body["analysisId"])
    assert analysis.user_id == user.id and analysis.report_channel == "gmail_addon"
    assert analysis.integration_token_id == token["tokenId"]
    assert analysis.raw_headers == _ORIGINAL, "el mensaje original llega intacto"
    assert analysis.title == "Verifique su cuenta"


def test_a_message_can_also_be_uploaded_as_a_file(client, app, analyst):
    _, headers = analyst
    token = _create_token(client, headers)

    response = _report_file(client, token["token"], _ORIGINAL.encode("utf-8"))

    assert response.status_code == 201
    assert _analysis(app, response.get_json()["analysisId"]).report_channel == "outlook_addin"


def test_a_message_forwarded_as_attachment_is_analysed_keeping_who_forwarded_it(client, app, analyst):
    _, headers = analyst
    token = _create_token(client, headers)
    raw = _forward_as_attachment(_ORIGINAL)

    analysis_id = _report_raw(client, token["token"], raw).get_json()["analysisId"]
    with app.app_context():
        _run_analysis(analysis_id, raw)
    report = client.get(f"/iris/results/{analysis_id}", headers=headers).get_json()

    assert report["unwrappedFromForward"] is True
    assert "ana@corp.example" in report["wrapperFrom"]
    assert report["wrapperSubject"] == "Fwd: Verifique su cuenta"
    assert report["reportChannel"] == "gmail_addon"


def test_reporting_the_same_message_twice_returns_the_existing_analysis(client, analyst):
    _, headers = analyst
    token = _create_token(client, headers)

    first = _report_raw(client, token["token"], _ORIGINAL)
    second = _report_raw(client, token["token"], _ORIGINAL)

    assert second.status_code == 200
    assert second.get_json()["isDuplicate"] is True
    assert second.get_json()["analysisId"] == first.get_json()["analysisId"]


@pytest.mark.parametrize("filename,content", [
    ("factura.pdf", b"%PDF-1.4"),
    ("sospechoso.eml", b""),
])
def test_something_that_is_not_a_message_is_rejected(client, analyst, filename, content):
    _, headers = analyst
    token = _create_token(client, headers)
    assert _report_file(client, token["token"], content, filename).status_code == 400


def test_an_oversized_message_is_rejected(client, analyst, monkeypatch):
    _, headers = analyst
    token = _create_token(client, headers)
    small = dataclasses.replace(CR.iris_config(), max_message_bytes=100)
    monkeypatch.setattr(CR, "iris_config", lambda: small)

    response = _report_raw(client, token["token"], _ORIGINAL)
    assert response.status_code == 400


def test_the_client_can_ask_how_its_report_ended(client, app, analyst):
    _, headers = analyst
    token = _create_token(client, headers)
    analysis_id = _report_raw(client, token["token"], _ORIGINAL).get_json()["analysisId"]
    with app.app_context():
        _run_analysis(analysis_id, _ORIGINAL)

    status = client.get(f"/iris/reports/{analysis_id}", headers=_token_headers(token["token"])).get_json()

    assert status["status"] == "finished" and status["verdict"] in ("Suspicious", "Phishing")
    assert set(status) == {"analysisId", "status", "verdict", "totalScore", "finishedAt"}


# --------------------------------------------------------------------------- lo que el token no permite

def test_without_a_token_or_with_a_bad_one_nothing_is_created(client, app, analyst):
    user, headers = analyst
    token = _create_token(client, headers)
    key_part = token["token"].split(".", 1)[0]

    for bad in ("", "irt_0000000000000000.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                f"{key_part}.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
        response = client.post("/iris/reports", headers={"Authorization": f"Bearer {bad}"},
                               data=_ORIGINAL.encode(), content_type="message/rfc822")
        assert response.status_code == 401
        assert response.get_json()["messageKey"] == "irisInvalidIntegrationToken"
    with app.app_context():
        assert build_repository(IrisAnalysisRepository).count_by_user(user.id) == 0


def test_a_session_token_does_not_work_on_the_report_channel(client, analyst):
    _, headers = analyst
    response = client.post("/iris/reports", headers=headers, data=_ORIGINAL.encode(), content_type="message/rfc822")
    assert response.status_code == 401


def test_an_integration_token_does_not_work_as_a_session(client, analyst):
    _, headers = analyst
    token = _create_token(client, headers)
    assert client.get("/iris/results", headers={"Authorization": f"Bearer {token['token']}"}).status_code == 401


def test_a_revoked_token_stops_working_at_once(client, analyst):
    _, headers = analyst
    token = _create_token(client, headers)
    client.delete(f"/iris/integration-tokens/{token['tokenId']}", headers=headers)

    assert _report_raw(client, token["token"], _ORIGINAL).status_code == 401


def test_an_expired_token_stops_working(client, app, analyst):
    _, headers = analyst
    token = _create_token(client, headers)
    with app.app_context():
        with UnitOfWork() as uow:
            stored = IrisIntegrationTokenRepository(uow).get_by_id(token["tokenId"])
            stored.expires_at = utcnow_naive() - timedelta(minutes=1)

    assert _report_raw(client, token["token"], _ORIGINAL).status_code == 401
    listed = client.get("/iris/integration-tokens", headers=headers).get_json()["tokens"][0]
    assert listed["status"] == "expired"


def test_losing_the_permission_disables_the_tokens(client, app, make_user, auth_headers):
    """Sin IRIS_CREATE, el token del usuario deja de poder reportar aunque no se revoque."""
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    token = _create_token(client, auth_headers(user))
    with app.app_context():
        from src.modules.users.repositories import AttributeRepository
        with UnitOfWork() as uow:
            repo = AttributeRepository(uow)
            for attribute in repo.get_by_user(user.id):
                if attribute.attribute_name == AttributeType.IRIS_CREATE.db_name:
                    repo.delete(attribute)

    assert _report_raw(client, token["token"], _ORIGINAL).status_code == 403


def test_the_status_of_an_analysis_of_another_user_does_not_exist(client, app, analyst, make_user, auth_headers):
    user, headers = analyst
    token = _create_token(client, headers)
    other = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    with app.app_context():
        with UnitOfWork() as uow:
            foreign = IrisAnalysisRepository(uow).save(IrisAnalysis(raw_headers=_ORIGINAL, user_id=other.id,
                                                                    status="finished", verdict="Phishing"))
            foreign_id = foreign.id

    assert client.get(f"/iris/reports/{foreign_id}", headers=_token_headers(token["token"])).status_code == 404


def test_the_last_use_is_recorded(client, app, analyst):
    _, headers = analyst
    token = _create_token(client, headers)
    _report_raw(client, token["token"], _ORIGINAL)

    with app.app_context():
        stored: IrisIntegrationToken = build_repository(IrisIntegrationTokenRepository).get_by_id(token["tokenId"])
    assert stored.last_used_at is not None
