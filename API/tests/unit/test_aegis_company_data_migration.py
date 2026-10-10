"""La migración que mueve los datos de empresa de Aegis al perfil de empresa no pierde nada."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

pytestmark = pytest.mark.unit

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COPY = _load("f8b0c2d4e6a7_aegis_company_data_to_company_profile")
DROP = _load("a9c1d3e5f7b8_aegis_drop_company_columns")


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text(
            'CREATE TABLE "AegisOrgProfile" (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, company TEXT, '
            "contact_email TEXT, company_size TEXT, jurisdiction TEXT, sector TEXT, work_model TEXT, "
            "employee_count INTEGER, brand_logo TEXT, tone TEXT)"
        ))
        conn.execute(sa.text(
            'CREATE TABLE "CompanyProfile" (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, legal_name TEXT, '
            "tax_id TEXT, sector TEXT, company_size TEXT, employee_count INTEGER, jurisdiction TEXT, "
            "work_model TEXT, security_contact TEXT, brand_logo TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)"
        ))
        yield conn


def _run(connection, module, step="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, step)()


def test_every_aegis_profile_gets_its_own_company_profile(connection):
    connection.execute(sa.text(
        'INSERT INTO "AegisOrgProfile" (user_id, company, contact_email, sector, employee_count, brand_logo) '
        "VALUES (1, 'Acme', 'sec@acme.es', 'banca', 40, 'data:image/png;base64,AAAA'), (2, '', '', '', NULL, NULL)"
    ))

    _run(connection, COPY)

    rows = connection.execute(sa.text(
        'SELECT user_id, legal_name, security_contact, sector, employee_count, brand_logo '
        'FROM "CompanyProfile" ORDER BY user_id'
    )).all()
    assert rows[0] == (1, "Acme", "sec@acme.es", "banca", 40, "data:image/png;base64,AAAA")
    assert rows[1] == (2, None, None, None, None, None)


def test_an_existing_company_profile_keeps_what_it_had(connection):
    connection.execute(sa.text(
        'INSERT INTO "AegisOrgProfile" (user_id, company, sector) VALUES (1, \'Vieja SL\', \'banca\')'
    ))
    connection.execute(sa.text(
        'INSERT INTO "CompanyProfile" (user_id, legal_name, tax_id) VALUES (1, \'Nueva SL\', \'B12345674\')'
    ))

    _run(connection, COPY)

    row = connection.execute(sa.text(
        'SELECT legal_name, tax_id, sector FROM "CompanyProfile" WHERE user_id = 1'
    )).one()
    assert row == ("Nueva SL", "B12345674", "banca")


def test_dropping_the_columns_leaves_the_aegis_settings(connection):
    connection.execute(sa.text('INSERT INTO "AegisOrgProfile" (user_id, company, tone) VALUES (1, \'Acme\', \'formal\')'))

    _run(connection, DROP)

    columns = {column["name"] for column in sa.inspect(connection).get_columns("AegisOrgProfile")}
    assert columns == {"id", "user_id", "tone"}
    assert connection.execute(sa.text('SELECT tone FROM "AegisOrgProfile"')).scalar() == "formal"
