"""Tipos de registro: validación de la definición, de las fichas y plazos calculados al leer."""

import copy
from datetime import datetime

import pytest

from src.modules.features.eunomia.services.catalog import CatalogFormatError
from src.modules.features.eunomia.services.registers import (
    DEADLINE_DONE,
    DEADLINE_OVERDUE,
    DEADLINE_PENDING_INPUT,
    DEADLINE_UPCOMING,
    compute_deadlines,
    parse_register,
    validate_values,
)

pytestmark = pytest.mark.unit

_DOCUMENT = {
    "key": "demo", "version": "1", "title": "Demo", "summary": "Un registro de prueba.", "titleField": "name",
    "controls": {"nis2": ["23.1"]},
    "fields": [
        {"key": "name", "label": "Nombre", "type": "text", "required": True},
        {"key": "kind", "label": "Tipo", "type": "select", "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]},
        {"key": "seen_at", "label": "Constancia", "type": "datetime"},
        {"key": "sent_at", "label": "Enviado", "type": "datetime"},
        {"key": "day", "label": "Día", "type": "date"},
    ],
    "deadlines": [
        {"key": "early", "label": "Alerta", "from": "seen_at", "hours": 24, "doneField": "sent_at"},
        {"key": "final", "label": "Informe final", "from": "day", "months": 1, "whenField": "kind", "whenEquals": "a"},
    ],
    "examples": [{"name": "Ejemplo", "kind": "a"}],
}


def _register(mutate=None):
    document = copy.deepcopy(_DOCUMENT)
    if mutate:
        mutate(document)
    return parse_register(document)


def test_a_valid_definition_is_accepted():
    register = _register()

    assert register.title_field == "name"
    assert [item.key for item in register.deadlines] == ["early", "final"]


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["fields"].append({"key": "name", "label": "x", "type": "text"}), "repetido"),
    (lambda d: d["fields"][0].update({"type": "rara"}), "tipo desconocido"),
    (lambda d: d["fields"][1].pop("options"), "select"),
    (lambda d: d.update({"titleField": "no_existe"}), "titleField"),
    (lambda d: d["deadlines"][0].update({"from": "name"}), "campo fecha"),
    (lambda d: d["deadlines"][0].update({"doneField": "no_existe"}), "no existe"),
    (lambda d: d["controls"].update({"nis2": ["RE.3"]}), "no existe o no es evaluable"),
    (lambda d: d["examples"].append({"kind": "a"}), "ejemplo"),
])
def test_an_invalid_definition_is_rejected(mutate, message):
    with pytest.raises(CatalogFormatError, match=message):
        _register(mutate)


def test_a_record_that_does_not_meet_the_definition_is_reported():
    register = _register()

    assert validate_values(register, {"name": "Ok", "kind": "a", "seen_at": "2026-10-10T08:00"}) == []
    assert set(validate_values(register, {"kind": "z", "seen_at": "ayer", "inventado": "x"})) == {
        "kind", "seen_at", "inventado", "name"}


def test_a_deadline_runs_from_its_date_field_and_is_not_stored():
    register = _register()
    values = {"name": "x", "seen_at": "2026-10-10T08:00"}

    early = compute_deadlines(register, values, datetime(2026, 10, 10, 20, 0))[0]
    assert (early["dueAt"], early["status"]) == (datetime(2026, 10, 11, 8, 0), DEADLINE_UPCOMING)
    late = compute_deadlines(register, values, datetime(2026, 10, 12))[0]
    assert late["status"] == DEADLINE_OVERDUE


def test_a_deadline_without_its_origin_date_waits_for_input():
    assert compute_deadlines(_register(), {"name": "x"}, datetime(2026, 10, 10))[0]["status"] == DEADLINE_PENDING_INPUT


def test_a_filled_done_field_closes_the_deadline():
    values = {"name": "x", "seen_at": "2026-10-01T08:00", "sent_at": "2026-10-01T20:00"}

    assert compute_deadlines(_register(), values, datetime(2026, 10, 20))[0]["status"] == DEADLINE_DONE


def test_a_conditional_deadline_only_applies_when_its_condition_holds():
    register = _register()

    keys = lambda values: [d["key"] for d in compute_deadlines(register, values, datetime(2026, 10, 10))]  # noqa: E731

    assert keys({"name": "x", "kind": "b"}) == ["early"]
    assert keys({"name": "x", "kind": "a", "day": "2026-01-31"}) == ["early", "final"]


def test_months_clamp_to_the_end_of_a_shorter_month():
    final = compute_deadlines(_register(), {"name": "x", "kind": "a", "day": "2026-01-31"}, datetime(2026, 2, 1))[1]

    assert final["dueAt"] == datetime(2026, 2, 28)
