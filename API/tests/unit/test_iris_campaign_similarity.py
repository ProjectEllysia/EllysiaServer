"""Parecido determinista entre análisis: qué hace falta para ser la misma campaña.

Son funciones puras (``services/campaigns.py``): huellas de asunto y de
plantilla, marcas suplantadas y la puntuación que decide si dos análisis van
juntos. La agrupación contra la base de datos se prueba en
``tests/integration/test_iris_campaigns.py``.
"""

from __future__ import annotations

import pytest

from src.modules.features.iris.model import CampaignSignal
from src.modules.features.iris.services.campaigns import (
    CampaignFeatures,
    build_features,
    extract_brands,
    fingerprint_subject,
    fingerprint_template,
    normalize_subject,
    score_similarity,
)

pytestmark = pytest.mark.unit

_THRESHOLD = 5.0


def test_the_subject_loses_numbers_reply_prefixes_and_case():
    assert normalize_subject("RE: Fwd: Factura 4411 pendiente!!") == "factura # pendiente"
    assert fingerprint_subject("Factura 4411 pendiente") == fingerprint_subject("RE: FACTURA 9 pendiente")


def test_a_short_subject_does_not_fingerprint():
    assert fingerprint_subject("Hola") is None
    assert fingerprint_subject("") is None
    assert fingerprint_subject(None) is None


def test_the_template_is_the_html_skeleton_not_its_text():
    first = "<table><tr><td><p>Hola Ana</p><a href='x'>pagar 10</a></td></tr></table>" * 3
    second = "<table><tr><td><p>Hola Luis</p><a href='y'>pagar 99</a></td></tr></table>" * 3
    other = "<div><span>" * 12

    assert fingerprint_template(first, "") == fingerprint_template(second, "")
    assert fingerprint_template(first, "") != fingerprint_template(other, "")


def test_a_short_body_is_no_template():
    assert fingerprint_template("<p>Hola</p>", "Hola") is None
    assert fingerprint_template("", "") is None


def test_brands_come_only_from_rules_that_penalised():
    brands = extract_brands([
        (-15.0, {"findings": [{"brand": "PayPal"}, {"brand": "paypal"}]}),
        (-6.0, {"findings": [{"type": "brand_impersonation", "brands": ["Microsoft"]}]}),
        (0.0, {"brand": "correos"}),
    ])

    assert brands == ["microsoft", "paypal"]


def test_free_mail_domains_are_not_a_campaign_signal():
    features = build_features(None, None, None, [("domain", "gmail.com"), ("domain", "evil.example")])

    assert features.domains == frozenset({"evil.example"})


@pytest.mark.parametrize("shared", [
    CampaignFeatures(urls=frozenset({"http://evil.example/pay"})),
    CampaignFeatures(hashes=frozenset({"ab" * 32})),
])
def test_a_shared_url_or_attachment_is_enough(shared):
    assert score_similarity(shared, shared).score >= _THRESHOLD


def test_the_same_subject_alone_is_not_a_campaign():
    features = CampaignFeatures(subject_fingerprint="s")

    assert score_similarity(features, features).score < _THRESHOLD


def test_subject_plus_a_domain_is_a_campaign():
    first = CampaignFeatures(subject_fingerprint="s", domains=frozenset({"evil.example"}))
    second = CampaignFeatures(subject_fingerprint="s", domains=frozenset({"evil.example", "other.example"}))

    match = score_similarity(first, second)

    assert match.score >= _THRESHOLD
    assert match.signals == (CampaignSignal.DOMAIN, CampaignSignal.SUBJECT)


def test_many_shared_domains_count_once():
    """Dos campañas contra la misma marca enlazan a su web real: no suma por enlace."""
    domains = frozenset({"paypal.com", "paypalobjects.com", "w3.org"})
    first = CampaignFeatures(domains=domains, brands=frozenset({"paypal"}))

    assert score_similarity(first, first).score < _THRESHOLD


def test_similarity_is_symmetric_and_zero_without_overlap():
    first = CampaignFeatures(subject_fingerprint="a", urls=frozenset({"u1"}))
    second = CampaignFeatures(subject_fingerprint="b", urls=frozenset({"u2"}))

    assert score_similarity(first, second).score == 0.0
    assert score_similarity(first, second) == score_similarity(second, first)
