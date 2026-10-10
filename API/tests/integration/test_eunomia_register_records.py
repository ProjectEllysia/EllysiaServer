"""Registros: fichas validadas contra su definición, con historial, plazos al leer y exportación."""

import io
from datetime import timedelta

import pytest

from src.modules.features.eunomia.managers import registers as registers_manager
from src.modules.features.eunomia.services.registers import parse_register
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/registers/demo"
_DEFINITION = {
    "key": "demo", "version": "1", "title": "Registro de prueba", "summary": "Para probar.", "titleField": "name",
    "controls": {"nis2": ["23.1"]},
    "fields": [
        {"key": "name", "label": "Nombre", "type": "text", "required": True},
        {"key": "kind", "label": "Tipo", "type": "select",
         "options": [{"value": "a", "label": "Tipo A"}, {"value": "b", "label": "Tipo B"}]},
        {"key": "seen_at", "label": "Constancia", "type": "datetime"},
        {"key": "sent_at", "label": "Enviado", "type": "datetime"},
    ],
    "deadlines": [{"key": "early", "label": "Alerta", "from": "seen_at", "hours": 24, "doneField": "sent_at"}],
    "examples": [{"name": "Ejemplo uno", "kind": "a"}, {"name": "Ejemplo dos", "kind": "b"}],
}


@pytest.fixture(autouse=True)
def demo_register(monkeypatch):
    register = parse_register(_DEFINITION)
    monkeypatch.setattr(registers_manager, "get_register", lambda key: register if key == "demo" else None)
    monkeypatch.setattr(registers_manager, "load_registers", lambda: (register,))
    return register


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


def _create(client, headers, **values):
    return client.post(f"{_URL}/records", headers=headers, json={"values": {"name": "Ficha", **values}})


