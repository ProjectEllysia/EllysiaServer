"""El presupuesto de tiempo por test de la suite.

Un vigilante que no vigila pasa en verde para siempre sin que nadie lo note,
así que se prueba en los dos sentidos: que detecta lo que debe y que no se
queja de lo que no debe.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Por ruta, igual que lo carga ``tests/conftest.py``.
_SPEC = spec_from_file_location(
    "time_budget_under_test", Path(__file__).resolve().parent.parent / "_time_budget.py"
)
time_budget = module_from_spec(_SPEC)
_SPEC.loader.exec_module(time_budget)

_TEST_ID = "tests/integration/test_x.py::test_y"


def test_a_quick_test_passes():
    assert time_budget.build_budget_failure(_TEST_ID, 0.3, 20.0, {}) is None


def test_a_test_over_the_budget_fails_with_its_name_and_duration():
    failure = time_budget.build_budget_failure(_TEST_ID, 109.4, 20.0, {})

    assert failure is not None
    assert _TEST_ID in failure and "109.4" in failure and "KNOWN_SLOW_TESTS" in failure


def test_a_known_slow_test_may_exceed_the_budget():
    known = {_TEST_ID: "arranca un servidor de verdad"}

    assert time_budget.build_budget_failure(_TEST_ID, 45.0, 20.0, known) is None


def test_a_known_slow_test_that_became_fast_must_leave_the_list():
    known = {_TEST_ID: "arranca un servidor de verdad"}

    failure = time_budget.build_budget_failure(_TEST_ID, 2.0, 20.0, known)

    assert failure is not None and "Quítalo de la lista" in failure


def test_a_known_slow_test_between_half_and_full_budget_is_left_alone():
    """La lista sólo pide quitar un test cuando es claramente rápido: entre la
    mitad y el total del presupuesto el tiempo varía de una máquina a otra."""
    known = {_TEST_ID: "arranca un servidor de verdad"}

    assert time_budget.build_budget_failure(_TEST_ID, 15.0, 20.0, known) is None


@pytest.mark.parametrize("budget", [0.0, -1.0])
def test_a_zero_or_negative_budget_disables_the_check(budget):
    assert time_budget.build_budget_failure(_TEST_ID, 500.0, budget, {}) is None
