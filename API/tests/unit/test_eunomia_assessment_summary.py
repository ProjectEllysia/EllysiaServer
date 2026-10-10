"""El cálculo de cumplimiento: los «no aplica» no cuentan, y nunca se divide por cero."""

from datetime import date

import pytest

from src.modules.features.eunomia.services.assessments import (
    ControlState,
    branch_progress,
    progress_of,
    summarize,
)
from src.modules.features.eunomia.services.catalog import parse_version

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 10)


def _version():
    def req(identifier, parent, order):
        return {"identifier": identifier, "parent": parent, "order": order, "kind": "requirement", "title": identifier}

    return parse_version({
        "key": "demo", "version": "1", "status": "draft", "name": "Demo", "shortName": "Demo",
        "publishedAt": "2026-01-01", "licenseMode": "full_text",
        "sources": [{"name": "n", "url": "u", "license": "l", "consultedAt": "2026-10-10"}],
        "nodes": [
            {"identifier": "A", "parent": None, "order": 1, "kind": "group", "title": "A"},
            req("A.1", "A", 1), req("A.2", "A", 2), req("A.3", "A", 3),
            {"identifier": "B", "parent": None, "order": 2, "kind": "group", "title": "B"},
            req("B.1", "B", 1), req("B.2", "B", 2),
        ],
    })


def test_not_applicable_counts_neither_for_nor_against():
    progress = progress_of({"implemented": 1, "pending": 1, "not_applicable": 2})

    assert progress["countable"] == 2
    assert progress["percent"] == 50.0
    assert progress["total"] == 4


def test_a_framework_without_assessments_is_zero_percent():
    summary = summarize(_version(), {}, TODAY)

    assert summary["global"]["percent"] == 0.0
    assert summary["global"]["counts"]["pending"] == 5


def test_a_branch_where_everything_is_not_applicable_does_not_divide_by_zero():
    states = {"B.1": ControlState("not_applicable"), "B.2": ControlState("not_applicable")}

    branch_b = next(b for b in summarize(_version(), states, TODAY)["branches"] if b["identifier"] == "B")

    assert branch_b["countable"] == 0
    assert branch_b["percent"] == 0.0


def test_each_branch_has_its_own_percentage_and_groups_aggregate_their_children():
    states = {"A.1": ControlState("implemented"), "A.2": ControlState("implemented"), "B.1": ControlState("in_progress")}

    progress = branch_progress(_version(), states)

    assert progress["demo:A"]["percent"] == pytest.approx(66.7, abs=0.05)
    assert progress["demo:B"]["percent"] == 0.0
    assert progress["demo:A.1"]["percent"] == 100.0


def test_upcoming_lists_overdue_and_near_deadlines_but_not_finished_controls():
    states = {
        "A.1": ControlState("pending", date(2026, 10, 1)),        # vencido
        "A.2": ControlState("in_progress", date(2026, 10, 20)),   # próximo
        "A.3": ControlState("pending", date(2027, 1, 1)),         # lejano
        "B.1": ControlState("implemented", date(2026, 10, 1)),    # ya hecho
    }

    upcoming = summarize(_version(), states, TODAY)["upcoming"]

    assert [(item["identifier"], item["isOverdue"]) for item in upcoming] == [("A.1", True), ("A.2", False)]


def test_unassigned_only_counts_open_controls_without_a_responsible():
    states = {
        "A.1": ControlState("pending", responsible_user_id=7),
        "A.2": ControlState("implemented"),
        "B.1": ControlState("not_applicable"),
    }

    summary = summarize(_version(), states, TODAY)

    assert sorted(item["identifier"] for item in summary["unassigned"]) == ["A.3", "B.2"]
    assert summary["unassignedCount"] == 2
