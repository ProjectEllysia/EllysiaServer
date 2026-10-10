"""Aegis aporta a Eunomia la actividad de concienciación, solo en agregado."""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/adoptions/nis2/automatic-evidence/RE.8.1"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def adopted(client, owner, auth_headers):
    client.post("/eunomia/adoptions", headers=auth_headers(owner), json={"frameworkKey": "nis2"})
    return owner


def _campaign(app, user_id, *, recipients=4, completed=3, correct=2, launched_days_ago=10):
    from src.modules.features.aegis.model import (
        AegisDocument, Campaign, CampaignAnswer, CampaignRecipient, DistributionList, Topic)
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            session = uow.session
            topic = Topic(title=f"t{user_id}-{launched_days_ago}")
            session.add(topic)
            session.flush()
            document = AegisDocument(document_type="aegis", filename="x", format="md", status="done", title="t",
                                     user_id=user_id, topic_id=topic.id)
            lst = DistributionList(user_id=user_id, name="l")
            session.add_all([document, lst])
            session.flush()
            campaign = Campaign(user_id=user_id, document_id=document.id, list_id=lst.id, name="c",
                                status="sent", launched_at=utcnow_naive() - timedelta(days=launched_days_ago))
            session.add(campaign)
            session.flush()
            for number in range(recipients):
                done = number < completed
                recipient = CampaignRecipient(
                    campaign_id=campaign.id, recipient_email=f"p{number}@example.test", token=f"tok-{user_id}-{launched_days_ago}-{number}",
                    status="completed" if done else "sent",
                    completed_at=utcnow_naive() if done else None, score=1 if done else None)
                session.add(recipient)
                session.flush()
                if done:
                    session.add(CampaignAnswer(campaign_recipient_id=recipient.id, question_position=0,
                                               selected_index=0, is_correct=number < correct))
            session.flush()


def _evidence(client, headers):
    return {item["title"]: item for item in client.get(_URL, headers=headers).get_json()["evidence"]
            if item["providerKey"] == "aegis.awareness"}


def test_without_campaigns_the_control_says_there_is_no_data(client, adopted, auth_headers):
    assert [i["status"] for i in _evidence(client, auth_headers(adopted)).values()] == ["missing"]


def test_the_figures_match_the_campaigns(app, client, adopted, auth_headers):
    _campaign(app, adopted.id, recipients=4, completed=3, correct=2)

    found = _evidence(client, auth_headers(adopted))

    assert "1 campaña" in found["Campañas en los últimos 12 meses"]["summary"]
    assert "75 %" in found["Participación"]["summary"] and found["Participación"]["status"] == "ok"
    assert "67 %" in found["Acierto"]["summary"]


def test_low_participation_is_a_warning(app, client, adopted, auth_headers):
    _campaign(app, adopted.id, recipients=10, completed=2, correct=2)

    assert _evidence(client, auth_headers(adopted))["Participación"]["status"] == "warning"


def test_campaigns_older_than_a_year_do_not_count(app, client, adopted, auth_headers):
    _campaign(app, adopted.id, launched_days_ago=500)

    assert [i["status"] for i in _evidence(client, auth_headers(adopted)).values()] == ["missing"]


def test_no_individual_recipient_data_is_exposed(app, client, adopted, auth_headers):
    _campaign(app, adopted.id)

    body = client.get(_URL, headers=auth_headers(adopted)).get_data(as_text=True)

    assert "example.test" not in body and "tok-" not in body


def test_only_the_campaigns_of_the_effective_owner_count(app, client, adopted, make_user, auth_headers):
    _campaign(app, make_user().id)

    assert [i["status"] for i in _evidence(client, auth_headers(adopted)).values()] == ["missing"]
