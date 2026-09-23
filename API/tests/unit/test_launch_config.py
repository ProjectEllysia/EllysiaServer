"""
Tests de ``LaunchConfig``: qué superficies están abiertas al público.

El bloque decide, con un modo general y un interruptor por superficie, si el
alta, los precios, los escáneres de terceros, las campañas, los buzones y la
IA externa están abiertos. Lo que se fija aquí es la regla de decisión y, sobre
todo, que ante la duda se cierra.
"""
import pytest

import src.modules.system.config_reading as CR

pytestmark = pytest.mark.unit

_ALL_OPEN = {surface.value: True for surface in CR.LaunchSurface}


@pytest.fixture(autouse=True)
def _without_launch_mode_env(monkeypatch):
    """Estos tests prueban el bloque, no la variable de entorno de la suite."""
    monkeypatch.delenv("LAUNCH_MODE", raising=False)


def test_preview_closes_every_surface_even_with_its_switch_on():
    config = CR.LaunchConfig(configured_mode="preview", surfaces=_ALL_OPEN)

    assert not any(config.is_surface_enabled(surface) for surface in CR.LaunchSurface)


def test_public_follows_each_switch():
    config = CR.LaunchConfig(
        configured_mode="public",
        surfaces={**_ALL_OPEN, "pricing": False},
    )

    assert config.is_surface_enabled(CR.LaunchSurface.REGISTRATION)
    assert not config.is_surface_enabled(CR.LaunchSurface.PRICING)


def test_a_surface_missing_from_the_switches_counts_as_closed():
    config = CR.LaunchConfig(configured_mode="public", surfaces={"registration": True})

    assert not config.is_surface_enabled(CR.LaunchSurface.CAMPAIGNS)


@pytest.mark.parametrize("configured_mode", ["", "PREVIEW", "abierto", "publico", None])
def test_an_unknown_mode_counts_as_preview(configured_mode):
    config = CR.LaunchConfig(configured_mode=configured_mode, surfaces=_ALL_OPEN)

    assert config.mode is CR.LaunchMode.PREVIEW
    assert not config.is_surface_enabled(CR.LaunchSurface.REGISTRATION)


def test_the_mode_is_case_insensitive_for_public():
    config = CR.LaunchConfig(configured_mode=" Public ", surfaces=_ALL_OPEN)

    assert config.mode is CR.LaunchMode.PUBLIC


def test_the_environment_can_open_a_local_copy(monkeypatch):
    monkeypatch.setenv("LAUNCH_MODE", "public")
    config = CR.LaunchConfig(configured_mode="preview", surfaces=_ALL_OPEN)

    assert config.is_surface_enabled(CR.LaunchSurface.EXTERNAL_AI)


def test_the_surface_can_be_given_by_its_value():
    config = CR.LaunchConfig(configured_mode="public", surfaces=_ALL_OPEN)

    assert config.is_surface_enabled("thirdPartyScanners")


def test_an_unknown_surface_raises_instead_of_answering_closed():
    """Una errata en el nombre tiene que verse, no quedarse cerrada en silencio."""
    config = CR.LaunchConfig(configured_mode="public", surfaces=_ALL_OPEN)

    with pytest.raises(ValueError):
        config.is_surface_enabled("regsitration")


@pytest.mark.parametrize("raw_switch, expected", [("true", True), ("false", False), (1, True), (0, False)])
def test_non_boolean_switches_are_coerced(raw_switch, expected):
    config = CR.LaunchConfig(configured_mode="public", surfaces={"pricing": raw_switch})

    assert config.is_surface_enabled(CR.LaunchSurface.PRICING) is expected


def test_the_block_defaults_to_preview():
    assert CR.LaunchConfig().mode is CR.LaunchMode.PREVIEW


def test_assert_surface_enabled_raises_with_the_surface_in_the_details(monkeypatch):
    from src.modules.shared import SurfaceDisabledError, assert_surface_enabled

    monkeypatch.setattr(CR, "launch_config", lambda: CR.LaunchConfig(configured_mode="preview"))

    with pytest.raises(SurfaceDisabledError) as raised:
        assert_surface_enabled(CR.LaunchSurface.CAMPAIGNS)

    assert raised.value.status_code == 403
    assert raised.value.to_dict()["details"] == {"surface": "campaigns"}


def test_assert_surface_enabled_lets_an_exempt_caller_through(monkeypatch):
    from src.modules.shared import assert_surface_enabled

    monkeypatch.setattr(CR, "launch_config", lambda: CR.LaunchConfig(configured_mode="preview"))

    assert_surface_enabled(CR.LaunchSurface.CAMPAIGNS, is_exempt=True)


def test_the_public_dict_has_every_surface_already_resolved():
    config = CR.LaunchConfig(configured_mode="public", surfaces={**_ALL_OPEN, "campaigns": False})

    public_state = config.to_public_dict()

    assert public_state["mode"] == "public"
    assert set(public_state["surfaces"]) == {surface.value for surface in CR.LaunchSurface}
    assert public_state["surfaces"]["campaigns"] is False
    assert public_state["surfaces"]["registration"] is True


def test_the_public_dict_in_preview_reports_everything_closed():
    public_state = CR.LaunchConfig(configured_mode="preview", surfaces=_ALL_OPEN).to_public_dict()

    assert public_state["mode"] == "preview"
    assert not any(public_state["surfaces"].values())
