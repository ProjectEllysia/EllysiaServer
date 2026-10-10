"""Los atributos y los topes de Eunomia que siembra su migración coinciden con el código."""

import importlib.util
from pathlib import Path

import pytest

from src.modules.accounts.services.limits import PERIODS, LimitKey
from src.modules.users.services.permissions import DEFAULT_USER_ATTRIBUTES, AttributeType

pytestmark = pytest.mark.unit

_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions"
    / "e7a9b1c3d5f6_eunomia_attributes_and_plan_limits.py"
)
_spec = importlib.util.spec_from_file_location("eunomia_migration", _PATH)
MIGRATION = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MIGRATION)


def test_the_migration_grants_exactly_the_eunomia_attributes():
    declared = {attribute.value for attribute in AttributeType if attribute.name.startswith("EUNOMIA_")}
    assert set(MIGRATION._ATTRIBUTES) == declared


def test_a_new_account_gets_the_eunomia_attributes_by_default():
    assert {AttributeType(name) for name in MIGRATION._ATTRIBUTES} <= set(DEFAULT_USER_ATTRIBUTES)


def test_the_migration_seeds_every_eunomia_limit_key_with_its_period():
    keys = {key.value: key for key in LimitKey if key.name.startswith("EUNOMIA_")}
    assert set(MIGRATION._LIMITS) == set(keys)
    for value, (period, _) in MIGRATION._LIMITS.items():
        assert PERIODS[keys[value]].value == period


def test_the_free_plan_gets_one_framework():
    assert MIGRATION._LIMITS["eunomia.frameworks"][1]["freemium"] == 1
