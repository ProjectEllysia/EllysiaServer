"""Los avisos por correo de los plazos de los registros: una vez por ficha y plazo."""

from datetime import timedelta

import pytest

from src.modules.features.eunomia.services import deadline_notices
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

_FUTURE = utcnow_naive() + timedelta(days=30)
_URL = "/eunomia/registers/incidentes-y-brechas"


@pytest.fixture()
def owner(make_user, make_subscription):
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=_FUTURE)
    return user


@pytest.fixture()
def mails(monkeypatch):
    sent = []

    class Mailer:
        def send(self, message):
            sent.append(message)

    monkeypatch.setattr(deadline_notices, "build_mailer", lambda name: Mailer())
    return sent


def _incident(client, headers, aware_hours_ago, **extra):
    aware = (utcnow_naive() - timedelta(hours=aware_hours_ago)).strftime("%Y-%m-%dT%H:%M")
    values = {"name": "Ransomware", "aware_at": aware, "description": "x", "nis2_significant": "yes", **extra}
    return client.post(f"{_URL}/records", headers=headers, json={"values": values}).get_json()


def test_a_deadline_close_to_expiring_sends_one_email_only(app, client, owner, auth_headers, mails):
    _incident(client, auth_headers(owner), aware_hours_ago=18)   # alerta de 24 h: quedan 6

    with app.app_context():
        first = deadline_notices.send_deadline_notices()
        second = deadline_notices.send_deadline_notices()

    assert (first, second) == (1, 0)
    assert "Alerta temprana" in mails[0].text_body and "Ransomware" in mails[0].text_body


def test_an_overdue_deadline_is_notified_once(app, client, owner, auth_headers, mails):
    _incident(client, auth_headers(owner), aware_hours_ago=30)

    with app.app_context():
        assert deadline_notices.send_deadline_notices() == 1
        assert deadline_notices.send_deadline_notices() == 0

    assert "(vencido)" in mails[0].text_body


def test_a_deadline_far_from_expiring_is_not_notified(app, client, owner, auth_headers, mails):
    _incident(client, auth_headers(owner), aware_hours_ago=1)

    with app.app_context():
        assert deadline_notices.send_deadline_notices() == 0


def test_a_deadline_already_met_is_not_notified(app, client, owner, auth_headers, mails):
    sent = (utcnow_naive() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    _incident(client, auth_headers(owner), aware_hours_ago=30, nis2_early_sent_at=sent,
              nis2_notification_sent_at=sent, nis2_final_sent_at=sent)

    with app.app_context():
        assert deadline_notices.send_deadline_notices() == 0


def test_an_archived_record_is_not_notified(app, client, owner, auth_headers, mails):
    headers = auth_headers(owner)
    record = _incident(client, headers, aware_hours_ago=30)
    client.post(f"{_URL}/records/{record['id']}/archive", headers=headers)

    with app.app_context():
        assert deadline_notices.send_deadline_notices() == 0


def test_a_failed_send_is_retried_on_the_next_pass(app, client, owner, auth_headers, monkeypatch):
    _incident(client, auth_headers(owner), aware_hours_ago=30)
    state = {"fail": True, "sent": 0}

    class Mailer:
        def send(self, message):
            if state["fail"]:
                raise RuntimeError("smtp caído")
            state["sent"] += 1

    monkeypatch.setattr(deadline_notices, "build_mailer", lambda name: Mailer())

    with app.app_context():
        assert deadline_notices.send_deadline_notices() == 0
        state["fail"] = False
        assert deadline_notices.send_deadline_notices() == 1
