"""El catálogo del RGPD: cada artículo citado existe en la fuente guardada y se puede cruzar con NIS2."""

import re

import pytest

from src.modules.features.eunomia.services.catalog import CATALOG_ROOT, load_version
from src.modules.features.eunomia.services.crosswalks import suggestions

pytestmark = pytest.mark.unit

_SOURCE = CATALOG_ROOT / "rgpd" / "fuentes" / "reglamento-2016-679.es.txt"


@pytest.fixture(scope="module")
def rgpd():
    version = load_version("rgpd", "2016-679")
    assert version is not None
    return version


def test_it_is_a_full_text_catalog_with_its_source_license(rgpd):
    assert rgpd.license_mode == "full_text"
    assert "2011/833" in rgpd.sources[0].license


def test_every_article_cited_exists_in_the_saved_source(rgpd):
    source = _SOURCE.read_text(encoding="utf-8")
    articles = {int(match) for match in re.findall(r"^Artículo (\d+)$", source, re.M)}
    cited = {int(node.identifier.split(".")[1]) for node in rgpd.nodes if node.identifier.startswith("art.")}

    assert cited <= articles
    assert cited >= {5, 6, 12, 13, 28, 30, 32, 33, 34, 35, 37}


def test_the_official_text_of_each_article_is_in_the_node(rgpd):
    assert "72 horas" in rgpd.node("rgpd:art.33").official_text
    assert "un mes" in rgpd.node("rgpd:art.12").official_text
    assert "250 personas" in rgpd.node("rgpd:art.30").official_text


def test_every_assessable_article_says_what_to_do_and_what_to_keep(rgpd):
    incomplete = [n.identifier for n in rgpd.assessable_nodes() if not (n.description and n.actions and n.evidence)]
    assert incomplete == []


def test_the_obligations_that_are_registers_are_marked(rgpd):
    registers = {n.identifier: n.register for n in rgpd.nodes if n.register}

    assert registers["art.30"] == "processing_activities"
    assert registers["art.33"] == "breaches"
    assert registers["art.15"] == "rights_requests"


def test_a_user_with_nis2_sees_which_part_of_article_32_is_covered():
    adopted = {"rgpd": "2016-679", "nis2": "2022-2555"}

    found = suggestions("rgpd", "2016-679", "art.32", adopted)

    assert {s.identifier for s in found} >= {"RE.9", "RE.11.1", "RE.4.2"}


def test_the_breach_notification_points_to_the_nis2_incident_deadlines():
    found = suggestions("rgpd", "2016-679", "art.33", {"rgpd": "2016-679", "nis2": "2022-2555"})

    assert "23.4.b" in {s.identifier for s in found}
