"""Qué controles exige el ENS según la categoría del sistema, contra filas reales del anexo II."""

import re
from datetime import date

import pytest

from src.modules.features.eunomia.services.applicability import (
    ALTERNATIVE,
    CATEGORIES,
    NOT_REQUIRED,
    OPTIONAL,
    REQUIRED,
    applicability,
    categories_of,
)
from src.modules.features.eunomia.services.assessments import ControlState, summarize
from src.modules.features.eunomia.services.catalog import load_version

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def ens():
    return load_version("ens", "rd-311-2022")


def test_only_the_ens_distinguishes_system_categories():
    assert categories_of(load_version("ens", "rd-311-2022")) == CATEGORIES
    assert categories_of(load_version("nis2", "2022-2555")) == ()


def test_without_a_category_everything_is_required(ens):
    assert applicability(ens, None) == {}
    assert applicability(load_version("nis2", "2022-2555"), "basic") == {}


def test_a_measure_brings_the_reinforcements_its_column_cites(ens):
    # mp.info.3: «aplica» en básica, «+ R1 + R2 + R3» en media, «+ R1 + R2 + R3 + R4» en alta.
    expected = {
        "basic": [REQUIRED, NOT_REQUIRED, NOT_REQUIRED, NOT_REQUIRED, NOT_REQUIRED],
        "medium": [REQUIRED, REQUIRED, REQUIRED, REQUIRED, NOT_REQUIRED],
        "high": [REQUIRED, REQUIRED, REQUIRED, REQUIRED, REQUIRED],
    }
    for category, statuses in expected.items():
        scope = applicability(ens, category)
        got = [scope[code] for code in ("mp.info.3", "mp.info.3.r1", "mp.info.3.r2", "mp.info.3.r3", "mp.info.3.r4")]
        assert got == statuses, category


def test_a_reinforcement_no_column_cites_is_optional(ens):
    assert {applicability(ens, category)["mp.info.3.r5"] for category in CATEGORIES} == {OPTIONAL}


def test_bracketed_reinforcements_are_alternatives(ens):
    # op.acc.6: «+ [R1 o R2 o R3 o R4] + R5 + R8 + R9» en media.
    scope = applicability(ens, "medium")
    assert [scope[f"op.acc.6.r{n}"] for n in (1, 2, 3, 4)] == [ALTERNATIVE] * 4
    assert [scope[f"op.acc.6.r{n}"] for n in (5, 8, 9)] == [REQUIRED] * 3
    assert scope["op.acc.6.r6"] == NOT_REQUIRED


def test_a_measure_marked_not_applicable_is_not_required_nor_its_reinforcements(ens):
    measure = next(node for node in ens.assessable_nodes()
                   if node.metadata.get("categories", {}).get("basic") == "n.a."
                   and ens.children(node.code))
    scope = applicability(ens, "basic")
    assert scope[measure.identifier] == NOT_REQUIRED
    assert {scope[child.identifier] for child in ens.children(measure.code)} <= {NOT_REQUIRED, OPTIONAL}


def test_every_cell_of_the_annex_is_understood(ens):
    cell = re.compile(r"aplica|n\.a\.|(\+ ?(\[R\d+( o R\d+)*\]|R\d+) ?)+")
    for node in ens.nodes:
        for value in node.metadata.get("categories", {}).values():
            assert cell.fullmatch(value.strip()), (node.identifier, value)


def test_every_cited_reinforcement_exists_in_the_catalog(ens):
    for node in ens.nodes:
        for value in node.metadata.get("categories", {}).values():
            for number in re.findall(r"R(\d+)", value):
                assert ens.node(f"ens:{node.identifier}.r{number}") is not None, (node.identifier, number)


def test_a_reinforcement_can_replace_another_in_a_higher_category(ens):
    # op.pl.1: «+ R1» (análisis semiformal) en media y «+ R2» (formal) en alta; el formal sustituye
    # al semiformal, así que en alta R1 deja de exigirse.
    assert applicability(ens, "medium")["op.pl.1.r1"] == REQUIRED
    assert applicability(ens, "high")["op.pl.1.r1"] == NOT_REQUIRED
    assert applicability(ens, "high")["op.pl.1.r2"] == REQUIRED


def test_the_compliance_percentage_only_counts_what_is_required(ens):
    states = {"mp.info.3": ControlState("implemented"), "mp.info.3.r4": ControlState("implemented")}

    everything = summarize(ens, states, date(2026, 10, 15))["global"]
    basic = summarize(ens, states, date(2026, 10, 15), scope=applicability(ens, "basic"))["global"]

    assert everything["total"] == len(ens.assessable_nodes())
    assert basic["total"] == sum(1 for status in applicability(ens, "basic").values() if status == REQUIRED)
    # mp.info.3.r4 está implementado pero no se exige en básica: no suma.
    assert basic["counts"]["implemented"] == 1
