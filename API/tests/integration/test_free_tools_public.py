"""Las consultas públicas de las herramientas gratuitas, sin sesión.

Cada una corre código del análisis real en memoria y no guarda nada. Se
comprueba que responden sin credenciales, que rechazan lo que no es su entrada
y que lo que devuelven son códigos para la interfaz, no frases.
"""

from __future__ import annotations

import pytest

from src.modules.features.iris.model import IrisAnalysis
from src.modules.infrastructure import UnitOfWork

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


# ── Iris: cabeceras ─────────────────────────────────────────────────────────

# Tres saltos, del más nuevo al más antiguo como los escriben los servidores: el
# segundo tramo (relay -> Google) va sin TLS después de un primero que sí lo usó.
_HEADERS = (
    "Received: from mail-sor-f41.google.com (mail-sor-f41.google.com [209.85.220.41])\n"
    "        by mx.example.com with ESMTPS id x12si1234567wrb\n"
    "        (version=TLS1_3 cipher=TLS_AES_256_GCM_SHA384 bits=256/256);\n"
    "        Thu, 09 Oct 2026 08:15:42 -0700 (PDT)\n"
    "Received: from relay.proveedor.com (relay.proveedor.com [203.0.113.25])\n"
    "        by mail-sor-f41.google.com with SMTP id abc123; Thu, 09 Oct 2026 08:15:40 -0700 (PDT)\n"
    "Received: from [192.168.1.20] (unknown [198.51.100.7])\n"
    "        by relay.proveedor.com (Postfix) with ESMTPSA id 4F2A1; Thu, 09 Oct 2026 17:15:38 +0200 (CEST)\n"
    "Authentication-Results: mx.example.com; spf=pass smtp.mailfrom=proveedor.com; "
    "dkim=pass header.d=proveedor.com; dmarc=pass header.from=proveedor.com\n"
    "DKIM-Signature: v=1; a=rsa-sha256; d=proveedor.com; s=sel1; h=from:to:subject; bh=abc=; b=def=\n"
    'From: "Proveedor" <facturas@proveedor.com>\n'
    "To: cliente@example.com\n"
    "Subject: =?UTF-8?Q?Factura_de_septiembre?=\n"
)


def _analyses_stored(app) -> int:
    """Cuántos análisis de Iris hay guardados, de cualquier usuario."""
    with app.app_context():
        with UnitOfWork() as uow:
            return uow.session.query(IrisAnalysis).count()


def test_anyone_can_read_the_headers_of_an_email_without_a_session(client, app):
    stored_before = _analyses_stored(app)

    response = client.post("/iris/tools/headers", json={"headers": _HEADERS})

    assert response.status_code == 200
    body = response.get_json()
    assert body["sender"] == '"Proveedor" <facturas@proveedor.com>'
    assert body["subject"] == "Factura de septiembre"
    assert body["fromDomain"] == "proveedor.com"
    assert {check["check"]: check["verdict"] for check in body["auth"]} == {
        "spf": "pass", "dkim": "pass", "dmarc": "pass", "alignment": "pass",
    }
    assert _analyses_stored(app) == stored_before


def test_the_route_comes_oldest_first_with_the_keys_the_path_component_reads(client):
    path = client.post("/iris/tools/headers", json={"headers": _HEADERS}).get_json()["path"]

    assert path["hopsCount"] == 3
    assert [hop["by"] for hop in path["hops"]] == ["relay.proveedor.com", "mail-sor-f41.google.com", "mx.example.com"]
    assert path["hops"][1]["fromAddress"] == "relay.proveedor.com"
    assert path["hops"][1]["tls"] is False
    assert "tls_downgrade" in path["transitions"][0]["reasons"]


def test_a_sender_that_fails_dmarc_is_reported_as_such(client):
    spoofed = _HEADERS.replace("spf=pass", "spf=fail").replace("dkim=pass", "dkim=fail").replace("dmarc=pass", "dmarc=fail")

    auth = client.post("/iris/tools/headers", json={"headers": spoofed}).get_json()["auth"]

    assert {check["check"]: check["verdict"] for check in auth}["dmarc"] == "fail"


def test_text_without_enough_headers_is_rejected(client):
    assert client.post("/iris/tools/headers", json={"headers": "esto no es un correo, es una frase"}).status_code == 400


@pytest.mark.parametrize("payload", [{}, {"headers": "corto"}, {"headers": "X-Relleno: " + "a" * 65536}])
def test_missing_short_or_oversized_headers_are_rejected_by_the_schema(client, payload):
    assert client.post("/iris/tools/headers", json=payload).status_code == 422
