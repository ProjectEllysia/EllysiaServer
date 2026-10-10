"""Las consultas públicas de las herramientas gratuitas, sin sesión.

Cada una corre código del análisis real en memoria y no guarda nada. Se
comprueba que responden sin credenciales, que rechazan lo que no es su entrada
y que lo que devuelven son códigos para la interfaz, no frases.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ── Iris: dominios engañosos ────────────────────────────────────────────────


def test_anyone_can_check_a_domain_without_a_session(client):
    response = client.get("/iris/tools/domain?domain=paypal.com")

    assert response.status_code == 200
    body = response.get_json()
    assert body["domain"] == "paypal.com"
    assert body["ownBrand"] == "paypal"
    assert body["isSuspicious"] is False
    assert body["findings"] == []


def test_a_cyrillic_homograph_of_a_brand_is_flagged_and_read_back_in_unicode(client):
    body = client.get("/iris/tools/domain", query_string={"domain": "pаypal.com"}).get_json()

    assert body["domain"] == "xn--pypal-4ve.com"
    assert body["unicodeDomain"] == "pаypal.com"
    assert body["isSuspicious"] is True
    assert body["findings"][0]["type"] == "idn_homograph"
    assert body["findings"][0]["brand"] == "paypal"
    assert body["findings"][0]["scripts"] == ["CYRILLIC", "LATIN"]


def test_a_brand_used_as_a_subdomain_of_a_url_is_flagged(client):
    body = client.get("/iris/tools/domain", query_string={
        "domain": "https://github.com.sessions-security.com/login?next=1",
    }).get_json()

    assert body["domain"] == "github.com.sessions-security.com"
    assert body["registrableDomain"] == "sessions-security.com"
    assert body["ownBrand"] is None
    assert {"type": "brand_in_subdomain", "brand": "github"}.items() <= body["findings"][0].items()


def test_an_email_address_is_read_as_its_domain(client):
    body = client.get("/iris/tools/domain", query_string={"domain": "soporte@paypa1.com"}).get_json()

    assert body["domain"] == "paypa1.com"
    assert body["findings"][0]["type"] == "homoglyph"


def test_a_legitimate_internationalised_domain_is_not_flagged(client):
    body = client.get("/iris/tools/domain", query_string={"domain": "münchen.de"}).get_json()

    assert body["domain"] == "xn--mnchen-3ya.de"
    assert body["isSuspicious"] is False


def test_the_answer_carries_codes_not_the_rule_sentences(client):
    body = client.get("/iris/tools/domain", query_string={"domain": "paypal-security.com"}).get_json()

    assert "recommendation" not in str(body)
    assert {finding["type"] for finding in body["findings"]} == {"cousin", "brand_action_combo"}


@pytest.mark.parametrize("domain", ["localhost", "203.0.113.7", "a..b", "-a.com", "http://"])
def test_what_is_not_a_domain_name_is_rejected(client, domain):
    assert client.get("/iris/tools/domain", query_string={"domain": domain}).status_code == 400


@pytest.mark.parametrize("query", ["", "?domain=", f"?domain={'a' * 301}.com"])
def test_a_missing_or_overlong_domain_is_rejected_by_the_schema(client, query):
    assert client.get(f"/iris/tools/domain{query}").status_code == 422
