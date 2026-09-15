"""Los perfiles de escaneo de Lybra ("fast"/"standard"/"thorough").

``_resolve_profile`` es la traducción pura de un perfil a los parámetros que
el motor ya entendía (puertos, modo, checks activos) — se testea aparte de
``run_scan`` porque no necesita base de datos.
"""

import pytest

from src.modules.features.themis.managers.lybra.engine import (
    LYBRA_SCAN_PROFILES,
    _resolve_profile,
    _ALL_PORTS,
)
from src.modules.shared._exceptions import ValidationError
from src.modules.system import config_reading as CR

pytestmark = pytest.mark.unit


def test_standard_profile_keeps_the_old_behaviour():
    """El perfil por defecto no debe cambiar nada de lo que ya existía:
    puertos por defecto (None -> DEFAULT_PORTS) y sin forzar el modo."""
    ports, aggressive, active_checks_override, planner_enabled = _resolve_profile("standard", aggressive=False)
    assert ports is None
    assert aggressive is False
    assert active_checks_override is None
    assert planner_enabled is True


def test_fast_profile_uses_the_configured_port_list_and_disables_checks():
    ports, aggressive, active_checks_override, planner_enabled = _resolve_profile("fast", aggressive=False)
    assert ports == CR.lybra_profiles_config().fast_ports
    assert aggressive is False
    assert active_checks_override is False
    assert planner_enabled is True


def test_thorough_profile_sweeps_every_port_and_implies_aggressive():
    ports, aggressive, active_checks_override, planner_enabled = _resolve_profile("thorough", aggressive=False)
    assert ports == _ALL_PORTS
    assert len(ports) == 65535
    assert aggressive is True
    assert active_checks_override is None
    # El escaneo completo bajo demanda que #314 exige: "thorough" nunca deja
    # que el CheckPlanner decida saltarse nada.
    assert planner_enabled is False


def test_an_explicit_aggressive_request_survives_the_standard_profile():
    # Compatibilidad con el llamador que ya pedía aggressive=True antes de
    # que existieran los perfiles: "standard" es el perfil que no cambia
    # nada de lo que el llamante pida.
    _, aggressive, _, _ = _resolve_profile("standard", aggressive=True)
    assert aggressive is True


def test_fast_profile_ignores_an_explicit_aggressive_request():
    # "fast" no escribe en el objetivo bajo ningún concepto: ni siquiera una
    # petición explícita de modo agresivo lo reabre.
    _, aggressive, active_checks_override, _ = _resolve_profile("fast", aggressive=True)
    assert aggressive is False
    assert active_checks_override is False


def test_an_unknown_profile_is_rejected():
    with pytest.raises(ValidationError):
        _resolve_profile("ultra", aggressive=False)


def test_every_declared_profile_resolves_without_raising():
    for profile in LYBRA_SCAN_PROFILES:
        _resolve_profile(profile, aggressive=False)


def test_fast_ports_config_defaults_to_one_hundred_ports():
    assert len(CR.lybra_profiles_config().fast_ports) == 100
