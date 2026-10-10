"""Validación del NIF/CIF/NIE español: forma y carácter de control."""

import pytest

from src.modules.accounts.services.tax_id import is_valid_spanish_tax_id, normalize_tax_id

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", [
    "12345678Z",      # DNI
    "X1234567L",      # NIE
    "B12345674",      # CIF con control numérico
    "Q2826000H",      # CIF de una entidad pública: el control es una letra
    " b-12345674 ",   # con separadores y en minúsculas
])
def test_valid_tax_ids_are_accepted(value):
    assert is_valid_spanish_tax_id(value) is True


@pytest.mark.parametrize("value", [
    "", "12345678A", "X1234567A", "B12345675", "Q2826000A", "1234567", "ABC", "K1234567L",
])
def test_invalid_tax_ids_are_rejected(value):
    assert is_valid_spanish_tax_id(value) is False


def test_normalization_drops_separators_and_uppercases():
    assert normalize_tax_id(" b-123.456 74 ") == "B12345674"
