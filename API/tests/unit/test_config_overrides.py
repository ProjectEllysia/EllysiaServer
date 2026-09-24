"""
Tests del fichero de cambios de configuración compartido entre la API y el worker.

En Docker, la API y el worker son contenedores distintos y cada uno lleva su
copia de ``SecOpsConfig.json`` dentro de la imagen. Un cambio guardado desde la
interfaz llegaba solo a la copia de la API: el worker seguía, por ejemplo, en
modo de vista previa y rechazaba la IA externa. Con
``SECOPS_CONFIG_OVERRIDES_PATH`` los cambios van a un fichero aparte que los dos
leen; sin la variable (desarrollo) todo funciona sobre ``SecOpsConfig.json``.
"""

import json
import os

import pytest

import src.modules.system.config_reading as CR

pytestmark = pytest.mark.unit


_BASE_CONFIG = {
    "appVersion": "1.0.0",
    "general": {
        "launch": {"mode": "preview", "surfaces": {"externalAi": True}},
        "publicUrl": "https://example.test",
    },
    "features": {"themis": {"prompts": ["uno", "dos"]}},
}


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Apunta el lector a una base temporal y deja la config sin cargar.

    Returns:
        Path: La ruta de la base temporal. El fichero de cambios, si el test lo
            activa, va en ``tmp_path / "config" / "overrides.json"``.
    """
    base_path = tmp_path / "SecOpsConfig.json"
    base_path.write_text(json.dumps(_BASE_CONFIG), encoding="utf-8")
    monkeypatch.delenv(CR.CONFIG_OVERRIDES_ENV, raising=False)
    monkeypatch.delenv("LAUNCH_MODE", raising=False)
    monkeypatch.setattr(CR, "_configs_path", base_path)
    monkeypatch.setattr(CR, "_configs", None)
    monkeypatch.setattr(CR, "_configs_mtimes", (0.0, 0.0))
    return base_path


@pytest.fixture
def overrides_path(tmp_path, monkeypatch, isolated_config):
    """Activa el fichero de cambios compartido, como en Docker."""
    path = tmp_path / "config" / "overrides.json"
    monkeypatch.setenv(CR.CONFIG_OVERRIDES_ENV, str(path))
    return path


def _bump_mtime(path):
    """Adelanta el mtime para que el cambio se vea aunque el reloj sea grueso."""
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 5))


def _edited(config, mode="public"):
    """Copia de ``config`` con el modo de lanzamiento cambiado."""
    edited = json.loads(json.dumps(config))
    edited["general"]["launch"]["mode"] = mode
    return edited


# ── Desarrollo: sin variable, todo como siempre ─────────────────────────────


def test_without_the_variable_saving_rewrites_the_base_file(isolated_config):
    CR.save_full_config(_edited(CR.get_full_config()))

    on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert on_disk["general"]["launch"]["mode"] == "public"
    assert CR.launch_config().mode is CR.LaunchMode.PUBLIC


def test_without_the_variable_another_process_sees_the_edit(isolated_config, monkeypatch):
    """El worker en WSL comparte el checkout: le basta con releer la base."""
    CR.get_full_config()
    edited = _edited(_BASE_CONFIG)
    isolated_config.write_text(json.dumps(edited), encoding="utf-8")
    _bump_mtime(isolated_config)

    assert CR.reload_if_changed() is True
    assert CR.launch_config().mode is CR.LaunchMode.PUBLIC


# ── Docker: los cambios van al fichero compartido ───────────────────────────


def test_with_the_variable_the_base_file_is_never_written(isolated_config, overrides_path):
    CR.save_full_config(_edited(CR.get_full_config()))

    assert json.loads(isolated_config.read_text(encoding="utf-8")) == _BASE_CONFIG
    assert overrides_path.exists()


def test_only_the_edited_leaves_are_stored(overrides_path):
    CR.save_full_config(_edited(CR.get_full_config()))

    stored = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert stored == {"general": {"launch": {"mode": "public"}}}


def test_the_saved_edit_is_the_effective_config(overrides_path):
    saved = CR.save_full_config(_edited(CR.get_full_config()))

    assert saved["general"]["launch"]["mode"] == "public"
    assert CR.launch_config().mode is CR.LaunchMode.PUBLIC


def test_the_worker_sees_an_edit_saved_by_the_api(overrides_path):
    """El caso del fallo: la API guarda y el worker lo ve en el siguiente job."""
    CR.get_full_config()  # el worker ya tenía la config cargada, en vista previa
    assert CR.launch_config().is_surface_enabled(CR.LaunchSurface.EXTERNAL_AI) is False

    # La API es otro proceso: escribe el fichero compartido por su cuenta.
    overrides_path.parent.mkdir(parents=True)
    overrides_path.write_text(json.dumps({"general": {"launch": {"mode": "public"}}}), encoding="utf-8")

    assert CR.reload_if_changed() is True
    assert CR.launch_config().is_surface_enabled(CR.LaunchSurface.EXTERNAL_AI) is True


def test_a_change_in_the_base_still_arrives_when_that_key_was_not_edited(isolated_config, overrides_path):
    """Lo que cambie en el repositorio llega tras reconstruir la imagen."""
    CR.save_full_config(_edited(CR.get_full_config()))

    new_base = json.loads(json.dumps(_BASE_CONFIG))
    new_base["appVersion"] = "2.0.0"
    new_base["general"]["publicUrl"] = "https://changed.test"
    isolated_config.write_text(json.dumps(new_base), encoding="utf-8")
    CR.reload()
    CR._configs_path = isolated_config

    config = CR.get_full_config()
    assert config["appVersion"] == "2.0.0"
    assert config["general"]["publicUrl"] == "https://changed.test"
    assert config["general"]["launch"]["mode"] == "public"


def test_an_edited_list_replaces_the_whole_list(overrides_path):
    edited = CR.get_full_config()
    edited = json.loads(json.dumps(edited))
    edited["features"]["themis"]["prompts"] = ["uno"]

    CR.save_full_config(edited)

    assert CR.get_full_config()["features"]["themis"]["prompts"] == ["uno"]


def test_saving_the_base_unchanged_leaves_an_empty_overrides_file(overrides_path):
    CR.save_full_config(CR.get_full_config())

    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {}


def test_an_unreadable_overrides_file_keeps_the_previous_config(overrides_path):
    CR.get_full_config()
    overrides_path.parent.mkdir(parents=True)
    overrides_path.write_text("{ a medio escribir", encoding="utf-8")

    assert CR.reload_if_changed() is False
    assert CR.launch_config().mode is CR.LaunchMode.PREVIEW


def test_an_empty_variable_counts_as_undefined(isolated_config, monkeypatch):
    monkeypatch.setenv(CR.CONFIG_OVERRIDES_ENV, "  ")

    CR.save_full_config(_edited(CR.get_full_config()))

    on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert on_disk["general"]["launch"]["mode"] == "public"
