"""El catálogo de NIS2 que viaja con Eunomia recoge la directiva y el anexo del reglamento."""

import json
from pathlib import Path

import pytest

from src.modules.features.eunomia.services.catalog import CATALOG_ROOT, load_version

pytestmark = pytest.mark.unit

_DRAFT = CATALOG_ROOT / "nis2" / "borrador" / "nis2-estructura.json"


@pytest.fixture(scope="module")
def nis2():
    version = load_version("nis2", "2022-2555")
    assert version is not None
    return version


def test_the_identifiers_lybra_maps_to_still_exist(nis2):
    """Los mapeos de Lybra apuntan a estos códigos; si desaparece uno, su informe pierde el control."""
    lybra_identifiers = json.loads(_DRAFT.read_text(encoding="utf-8"))["lybraIdentifiers"]["ids"]

    missing = [identifier for identifier in lybra_identifiers if nis2.node(f"nis2:{identifier}") is None]

    assert missing == []


def test_all_ten_letters_of_article_21_2_exist(nis2):
    letters = [f"nis2:21.2.{letter}" for letter in "abcdefghij"]

    assert all(nis2.node(code) is not None for code in letters)
    assert [node.code for node in nis2.children("nis2:21.2")] == letters


def test_every_letter_has_requirements_underneath(nis2):
    for letter in "abcdefghij":
        code = f"nis2:21.2.{letter}"
        below = [node for node in nis2.walk() if code in {a.code for a in nis2.ancestors(node.code)}]
        assert any(node.is_assessable for node in below), f"la letra {letter} no tiene requisitos"


def test_every_section_of_the_annex_is_represented(nis2):
    draft = json.loads(_DRAFT.read_text(encoding="utf-8"))
    for section in draft["implementingRegulation"]["annex"]:
        sid = section["id"]
        represented = nis2.node(f"nis2:RE.{sid}") is not None or any(
            nis2.node(f"nis2:RE.{sub['id']}") is not None for sub in section["subsections"]
        )
        assert represented, f"falta la sección {sid} del anexo"


def test_every_point_of_the_annex_ends_up_in_a_node(nis2):
    """Ningún punto del anexo se pierde: el texto de cada uno está en el nodo que lo contiene."""
    draft = json.loads(_DRAFT.read_text(encoding="utf-8"))
    corpus = "\n".join(node.official_text for node in nis2.nodes)
    for section in draft["implementingRegulation"]["annex"]:
        points = list(section.get("points", []))
        for sub in section["subsections"]:
            points.extend(sub["points"])
        for point in points:
            assert point["text"] in corpus, f"falta el punto {point['id']}"


def test_articles_20_and_23_are_there_with_their_deadlines(nis2):
    assert nis2.node("nis2:20.1") is not None and nis2.node("nis2:20.2") is not None
    assert "veinticuatro horas" in nis2.node("nis2:23.4.a").official_text
    assert "setenta y dos horas" in nis2.node("nis2:23.4.b").official_text
    assert "un mes" in nis2.node("nis2:23.4.d").official_text


def test_every_node_cites_where_it_comes_from(nis2):
    assert [node.identifier for node in nis2.nodes if not node.source] == []


def test_a_node_with_requirements_is_not_itself_assessable_by_accident(nis2):
    for node in nis2.nodes:
        if nis2.children(node.code):
            assert node.is_assessable is False, node.identifier


# ── qué hay que hacer y qué hay que evidenciar ─────────────────────────────

#: Lo que la SPA puede pintar sin desbordar una tarjeta o una fila de lista de comprobación.
MAX_DESCRIPTION = 500
MAX_LIST_ITEM = 240


def test_every_assessable_requirement_says_what_to_do_and_what_to_keep(nis2):
    incomplete = [
        node.identifier for node in nis2.assessable_nodes()
        if not (node.description.strip() and node.actions and node.evidence)
    ]
    assert incomplete == []


def test_no_field_is_too_long_to_be_shown(nis2):
    too_long = [
        node.identifier for node in nis2.nodes
        if len(node.description) > MAX_DESCRIPTION
        or any(len(item) > MAX_LIST_ITEM for item in (*node.actions, *node.evidence))
    ]
    assert too_long == []


def test_evidence_is_a_list_of_short_items_not_a_paragraph(nis2):
    assert all(len(node.evidence) >= 2 for node in nis2.assessable_nodes() if node.identifier.startswith("RE."))


def test_the_plain_wording_is_not_a_copy_of_the_official_text(nis2):
    copied = [
        node.identifier for node in nis2.assessable_nodes()
        if node.description and node.description in node.official_text
    ]
    assert copied == []
