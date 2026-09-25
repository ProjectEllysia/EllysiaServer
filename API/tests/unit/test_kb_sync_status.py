"""El estado de sincronización de la base de conocimiento.

Toda la detección por versión del motor depende de un espejo local de NVD, KEV
y EPSS, y hasta ahora no había nada que registrara cuándo se refrescó cada uno.
Los modos de fallo eran todos silenciosos: el job lleva tres semanas fallando y
los escaneos siguen saliendo en verde contra un catálogo congelado, porque el
motor no tiene forma de saber que dejó de aprender.

Lo que se fija aquí es sobre todo **el camino de error**, que es el que importa:
una sincronización que funciona ya se notaba —los datos aparecían—, mientras que
una que falla no dejaba ningún rastro consultable.
"""

from __future__ import annotations

import pytest

from src.modules.features.themis.managers.kb_sync import KbSyncManager

pytestmark = pytest.mark.unit


class _FakeRepo:
    """Registra las llamadas a ``record_sync`` sin tocar la base de datos."""

    def __init__(self) -> None:
        self.calls: list = []

    def record_sync(self, source, rows_upserted=None, error=None):
        self.calls.append({"source": source, "rows": rows_upserted, "error": error})


@pytest.fixture(name="recorded")
def _recorded(monkeypatch):
    """Sustituye la escritura del estado por una lista en memoria."""
    repo = _FakeRepo()

    def fake_record(self, source, rows_upserted=None, error=None):
        repo.record_sync(source, rows_upserted, error)

    monkeypatch.setattr(KbSyncManager, "_record", fake_record)
    return repo


def test_a_successful_sync_is_recorded_with_its_row_count(recorded):
    manager = KbSyncManager()
    rows = manager._sync_source("kev", lambda: 42)  # pylint: disable=protected-access

    assert rows == 42
    assert recorded.calls == [{"source": "kev", "rows": 42, "error": None}]


def test_a_failed_sync_is_recorded_too(recorded):
    """El caso que da sentido a la tabla.

    Un intento con éxito ya se nota: aparecen datos nuevos. Uno que falla no
    dejaba nada más que una línea de log, así que una fuente rota podía estar
    semanas sin que nadie se enterase.
    """
    def boom():
        raise RuntimeError("404 desde el feed")

    manager = KbSyncManager()
    rows = manager._sync_source("nvd", boom)  # pylint: disable=protected-access

    assert rows is None, "un fallo no puede devolver un recuento"
    assert len(recorded.calls) == 1
    call = recorded.calls[0]
    assert call["source"] == "nvd"
    assert call["rows"] is None
    assert "404 desde el feed" in call["error"]
    assert "RuntimeError" in call["error"]


def test_a_failing_source_does_not_take_the_others_down(recorded, monkeypatch):
    """Una fuente rota debe costar una fuente, no tres.

    `sync_all` encadenaba las tres en línea recta, así que un fallo de KEV —una
    URL caída, un formato cambiado— se llevaba por delante a EPSS y a NVD, que
    no tienen nada que ver con ella. El resultado era que un feed de terceros
    caído congelaba la base de conocimiento entera.
    """
    import src.modules.system.config_reading as CR

    monkeypatch.setattr(
        CR, "knowledge_base_config",
        lambda: type("C", (), {
            "sources": {"kev": "u1", "epss": "u2", "nvd": "u3"},
            "nvd_window_days": 8,
            "nvd_api_key": None,
        })(),
    )

    def kev_boom(_url):
        raise RuntimeError("KEV caído")

    manager = KbSyncManager()
    monkeypatch.setattr(KbSyncManager, "sync_kev", lambda self, url: kev_boom(url))
    monkeypatch.setattr(KbSyncManager, "sync_epss", lambda self, url: 7)
    monkeypatch.setattr(KbSyncManager, "sync_nvd", lambda self, url, **kw: 9)
    monkeypatch.setattr(KbSyncManager, "rebuild_cpe_product_index", lambda self: 3)

    summary = manager.sync_all()

    assert summary["kev"] is None          # falló, y se sabe
    assert summary["epss"] == 7            # siguió adelante
    assert summary["nvd"] == 9
    assert summary["cpeProductAliases"] == 3
    assert [call["source"] for call in recorded.calls] == ["kev", "epss", "nvd"]


