"""
El servidor cierra las superficies que ``general.launch`` no tiene abiertas.

Ocultar un botón en la SPA no cierra nada: cualquiera con un token puede
llamar a la API, y algunas funciones corren solas (escaneos programados,
sincronización de buzones). Estos tests fijan que cada superficie se rechaza
**en el servidor**, por HTTP y por el camino que no pasa por HTTP, y que el
administrador principal queda exento donde se sabe en nombre de quién se
trabaja.

La suite corre con ``LAUNCH_MODE=public`` (``tests/conftest.py``); aquí se
quita la variable y se sustituye el bloque por uno en ``preview`` con todos los
interruptores encendidos, para comprobar que el modo manda sobre ellos.
"""
from unittest import mock

import pytest

import src.modules.system.config_reading as CR
from src.modules.features.iris.managers import IrisMailboxManager
from src.modules.features.iris.model import IrisMailboxConnection
from src.modules.features.iris.repositories import IrisMailboxConnectionRepository
from src.modules.features.iris.services.mailbox.scheduling import IrisMailboxScheduler
from src.modules.features.themis.exceptions import PrivateIPRequested
from src.modules.features.themis.managers import NiktoScanManager, NmapScanManager, NucleiScanManager
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import SurfaceDisabledError
from src.modules.tools.scribe import build_generator
from src.modules.tools.scribe.factory import _assert_strategy_allowed

pytestmark = pytest.mark.integration

_SURFACE_DISABLED_CODE = 1618
_ALL_SWITCHES_ON = {surface.value: True for surface in CR.LaunchSurface}


@pytest.fixture()
def preview_mode(monkeypatch):
    """Pone la instalación en vista previa con todos los interruptores encendidos."""
    monkeypatch.delenv("LAUNCH_MODE", raising=False)
    monkeypatch.setattr(
        CR, "launch_config",
        lambda: CR.LaunchConfig(configured_mode="preview", surfaces=_ALL_SWITCHES_ON),
    )


class _FakeTaskQueue:
    """Doble de la TaskQueue que solo recuerda lo que se le encola."""

    def __init__(self):
        self.submitted = []

    def submit(self, **kwargs):
        self.submitted.append(kwargs)


def _assert_surface_disabled(response, surface: str) -> None:
    assert response.status_code == 403
    body = response.get_json()
    assert body["code"] == _SURFACE_DISABLED_CODE
    assert body["details"]["surface"] == surface


def _save_connection(app, user_id: int) -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            connection = IrisMailboxConnection(
                user_id=user_id, provider="gmail", account_email="buzon@example.com",
                scopes="gmail.metadata", refresh_token="refresh-token", status="active",
            )
            IrisMailboxConnectionRepository(uow).save(connection)
            return connection.id


# ------------------------------------------------------------------ precios

def test_the_price_list_is_closed_in_preview(client, preview_mode):
    _assert_surface_disabled(client.get("/plans"), "pricing")


def test_the_price_list_is_open_in_public_mode(client):
    assert client.get("/plans").status_code == 200


# --------------------------------------------------------- escáneres de terceros

@pytest.mark.parametrize("start_scan", [
    lambda user_id: NmapScanManager().run_scan(target_host="8.8.8.8", target_ports="80", user_id=user_id),
    lambda user_id: NiktoScanManager().run_scan(target_domain="8.8.8.8", user_id=user_id),
    lambda user_id: NucleiScanManager().run_scan(target="http://8.8.8.8", user_id=user_id),
], ids=["nmap", "nikto", "nuclei"])
def test_third_party_scanners_are_closed_also_on_the_scheduled_flow(app, preview_mode, regular_user, start_scan):
    """``run_scan`` es por donde entran también los escaneos programados."""
    with app.app_context():
        with pytest.raises(SurfaceDisabledError) as raised:
            start_scan(regular_user.id)

    assert raised.value.surface == "thirdPartyScanners"