def test_a_record_is_created_and_listed_with_its_deadlines(client, owner, auth_headers):
    headers = auth_headers(owner)
    seen = (utcnow_naive() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")

    created = _create(client, headers, kind="a", seen_at=seen)
    body = client.get(_URL, headers=headers).get_json()

    assert created.status_code == 201, created.get_json()
    assert [r["title"] for r in body["records"]] == ["Ficha"]
    deadline = body["records"][0]["deadlines"][0]
    assert deadline["key"] == "early" and deadline["status"] == "upcoming"
    assert body["register"]["fields"][1]["options"][0] == {"value": "a", "label": "Tipo A"}


def test_a_record_that_does_not_meet_the_definition_is_rejected(client, owner, auth_headers):
    headers = auth_headers(owner)

    missing = client.post(f"{_URL}/records", headers=headers, json={"values": {"kind": "a"}})
    bad_option = _create(client, headers, kind="z")

    assert missing.status_code == 400 and missing.get_json()["messageKey"] == "recordInvalid"
    assert bad_option.status_code == 400


def test_an_unknown_register_is_a_404(client, owner, auth_headers):
    assert client.get("/eunomia/registers/no-existe", headers=auth_headers(owner)).status_code == 404


def test_editing_records_the_change_and_detects_a_concurrent_edit(client, owner, auth_headers):
    headers = auth_headers(owner)
    record = _create(client, headers, kind="a").get_json()
    url = f"{_URL}/records/{record['id']}"

    saved = client.put(url, headers=headers, json={"values": {"name": "Ficha", "kind": "b"},
                                                   "updatedAt": record["updatedAt"]})
    stale = client.put(url, headers=headers, json={"values": {"name": "Otra"}, "updatedAt": record["updatedAt"]})
    history = client.get(f"{url}/history", headers=headers).get_json()["events"]

    assert saved.status_code == 200 and saved.get_json()["values"]["kind"] == "b"
    assert stale.status_code == 409 and stale.get_json()["messageKey"] == "recordConflict"
    assert history[0]["changes"]["kind"] == {"from": "a", "to": "b"}


def test_an_archived_record_leaves_the_register_but_keeps_its_history(client, owner, auth_headers):
    headers = auth_headers(owner)
    record = _create(client, headers).get_json()
    url = f"{_URL}/records/{record['id']}"

    client.post(f"{url}/archive", headers=headers)

    assert client.get(_URL, headers=headers).get_json()["records"] == []
    assert len(client.get(f"{_URL}?includeArchived=true", headers=headers).get_json()["records"]) == 1
    assert client.get(f"{url}/history", headers=headers).get_json()["events"][0]["changes"] == {
        "isArchived": {"from": False, "to": True}}
    client.post(f"{url}/restore", headers=headers)
    assert len(client.get(_URL, headers=headers).get_json()["records"]) == 1


def test_the_example_records_are_created_on_request(client, owner, auth_headers):
    headers = auth_headers(owner)

    created = client.post(f"{_URL}/examples", headers=headers)

    assert [r["title"] for r in created.get_json()["records"]] == ["Ejemplo uno", "Ejemplo dos"]


def test_the_register_exports_to_csv_and_pdf(client, owner, auth_headers):
    headers = auth_headers(owner)
    _create(client, headers, name="Con, coma", kind="a")

    csv_response = client.get(f"{_URL}/export?format=csv", headers=headers)
    pdf_response = client.get(f"{_URL}/export?format=pdf", headers=headers)

    text = csv_response.data.decode("utf-8-sig")
    assert text.splitlines()[0] == "Nombre,Tipo,Constancia,Enviado"
    assert '"Con, coma",Tipo A' in text
    assert pdf_response.data.startswith(b"%PDF")


def test_a_member_edits_the_records_of_the_owner(app, client, owner, regular_user, auth_headers):
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    org = client.post("/organizations", headers=auth_headers(owner), json={"name": "Acme"}).get_json()
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(organization_id=org["id"], user_id=regular_user.id, member_role="member"))
            uow.session.flush()
    record = _create(client, auth_headers(owner)).get_json()

    seen = client.get(_URL, headers=auth_headers(regular_user)).get_json()["records"]
    edited = client.put(f"{_URL}/records/{record['id']}", headers=auth_headers(regular_user),
                        json={"values": {"name": "Cambiada"}, "updatedAt": record["updatedAt"]})

    assert [r["id"] for r in seen] == [record["id"]]
    assert edited.status_code == 200


def test_another_account_cannot_touch_the_record(client, owner, make_user, auth_headers):
    record = _create(client, auth_headers(owner)).get_json()
    stranger = auth_headers(make_user())

    assert client.get(_URL, headers=stranger).get_json()["records"] == []
    assert client.post(f"{_URL}/records/{record['id']}/archive", headers=stranger).status_code == 404


def test_a_register_with_records_is_automatic_evidence_of_its_controls(client, owner, auth_headers, demo_register,
                                                                       monkeypatch):
    from src.modules.features.eunomia.services import register_evidence
    from src.modules.features.eunomia.services.providers import EvidenceProviderRegistry
    from src.modules.features.eunomia.services.register_evidence import register_providers

    monkeypatch.setattr(register_evidence, "load_registers", lambda: (demo_register,))

    headers = auth_headers(owner)
    client.post("/eunomia/adoptions", headers=headers, json={"frameworkKey": "nis2"})
    register_providers()
    try:
        empty = client.get("/eunomia/adoptions/nis2/automatic-evidence/23.1", headers=headers).get_json()["evidence"]
        _create(client, headers)
        filled = client.get("/eunomia/adoptions/nis2/automatic-evidence/23.1", headers=headers).get_json()["evidence"]
    finally:
        EvidenceProviderRegistry._providers.pop("eunomia.register.demo", None)

    assert [e["status"] for e in empty if e["providerKey"] == "eunomia.register.demo"] == ["missing"]
    assert [e["status"] for e in filled if e["providerKey"] == "eunomia.register.demo"] == ["ok"]
