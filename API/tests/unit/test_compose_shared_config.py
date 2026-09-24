"""
Contrato del ``docker-compose.yml`` con el fichero de cambios de configuración.

La API y el worker son contenedores distintos. Para que un cambio guardado desde
la pantalla de configuración llegue a los trabajos en segundo plano, los dos
tienen que apuntar ``SECOPS_CONFIG_OVERRIDES_PATH`` al mismo fichero, dentro de
un volumen que monten los dos. Si uno de ellos pierde la variable o el volumen,
nada falla al arrancar: el worker sigue con su copia de la imagen en silencio.
"""

from pathlib import Path

import pytest
import yaml

import src.modules.system.config_reading as CR

pytestmark = pytest.mark.unit

_COMPOSE_PATH = Path(__file__).resolve().parents[3] / "docker-compose.yml"
_SERVICES_THAT_READ_CONFIG = ("ellysia", "ellysia-worker")


@pytest.fixture(scope="module")
def compose():
    """El ``docker-compose.yml`` de la raíz, ya parseado."""
    return yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))


def _mount_for(service: dict, container_path: str) -> str | None:
    """Nombre del volumen montado en ``container_path``, o ``None`` si no hay."""
    for volume in service.get("volumes", []):
        source, _, target = volume.partition(":")
        if target.split(":")[0] == container_path:
            return source
    return None


def test_api_and_worker_point_to_the_same_overrides_file(compose):
    paths = {
        compose["services"][name]["environment"].get(CR.CONFIG_OVERRIDES_ENV)
        for name in _SERVICES_THAT_READ_CONFIG
    }
    assert len(paths) == 1
    assert None not in paths


def test_the_overrides_file_lives_in_a_volume_both_services_mount(compose):
    overrides_path = compose["services"]["ellysia"]["environment"][CR.CONFIG_OVERRIDES_ENV]
    config_dir = str(Path(overrides_path).parent.as_posix())

    volumes = {
        _mount_for(compose["services"][name], config_dir)
        for name in _SERVICES_THAT_READ_CONFIG
    }
    assert len(volumes) == 1
    volume_name = volumes.pop()
    assert volume_name in compose["volumes"], "el fichero tiene que estar en un volumen con nombre, no en la imagen"
