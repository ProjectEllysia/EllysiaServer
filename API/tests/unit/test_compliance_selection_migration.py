"""La migración que pasa la elección de marcos de Themis a adopciones de Eunomia no pierde ninguna."""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "c2e4f6a8b0d1_compliance_selection_to_eunomia.py"
_spec = importlib.util.spec_from_file_location("compliance_selection_migration", _PATH)
MIGRATION = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MIGRATION)


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE TABLE "Organization" (id INTEGER PRIMARY KEY, owner_user_id INTEGER)'))
        conn.execute(sa.text(
            'CREATE TABLE "ComplianceFrameworkSelection" (id INTEGER PRIMARY KEY, user_id INTEGER, '
            "organization_id INTEGER, frameworks TEXT)"
        ))
        conn.execute(sa.text(
            'CREATE TABLE "EunomiaFrameworkAdoption" (id INTEGER PRIMARY KEY, owner_user_id INTEGER, '
            "framework_key TEXT, catalog_version TEXT, status TEXT, adopted_at TIMESTAMP, "
            "adopted_by_user_id INTEGER, archived_at TIMESTAMP, archived_by_user_id INTEGER)"
        ))
        conn.execute(sa.text('INSERT INTO "Organization" (id, owner_user_id) VALUES (10, 1)'))
        yield conn


def _select(connection, user_id=None, organization_id=None, frameworks=()):
    connection.execute(
        sa.text('INSERT INTO "ComplianceFrameworkSelection" (user_id, organization_id, frameworks) '
                "VALUES (:u, :o, :f)"),
        {"u": user_id, "o": organization_id, "f": json.dumps(list(frameworks))},
    )


def _upgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
        MIGRATION.upgrade()


def _adoptions(connection):
    return connection.execute(sa.text(
        'SELECT owner_user_id, framework_key, catalog_version, status, adopted_by_user_id '
        'FROM "EunomiaFrameworkAdoption" ORDER BY owner_user_id, framework_key'
    )).all()


def test_an_organization_choice_becomes_the_adoptions_of_its_owner(connection):
    _select(connection, organization_id=10, frameworks=["nis2", "ens"])

    _upgrade(connection)

    assert _adoptions(connection) == [
        (1, "ens", "rd-311-2022", "active", 1), (1, "nis2", "2022-2555", "active", 1),
    ]


def test_the_organization_choice_wins_over_the_owners_own(connection):
    _select(connection, user_id=1, frameworks=["iso27001"])
    _select(connection, organization_id=10, frameworks=["nis2"])

    _upgrade(connection)

    assert [row[1] for row in _adoptions(connection)] == ["nis2"]


def test_a_members_own_choice_is_kept_for_when_they_leave(connection):
    _select(connection, user_id=7, frameworks=["ens"])

    _upgrade(connection)

    assert _adoptions(connection) == [(7, "ens", "rd-311-2022", "active", 7)]


def test_an_empty_choice_creates_nothing_and_unknown_keys_are_ignored(connection):
    _select(connection, user_id=3, frameworks=[])
    _select(connection, user_id=4, frameworks=["retirado", "nis2"])

    _upgrade(connection)

    assert _adoptions(connection) == [(4, "nis2", "2022-2555", "active", 4)]


def test_the_old_table_is_dropped(connection):
    _upgrade(connection)

    assert not sa.inspect(connection).has_table("ComplianceFrameworkSelection")