def test_the_alias_index_is_not_rebuilt_when_nvd_failed(recorded, monkeypatch):
    """El índice se deriva entero de las filas de NVD. Reconstruirlo tras un
    fallo gastaría una pasada sobre datos que no han cambiado."""
    import src.modules.system.config_reading as CR

    monkeypatch.setattr(
        CR, "knowledge_base_config",
        lambda: type("C", (), {
            "sources": {"nvd": "u3"}, "nvd_window_days": 8, "nvd_api_key": None,
        })(),
    )
    rebuilt = []
    monkeypatch.setattr(KbSyncManager, "sync_nvd",
                        lambda self, url, **kw: (_ for _ in ()).throw(RuntimeError("nope")))
    monkeypatch.setattr(KbSyncManager, "rebuild_cpe_product_index",
                        lambda self: rebuilt.append(True))

    summary = KbSyncManager().sync_all()

    assert summary["nvd"] is None
    assert "cpeProductAliases" not in summary
    assert rebuilt == []


def test_a_broken_oval_distribution_costs_only_that_distribution(recorded, monkeypatch):
    """Cada distribución OVAL se sincroniza y se registra por separado.

    El caso es el de producción: guardar la configuración desde la web partía
    la clave `ubuntu:20.04` por el punto y dejaba como «URL» un diccionario
    (`{"04": url}`). Con las seis distribuciones en una sola operación, eso
    tumbaba OVAL entero cada noche después de haber escrito Debian, y lo único
    registrado era un error de la librería HTTP que no nombraba la entrada.
    """
    import src.modules.system.config_reading as CR

    monkeypatch.setattr(
        CR, "knowledge_base_config",
        lambda: type("C", (), {"sources": {"oval": {
            "debian:12": "https://example.test/bookworm.xml.bz2",
            "ubuntu:20": {"04": "https://example.test/focal.xml.bz2"},
            "ubuntu:24.04": "https://example.test/noble.xml.bz2",
        }}})(),
    )
    import src.modules.features.themis.lybra as lybra
    monkeypatch.setattr(lybra, "fetch_oval", lambda url: b"<oval/>")
    monkeypatch.setattr(lybra, "parse_oval_definitions", lambda document, vendor, release: iter(()))

    summary = KbSyncManager().sync_all()

    assert summary == {"oval:debian:12": 0, "oval:ubuntu:20": None, "oval:ubuntu:24.04": 0}
    by_source = {call["source"]: call for call in recorded.calls}
    assert by_source["oval:debian:12"]["error"] is None
    assert by_source["oval:ubuntu:24.04"]["error"] is None
    error = by_source["oval:ubuntu:20"]["error"]
    assert "ubuntu:20" in error and "no es una URL" in error, error


def test_a_manual_sync_can_be_limited_to_one_source(recorded, monkeypatch):
    """El panel sincroniza una fuente suelta; las demás no se tocan."""
    import src.modules.system.config_reading as CR

    monkeypatch.setattr(
        CR, "knowledge_base_config",
        lambda: type("C", (), {
            "sources": {"kev": "u1", "epss": "u2", "nvd": "u3",
                        "oval": {"debian:12": "https://example.test/bookworm.xml.bz2"}},
            "nvd_window_days": 8, "nvd_api_key": None,
        })(),
    )
    monkeypatch.setattr(KbSyncManager, "sync_kev", lambda self, url: 1)
    monkeypatch.setattr(KbSyncManager, "sync_epss", lambda self, url: 2)
    monkeypatch.setattr(KbSyncManager, "sync_nvd", lambda self, url, **kw: 3)
    monkeypatch.setattr(KbSyncManager, "sync_oval", lambda self, key, url: 4)
    monkeypatch.setattr(KbSyncManager, "rebuild_cpe_product_index", lambda self: 5)

    assert KbSyncManager().sync_all(only="kev") == {"kev": 1}
    assert KbSyncManager().sync_all(only="oval") == {"oval:debian:12": 4}
    assert KbSyncManager().sync_all(only="nvd") == {"nvd": 3, "cpeProductAliases": 5}
