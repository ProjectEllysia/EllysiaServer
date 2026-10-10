"""El valor de un tope de plan cabe en bytes: los de almacenamiento pasan de lo que cabe en 32 bits."""

import pytest
from sqlalchemy import BigInteger

from src.modules.accounts.model import PlanLimit

pytestmark = pytest.mark.unit

_INT32_MAX = 2**31 - 1


def test_plan_limit_value_is_a_big_integer():
    assert isinstance(PlanLimit.__table__.c.value.type, BigInteger)


def test_a_five_gibibyte_limit_exceeds_what_fits_in_32_bits():
    assert 5 * 1024**3 > _INT32_MAX