def test_the_nmap_endpoint_answers_surface_disabled(client, preview_mode, make_user, auth_headers):
    themis_creator = make_user(role="role_user", attributes=["themis_create"])

    response = client.post(
        "/themis/nmap", headers=auth_headers(themis_creator),
        json={"target": "8.8.8.8", "ports": "80"},
    )

    _assert_surface_disabled(response, "thirdPartyScanners")


def test_the_main_administrator_is_exempt_from_the_scanner_closure(app, preview_mode, make_user):
    """El administrador principal pasa el cierre y llega a la siguiente validación."""
    root = make_user(role="role_root")

    with app.app_context():
        with pytest.raises(PrivateIPRequested):
            NmapScanManager().run_scan(target_host="10.0.0.5", target_ports="80", user_id=root.id)


def test_an_administrator_below_root_is_not_exempt(app, preview_mode, make_user):
    admin = make_user(role="role_admin")

    with app.app_context():
        with pytest.raises(SurfaceDisabledError):
            NmapScanManager().run_scan(target_host="8.8.8.8", target_ports="80", user_id=admin.id)


# ---------------------------------------------------------------- campañas

def test_launching_a_campaign_is_closed_in_preview(client, preview_mode, make_user, auth_headers):
    """El cierre va antes que cualquier validación: ni siquiera mira si la campaña existe."""
    aegis_editor = make_user(role="role_user", attributes=["aegis_update"])

    response = client.post("/aegis/campaigns/999999/launch", headers=auth_headers(aegis_editor))

    _assert_surface_disabled(response, "campaigns")


# ---------------------------------------------------------------- buzones

def test_connecting_a_mailbox_is_closed_in_preview(client, preview_mode, make_user, auth_headers):
    iris_creator = make_user(role="role_user", attributes=["iris_create"])

    response = client.post(
        "/iris/mailbox/connect", headers=auth_headers(iris_creator), json={"provider": "gmail"},
    )

    _assert_surface_disabled(response, "mailboxConnectors")


def test_mailbox_sync_is_not_queued_in_preview(app, preview_mode, regular_user):
    connection_id = _save_connection(app, regular_user.id)
    fake_queue = _FakeTaskQueue()

    with app.app_context():
        with pytest.raises(SurfaceDisabledError):
            IrisMailboxManager(task_queue=fake_queue).submit_sync(connection_id)

    assert fake_queue.submitted == []


def test_the_main_administrator_mailboxes_keep_syncing_in_preview(app, preview_mode, make_user):
    root = make_user(role="role_root")
    connection_id = _save_connection(app, root.id)
    fake_queue = _FakeTaskQueue()

    with app.app_context():
        IrisMailboxManager(task_queue=fake_queue).submit_sync(connection_id)

    assert len(fake_queue.submitted) == 1


def test_the_periodic_poll_skips_closed_mailboxes_without_warning(app, preview_mode, regular_user, caplog):
    """Una conexión en pausa por el cierre no es un fallo: no merece un aviso."""
    _save_connection(app, regular_user.id)
    fake_queue = _FakeTaskQueue()

    with app.app_context(), \
            mock.patch.object(IrisMailboxManager, "__init__", lambda self, **_: setattr(self, "_task_queue", fake_queue)), \
            caplog.at_level("INFO"):
        IrisMailboxScheduler._poll_connections()

    assert fake_queue.submitted == []
    assert not [record for record in caplog.records if record.levelname == "WARNING"]
    assert any("en pausa" in record.getMessage() for record in caplog.records)


# ------------------------------------------------------------- IA externa

def test_an_external_ai_provider_is_closed_in_preview(preview_mode):
    with pytest.raises(SurfaceDisabledError) as raised:
        _assert_strategy_allowed("openai")

    assert raised.value.surface == "externalAi"


def test_a_local_ai_provider_is_allowed_in_preview(preview_mode):
    _assert_strategy_allowed("ollama")


def test_building_a_generator_for_an_external_provider_fails_in_preview(preview_mode, monkeypatch):
    monkeypatch.setattr(
        CR, "scribe_config",
        lambda: CR.ScribeConfig(default_strategy="openai"),
    )

    with pytest.raises(SurfaceDisabledError):
        build_generator("aegis")
