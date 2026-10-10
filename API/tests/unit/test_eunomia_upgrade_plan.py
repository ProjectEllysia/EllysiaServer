"""El plan de cambio de versión traslada lo seguro y pide revisión de lo que no lo es."""

import pytest

from src.modules.features.eunomia.services.upgrade_plan import plan_upgrade
from src.modules.features.eunomia.services.version_mappings import Correspondence, VersionMapping

pytestmark = pytest.mark.unit


def _mapping(*entries):
    return VersionMapping("demo", "1", "2", tuple(Correspondence(*entry, "") for entry in entries))


MAPPING = _mapping(
    ("A", "X", "equivalent"),
    ("B", "Y", "split"), ("B", "Z", "split"),
    ("C", "W", "merged"), ("D", "W", "merged"),
    ("E", None, "retired"),
    (None, "N", "new"),
)


def test_an_equivalent_control_moves_intact_without_review():
    plan = plan_upgrade(MAPPING, {"A": "implemented"}, set())

    move = next(m for m in plan.moves if m.target == "X")
    assert (move.status, move.needs_review) == ("implemented", False)


def test_a_split_control_lands_in_review_in_every_destination():
    plan = plan_upgrade(MAPPING, {"B": "implemented"}, set())

    moves = {m.target: m for m in plan.moves if m.sources == ("B",)}
    assert set(moves) == {"Y", "Z"}
    assert all(m.needs_review and m.reason == "split" for m in moves.values())


def test_a_merged_control_is_never_better_than_its_sources():
    plan = plan_upgrade(MAPPING, {"C": "implemented", "D": "pending"}, set())

    move = next(m for m in plan.moves if m.target == "W")
    assert move.status == "in_progress" and move.needs_review


def test_a_merge_of_two_implemented_controls_stays_implemented_but_is_reviewed():
    move = next(m for m in plan_upgrade(MAPPING, {"C": "implemented", "D": "implemented"}, set()).moves
                if m.target == "W")

    assert move.status == "implemented" and move.needs_review


def test_a_retired_control_is_lost_with_its_status_and_a_new_one_is_pending():
    plan = plan_upgrade(MAPPING, {"E": "implemented"}, set())

    assert plan.lost == (("E", "implemented"),)
    assert plan.new_controls == ("N",)
    assert not any(m.target == "N" for m in plan.moves)


def test_unassessed_controls_move_nothing_but_their_links_do():
    plan = plan_upgrade(MAPPING, {}, {"A", "E"})

    assert plan.moves == ()
    assert plan.link_moves == (("A", "X"),)     # E se retira: su enlace se pierde


def test_a_merge_with_an_unassessed_source_is_not_better_than_that_source():
    move = next(m for m in plan_upgrade(MAPPING, {"C": "implemented"}, set()).moves if m.target == "W")

    assert move.status == "in_progress"
