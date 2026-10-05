"""L117: las comprobaciones marcadas ``aggressive`` no corren en modo ``safe``.

El mecanismo ya existe (``CheckRuntime._applies_mode``); lo que fija este test
es la **política**: cada check que hoy vive bajo ``mode: aggressive`` no debe
aparecer en absoluto en un informe generado en modo ``safe`` — ni como
hallazgo ni de ninguna otra forma, porque el runtime no produce entradas para
lo que no corrió —, y sí debe correr cuando el runtime se lanza en
``aggressive``. Se usa un plugin simulado que siempre «aplica» y siempre
«dispara»: así la prueba aísla la puerta de modo de la lógica real de cada
protocolo, que ya tiene sus propios tests.
"""

import pytest

from src.modules.features.themis.lybra.checks import (
    CHECK_MODES,
    CheckRuntime,
    Service,
    load_checks,
)

pytestmark = pytest.mark.unit

_HOST = "10.0.0.5"
_SMB = Service(445, "tcp", "microsoft-ds")
_SSH = Service(22, "tcp", "ssh")

_SERVICE_BY_FAMILY = {"smb": _SMB, "ssh": _SSH}


class _AlwaysFiresPlugin:
    """Un plugin de prueba que siempre se considera aplicable y siempre dispara."""

    def applies(self, _service) -> bool:
        return True

    def run(self, _context) -> bool:
        return True


def _aggressive_checks():
    return [check for check in load_checks() if check.mode == "aggressive"]


def test_every_check_mode_is_one_of_the_two_known():
    assert {check.mode for check in load_checks()} <= set(CHECK_MODES)


def test_there_is_at_least_one_aggressive_check_today():
    """Si esto deja de cumplirse, el resto del fichero no prueba nada."""
    assert _aggressive_checks()


@pytest.mark.parametrize("check", _aggressive_checks(), ids=lambda c: c.id)
def test_an_aggressive_check_produces_nothing_in_safe_mode(check):
    service = _SERVICE_BY_FAMILY[check.service]
    plugins = {check.script: _AlwaysFiresPlugin()}
    findings = CheckRuntime([check], fetch=lambda *a, **k: None,
                            mode="safe", script_plugins=plugins).run(_HOST, [service])
    assert findings == []


@pytest.mark.parametrize("check", _aggressive_checks(), ids=lambda c: c.id)
def test_the_same_aggressive_check_fires_in_aggressive_mode(check):
    service = _SERVICE_BY_FAMILY[check.service]
    plugins = {check.script: _AlwaysFiresPlugin()}
    findings = CheckRuntime([check], fetch=lambda *a, **k: None,
                            mode="aggressive", script_plugins=plugins).run(_HOST, [service])
    assert [f["check_id"] for f in findings] == [f"lybra:{check.id}@{check.version}"]


def test_a_mixed_batch_in_safe_mode_only_loses_the_aggressive_ones():
    """Un escaneo normal no se queda sin nada: sólo se recorta lo agresivo."""
    checks = _aggressive_checks()
    plugins = {check.script: _AlwaysFiresPlugin() for check in checks}
    findings = CheckRuntime(checks, fetch=lambda *a, **k: None,
                            mode="safe", script_plugins=plugins).run(_HOST, [_SMB, _SSH])
    assert findings == []
    findings = CheckRuntime(checks, fetch=lambda *a, **k: None,
                            mode="aggressive", script_plugins=plugins).run(_HOST, [_SMB, _SSH])
    # El plugin simulado "aplica" a cualquier servicio, así que cada check se
    # evalúa contra los dos servicios de la lista.
    assert len(findings) == len(checks) * 2
