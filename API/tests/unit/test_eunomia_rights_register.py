"""Registro de solicitudes de derechos: plazo de un mes, o de tres con prórroga."""

from datetime import datetime

import pytest

from src.modules.features.eunomia.services.registers import compute_deadlines, get_register

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 2, 1)


def _due(values):
    register = get_register("rgpd-solicitudes-derechos")
    return {item["key"]: item for item in compute_deadlines(register, values, _NOW)}


def test_a_request_is_due_one_month_after_it_is_received():
    deadlines = _due({"received_at": "2026-01-15"})

    assert list(deadlines) == ["response"]
    assert deadlines["response"]["dueAt"] == datetime(2026, 2, 15)


def test_marking_the_extension_moves_the_deadline_to_three_months():
    deadlines = _due({"received_at": "2026-01-15", "extension": "yes"})

    assert list(deadlines) == ["response_extended"]
    assert deadlines["response_extended"]["dueAt"] == datetime(2026, 4, 15)


def test_an_answered_request_has_its_deadline_done():
    deadlines = _due({"received_at": "2026-01-15", "responded_at": "2026-01-20"})

    assert deadlines["response"]["status"] == "done"
