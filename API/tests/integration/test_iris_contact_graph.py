"""Grafo de comunicación: quién escribe a quién, contacto habitual y retención.

Ejecuta el catálogo real como el worker. Comprueba que los mensajes legítimos
de un remitente lo hacen habitual, que otro remitente que usa su nombre queda
señalado en el informe sin cambiar el veredicto, que el grafo es de un solo
usuario, que la retención lo purga y que el usuario puede olvidarlo.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest

from src.modules.features.iris.managers.analysis import _run_analysis
from src.modules.features.iris.model import IrisAnalysis, IrisCommunicationEdge
from src.modules.features.iris.repositories import IrisAnalysisRepository
from src.modules.features.iris.services import retention as retention_mod
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import utcnow_naive
from src.modules.users.services.permissions import AttributeType

pytestmark = pytest.mark.integration

_IRIS_ATTRIBUTES = [attribute.db_name for attribute in (
    AttributeType.IRIS_READ, AttributeType.IRIS_CREATE,
    AttributeType.IRIS_UPDATE, AttributeType.IRIS_DELETE,
)]


def _message(from_header: str, number: int) -> str:
    return (
        f"From: {from_header}\r\n"
        "To: ana@corp.example\r\n"
        f"Subject: Reunion semanal {number}\r\n"
        "Date: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
        f"Message-ID: <m{number}@example>\r\n\r\n"
        f"Hola Ana, te paso el orden del dia de la reunion {number}.\r\n"
    )


def _analyze(app, user_id: int, raw: str, verdict: str | None = None) -> int:
    """Analiza ``raw``; con ``verdict`` se fuerza el veredicto de la política."""
    with app.app_context():
        with UnitOfWork() as uow:
            analysis = IrisAnalysis(raw_headers=raw, user_id=user_id, status="pending",
                                    content_sha256=f"sha-{hash(raw)}")
            IrisAnalysisRepository(uow).save(analysis)
            analysis_id = analysis.id
        if verdict is None:
            _run_analysis(analysis_id, raw)
        else:
            with patch("src.modules.features.iris.services.scoring.ScoringPolicy.verdict_for",
                       return_value=verdict):
                _run_analysis(analysis_id, raw)
    return analysis_id


def _make_habitual(app, user_id: int, count: int = 3) -> None:
    for number in range(count):
        _analyze(app, user_id, _message('"Juan Pérez" <juan.perez@empresa.example>', number), "Legitimate")


@pytest.fixture
def analyst(make_user, auth_headers):
    user = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    return user, auth_headers(user)


def test_legitimate_messages_make_a_habitual_contact(client, app, analyst):
    user, headers = analyst
    _make_habitual(app, user.id)

    graph = client.get("/iris/graph", headers=headers).get_json()

    juan = next(sender for sender in graph["senders"] if sender["address"] == "juan.perez@empresa.example")
    assert juan["isHabitual"] and juan["legitimateCount"] == 3
    assert graph["edges"][0]["recipient"] == "ana@corp.example"


def test_a_new_sender_using_a_habitual_name_is_flagged_without_changing_the_verdict(client, app, analyst):
    user, headers = analyst
    _make_habitual(app, user.id)
    impostor = _analyze(app, user.id, _message('"Juan Perez" <juan.perez.ceo@gmail.com>', 9))

    report = client.get(f"/iris/results/{impostor}", headers=headers).get_json()

    assert report["contactDeviation"]["kind"] == "display_name_reuse"
    assert report["contactDeviation"]["habitualAddress"] == "juan.perez@empresa.example"
    with app.app_context():
        from src.modules.features.iris.managers.analysis import IrisManager
        with UnitOfWork():
            raw = build_repository(IrisAnalysisRepository).get_by_id(impostor).raw_headers
        assert IrisManager.evaluate_raw(raw)["verdict"] == report["verdict"]


def test_the_same_address_from_another_domain_is_flagged(client, app, analyst):
    user, headers = analyst
    _make_habitual(app, user.id)
    lookalike = _analyze(app, user.id, _message("<juan.perez@empresa-mail.example>", 9))

    report = client.get(f"/iris/results/{lookalike}", headers=headers).get_json()

    assert report["contactDeviation"]["kind"] == "address_domain_change"


def test_suspicious_messages_never_make_a_sender_habitual(client, app, analyst):
    user, headers = analyst
    for number in range(4):
        _analyze(app, user.id, _message('"Juan Pérez" <juan.perez@empresa.example>', number), "Suspicious")
    impostor = _analyze(app, user.id, _message('"Juan Perez" <otro@gmail.com>', 9))

    assert client.get(f"/iris/results/{impostor}", headers=headers).get_json()["contactDeviation"] is None


def test_reanalysing_a_message_does_not_count_it_twice(app, analyst):
    user, _ = analyst
    raw = _message('"Juan Pérez" <juan.perez@empresa.example>', 1)
    _analyze(app, user.id, raw, "Legitimate")
    _analyze(app, user.id, raw, "Legitimate")

    with app.app_context():
        edge = build_repository(IrisAnalysisRepository)._session.query(IrisCommunicationEdge).one()
        assert edge.message_count == 1


def test_the_graph_belongs_to_one_user(client, app, analyst, make_user, auth_headers):
    user, _ = analyst
    other = make_user(role="role_user", attributes=_IRIS_ATTRIBUTES)
    _make_habitual(app, user.id)
    impostor = _analyze(app, other.id, _message('"Juan Perez" <juan.perez.ceo@gmail.com>', 9))

    other_headers = auth_headers(other)
    assert client.get("/iris/graph", headers=other_headers).get_json()["senders"][0]["address"] \
        == "juan.perez.ceo@gmail.com"
    assert client.get(f"/iris/results/{impostor}", headers=other_headers).get_json()["contactDeviation"] is None


def test_retention_forgets_old_edges(app, analyst):
    user, _ = analyst
    _make_habitual(app, user.id)
    with app.app_context():
        with UnitOfWork() as uow:
            for edge in uow.session.query(IrisCommunicationEdge).all():
                edge.last_seen_at = utcnow_naive() - timedelta(days=365)

        report = retention_mod.run_retention()

    assert report["deletedCommunicationEdges"] == 1


def test_the_user_can_forget_the_whole_graph(client, app, analyst):
    user, headers = analyst
    _make_habitual(app, user.id)

    response = client.delete("/iris/graph", headers=headers)

    assert response.status_code == 200 and response.get_json()["deletedEdges"] == 1
    assert client.get("/iris/graph", headers=headers).get_json()["senders"] == []
