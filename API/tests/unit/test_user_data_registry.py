"""El registro de datos de usuario y la frontera ``users`` ↔ ``accounts``.

Borrar una cuenta y exportar sus datos recorren ``UserDataRegistry`` en vez de
importar las tablas de ``accounts``. Estos tests fijan tres cosas que, si
cambian en silencio, rompen la baja o la exportación sin que ninguna otra suite
lo note: que ``accounts`` está dado de alta, que el orden de purga es el de
siempre (algunas tablas tienen claves ajenas entre sí) y que ``users`` solo
llama a ``accounts`` por su cara pública.
"""

import ast
from pathlib import Path

import pytest

import src.modules.accounts  # noqa: F401  (darse de alta en el registro es un efecto de la importación)
from src.modules.accounts.data_export import EXPORT_TABLES as ACCOUNTS_EXPORT_TABLES
from src.modules.accounts.model import Subscription
from src.modules.users import UserDataRegistry
from src.modules.users.services import account_deletion, data_export
from src.modules.users.services.user_data import UserDataContribution

pytestmark = pytest.mark.unit

_USERS_DIRECTORY = Path(__file__).resolve().parents[2] / "src" / "modules" / "users"


@pytest.fixture
def isolated_registry():
    """Deja el registro como estaba al terminar, para poder registrar módulos de prueba."""
    saved = dict(UserDataRegistry._contributions)
    yield UserDataRegistry
    UserDataRegistry._contributions.clear()
    UserDataRegistry._contributions.update(saved)


def _noop_purge(uow, user_id):
    return {}


def test_accounts_is_registered_with_everything_it_owns():
    """``accounts`` declara su purga, su categoría del aviso y sus tablas exportables."""
    contribution = next(item for item in UserDataRegistry.contributions() if item.name == "accounts")

    assert isinstance(contribution, UserDataContribution)
    assert contribution.export_tables == ACCOUNTS_EXPORT_TABLES
    assert contribution.deletion_models == {"subscription": (Subscription,)}


def test_the_purge_order_is_the_one_the_foreign_keys_need():
    """Features, luego los módulos registrados y por último ``users``."""
    assert account_deletion.purge_order() == [
        "themis", "aegis", "iris", "hygeia", "accounts", "eunomia", "users",
    ]


def test_the_subscription_category_is_served_by_the_registry():
    """La cuenta de suscripciones del aviso sale del modelo que aporta ``accounts``."""
    assert account_deletion._models_of_deletion_category("subscription") == [Subscription]


def test_the_export_keeps_accounts_between_the_profile_and_the_features():
    """Los módulos del registro (``accounts``, ``eunomia``) van entre el perfil y las features."""
    modules = list(data_export.export_modules())
    assert modules == ["profile", "accounts", "eunomia", "themis", "aegis", "iris", "hygeia", "acheron"]


def test_registered_modules_are_ordered_by_priority_then_name(isolated_registry):
    """El orden no depende de qué módulo se importó antes."""
    isolated_registry.register("zeta", purge=_noop_purge, priority=10)
    isolated_registry.register("alpha", purge=_noop_purge, priority=10)
    isolated_registry.register("first", purge=_noop_purge, priority=1)

    names = [item.name for item in isolated_registry.contributions()]
    assert names.index("first") < names.index("alpha") < names.index("zeta")
    assert names.index("zeta") < names.index("accounts")


def test_registering_twice_keeps_the_last_declaration(isolated_registry):
    """Es idempotente por nombre, como ``QueueRegistry.register``."""
    isolated_registry.register("twice", purge=_noop_purge, priority=1)
    isolated_registry.register("twice", purge=_noop_purge, priority=2)

    entries = [item for item in isolated_registry.contributions() if item.name == "twice"]
    assert len(entries) == 1
    assert entries[0].priority == 2


def test_users_only_imports_the_public_surface_of_accounts():
    """Ningún fichero de ``users`` entra en los ``repositories`` ni en los ``services`` de ``accounts``."""
    offenders = []
    for path in _USERS_DIRECTORY.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
            elif isinstance(node, ast.Import):
                imported = ",".join(alias.name for alias in node.names)
            else:
                continue
            if "src.modules.accounts." in imported:
                offenders.append(f"{path.relative_to(_USERS_DIRECTORY)}: {imported}")

    assert offenders == []
