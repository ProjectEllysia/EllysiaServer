"""
Tests de integración de la exportación en CSV de las estadísticas de Hygeia
(documentos ``stats-csv``: el resumen de un activo, las métricas de una
etiqueta, el ranking del parque y el panorama).

Lo que estos tests atan es el criterio de cierre de la necesidad: **el CSV
contiene exactamente los mismos valores que la respuesta JSON de la misma
consulta**. Por eso casi todos piden las dos cosas y comparan celda a celda, en
vez de comprobar el CSV contra valores escritos a mano — un valor escrito a
mano en el test podría coincidir con el CSV y no con el JSON, que es justo la
divergencia que hay que impedir.

El CSV se genera en segundo plano: cada exportación pide el documento, ejecuta
su trabajo llamando al punto de entrada del worker y descarga el fichero.
"""

import csv
import io
import secrets
from datetime import timedelta
from unittest import mock

import pytest

from src.modules.features.hygeia.managers import HygeiaDocumentManager
from src.modules.system.taskqueue import TaskQueue

from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset, UserTag
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    HygeiaTagRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


class _FakeTaskQueue:
    """Doble de la cola que acepta el trabajo sin tocar Redis."""

    def submit(self, **kwargs):
        """Descarta el trabajo: el test lo ejecuta a mano."""


@pytest.fixture(autouse=True)
def fake_task_queue():
    """Sustituye la cola compartida por el doble en todo el fichero."""
    with mock.patch.object(TaskQueue, "get_instance", return_value=_FakeTaskQueue()):
        yield


@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    """Dirige los ficheros generados a un directorio temporal."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))


def _create_asset(app, user_id: int, hostname: str = "host-export") -> int:
    """Da de alta un activo en línea del usuario y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, user_id=user_id, status="online",
                last_seen_at=utcnow_naive(), uptime_sec=3600,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _tag_asset(app, user_id: int, asset_id: int, name: str = "produccion") -> int:
    """Crea una etiqueta personal, se la pone al activo y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            tag = UserTag(name=name, color="blue", user_id=user_id)
            HygeiaTagRepository(uow).save(tag)
            asset_repo = MonitoredAssetRepository(uow)
            asset = asset_repo.get_by_id(asset_id)
            asset.tags.append(tag)
            asset_repo.update(asset)
            return tag.id


def _seed(app, asset_id: int, readings: list) -> None:
    """Guarda un snapshot por cada ``(antigüedad, columnas)``."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetSnapshotRepository(uow)
            now = utcnow_naive()
            for age, columns in readings:
                instant = now - age
                repo.save(AssetSnapshot(
                    asset_id=asset_id, collected_at=instant, received_at=instant,
                    metrics={}, **columns,
                ))


def _export(client, headers: dict, **request) -> object:
    """Exporta a CSV como lo hace el panel y devuelve la respuesta de la descarga.

    Pide el documento ``stats-csv``, ejecuta su generación como haría el worker
    y descarga el fichero.

    Args:
        client: Cliente HTTP de test.
        headers: Cabeceras de autenticación.
        **request: Campos de ``POST /hygeia/documents`` además de ``kind``
            (``dataset``, ``assetId``, ``metrics``, ``period``…).

    Returns:
        La respuesta de ``GET /hygeia/documents/<id>/download``.
    """
    created = client.post(
        "/hygeia/documents", json={"kind": "stats-csv", **request}, headers=headers,
    )
    assert created.status_code == 202, created.get_json()
    document_id = created.get_json()["id"]
    HygeiaDocumentManager.execute_document_generation(document_id)
    return client.get(f"/hygeia/documents/{document_id}/download", headers=headers)


def _rows(response) -> list:
    """Lee el CSV de una respuesta como lista de filas.

    El fichero viaja en UTF-8 con BOM para que Excel no destroce los acentos,
    así que se decodifica con ``utf-8-sig``: eso consume el BOM y deja el
    primer nombre de columna limpio.
    """
    text = response.data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def _as_text(value) -> str:
    """El valor de un JSON tal como debe aparecer en una celda del CSV."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


@pytest.fixture()
def asset_with_history(app, regular_user):
    """Un activo con cuatro latidos de CPU, memoria y disco en la última hora."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [
        (timedelta(minutes=40), {"cpu_pct": 10.0, "mem_pct": 60.0, "disk_max_pct": 70.0}),
        (timedelta(minutes=30), {"cpu_pct": 50.0, "mem_pct": 62.0, "disk_max_pct": 70.0}),
        (timedelta(minutes=20), {"cpu_pct": 30.0, "mem_pct": 64.0, "disk_max_pct": 71.0}),
        (timedelta(minutes=10), {"cpu_pct": 20.0, "mem_pct": 66.0, "disk_max_pct": 72.0}),
    ])
    return asset_id


# =============================================================================
# EL RESUMEN DE UN ACTIVO
# =============================================================================

def test_the_summary_csv_holds_the_same_values_as_its_json(
    client, asset_with_history, regular_user, auth_headers,
):
    """Cada celda del CSV es el valor que trae el JSON para esa métrica.

    Es el criterio de cierre de la necesidad, comprobado sobre las dos
    respuestas de la misma consulta en vez de contra cifras escritas a mano.
    """
    headers = auth_headers(regular_user)
    path = f"/hygeia/assets/{asset_with_history}/stats/summary"

    as_json = client.get(path, query_string={"period": "24h"}, headers=headers).get_json()
    as_csv = _export(
        client, headers, dataset="summary", assetId=asset_with_history, period="24h",
    )

    rows = _rows(as_csv)
    header = rows[0]
    by_metric = {row[0]: dict(zip(header, row)) for row in rows[1:]}

    assert set(by_metric) == set(as_json["metrics"])
    for name, summary in as_json["metrics"].items():
        for column in ("min", "avg", "p95", "max", "current", "sampleCount"):
            assert by_metric[name][column] == _as_text(summary[column]), f"{name}.{column}"


def test_the_summary_csv_carries_the_covered_window_on_every_row(
    client, asset_with_history, regular_user, auth_headers,
):
    """La ventana cubierta viaja en cada fila, no se pierde al exportar.

    Un «máximo de los últimos 30 días» calculado sobre menos tiene que poder
    decirse también en la hoja de cálculo.

    La ventana se compara dentro de la propia respuesta y no contra la del
    JSON: las dos se calculan desde el instante de su petición, así que dos
    llamadas separadas por milisegundos dan ventanas que difieren en
    milisegundos. Lo que el CSV tiene que garantizar es que todas sus filas
    hablen de la misma ventana, y que el recorte se declare.
    """
    headers = auth_headers(regular_user)
    path = f"/hygeia/assets/{asset_with_history}/stats/summary"

    as_json = client.get(path, query_string={"period": "365d"}, headers=headers).get_json()
    rows = _rows(_export(
        client, headers, dataset="summary", assetId=asset_with_history, period="365d",
    ))

    header = rows[0]
    assert as_json["isPeriodClipped"] is True
    windows = {
        tuple(dict(zip(header, row))[column] for column in
              ("periodCoveredFrom", "periodCoveredTo", "isPeriodClipped"))
        for row in rows[1:]
    }
    assert len(windows) == 1, "cada fila declara una ventana distinta"
    covered_from, covered_to, is_clipped = windows.pop()
    assert is_clipped == "true"
    assert covered_from and covered_to
    # La ventana recortada abarca la retención, no el año pedido.
    assert covered_from[:4] == covered_to[:4]


def test_a_metric_without_samples_exports_empty_cells_and_not_zeros(
    client, asset_with_history, regular_user, auth_headers,
):
    """Una métrica sin datos deja celdas vacías, nunca ceros.

    Un cero en una hoja de cálculo se promedia y se grafica como un dato real;
    la celda vacía es lo que una hoja entiende como «sin dato», que es lo que
    significa.
    """
    rows = _rows(_export(
        client, auth_headers(regular_user),
        dataset="summary", assetId=asset_with_history, metrics=["powerWatts"],
    ))

    cells = dict(zip(rows[0], rows[1]))
    assert cells["metric"] == "powerWatts"
    assert cells["max"] == ""
    assert cells["avg"] == ""
    assert cells["sampleCount"] == "0"


def test_the_summary_csv_is_served_as_a_download(
    client, asset_with_history, regular_user, auth_headers,
):
    """Llega como fichero adjunto, con tipo CSV y un nombre que dice qué es."""
    response = _export(
        client, auth_headers(regular_user),
        dataset="summary", assetId=asset_with_history, period="7d",
    )

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "hygeia-summary-host-export-7d.csv" in response.headers["Content-Disposition"]


def test_the_summary_csv_starts_with_a_byte_order_mark(
    client, asset_with_history, regular_user, auth_headers,
):
    """El fichero lleva BOM: sin él, Excel destroza los acentos."""
    response = _export(
        client, auth_headers(regular_user), dataset="summary", assetId=asset_with_history,
    )

    assert response.data.startswith(b"\xef\xbb\xbf")


def test_the_stats_endpoints_no_longer_serve_csv(
    client, asset_with_history, regular_user, auth_headers,
):
    """La ruta de estadísticas responde JSON: el CSV solo sale como documento."""
    response = client.get(
        f"/hygeia/assets/{asset_with_history}/stats/summary",
        query_string={"format": "csv"}, headers=auth_headers(regular_user),
    )

    assert response.mimetype == "application/json"


# =============================================================================
# LAS MÉTRICAS DE UNA ETIQUETA
# =============================================================================

def test_the_tag_csv_holds_the_same_values_as_its_json(
    app, client, asset_with_history, regular_user, auth_headers,
):
    """El CSV de una etiqueta repite los valores agregados de su JSON."""
    tag_id = _tag_asset(app, regular_user.id, asset_with_history)
    headers = auth_headers(regular_user)
    path = f"/hygeia/stats/by-tag/{tag_id}"

    as_json = client.get(path, headers=headers).get_json()
    rows = _rows(_export(client, headers, dataset="tag-stats", tagId=tag_id))

    header = rows[0]
    by_metric = {dict(zip(header, row))["metric"]: dict(zip(header, row)) for row in rows[1:]}
    assert set(by_metric) == set(as_json["metrics"])
    for name, aggregate in as_json["metrics"].items():
        assert by_metric[name]["value"] == _as_text(aggregate["value"])
        assert by_metric[name]["unit"] == aggregate["unit"]
        assert by_metric[name]["assetsWithData"] == _as_text(aggregate["assetsWithData"])


def test_the_tag_csv_names_its_tag_on_every_row(
    app, client, asset_with_history, regular_user, auth_headers,
):
    """La etiqueta se repite en cada fila, para poder juntar dos descargas.

    Sin ese par de columnas, dos exportaciones pegadas en la misma hoja serían
    indistinguibles entre sí.
    """
    tag_id = _tag_asset(app, regular_user.id, asset_with_history, name="produccion")
    rows = _rows(_export(client, auth_headers(regular_user), dataset="tag-stats", tagId=tag_id))

    header = rows[0]
    assert all(dict(zip(header, row))["tagName"] == "produccion" for row in rows[1:])
    assert all(dict(zip(header, row))["tagId"] == str(tag_id) for row in rows[1:])


# =============================================================================
# EL RANKING DEL PARQUE
# =============================================================================

def test_the_ranking_csv_holds_the_same_values_as_its_json(
    app, client, regular_user, auth_headers,
):
    """El CSV del ranking repite activo por activo lo que dice su JSON."""
    for position, cpu in enumerate([90.0, 50.0, 10.0], start=1):
        asset_id = _create_asset(app, regular_user.id, f"host-{position}")
        _seed(app, asset_id, [(timedelta(minutes=10), {"cpu_pct": cpu})])

    headers = auth_headers(regular_user)
    query = {"metric": "cpuPct", "agg": "avg", "order": "desc", "limit": 10}

    as_json = client.get("/hygeia/stats/ranking", query_string=query, headers=headers).get_json()
    rows = _rows(_export(client, headers, dataset="ranking", **query))

    header = rows[0]
    exported = [dict(zip(header, row)) for row in rows[1:]]
    assert len(exported) == len(as_json["assets"])
    for entry, cells in zip(as_json["assets"], exported):
        assert cells["hostname"] == entry["hostname"]
        assert cells["assetId"] == _as_text(entry["assetId"])
        assert cells["value"] == _as_text(entry["value"])
        assert cells["sampleCount"] == _as_text(entry["sampleCount"])


def test_the_ranking_csv_writes_the_position_down(app, client, regular_user, auth_headers):
    """La posición se escribe porque una hoja de cálculo reordena en dos clics.

    Sin ella, el orden que decidió el servidor —que es lo que significa
    «ranking»— se perdería en cuanto alguien ordenase por hostname.
    """
    for position, cpu in enumerate([90.0, 50.0, 10.0], start=1):
        asset_id = _create_asset(app, regular_user.id, f"host-{position}")
        _seed(app, asset_id, [(timedelta(minutes=10), {"cpu_pct": cpu})])

    rows = _rows(_export(client, auth_headers(regular_user), dataset="ranking", metric="cpuPct"))

    header = rows[0]
    assert [dict(zip(header, row))["position"] for row in rows[1:]] == ["1", "2", "3"]


# =============================================================================
# EL PANORAMA DEL PARQUE
# =============================================================================

def test_the_overview_csv_holds_the_same_values_as_its_json(
    app, client, asset_with_history, regular_user, auth_headers,
):
    """El panorama se vuelca como medida y valor, con las cifras de su JSON.

    Es una foto del estado actual con recuentos de naturalezas distintas, así
    que la tabla de dos columnas es la forma honesta: forzar una fila ancha
    obligaría a inventar un nombre de columna por cada clave anidada.
    """
    headers = auth_headers(regular_user)

    as_json = client.get("/hygeia/stats/overview", headers=headers).get_json()
    rows = _rows(_export(client, headers, dataset="overview"))

    assert rows[0] == ["measure", "value"]
    measures = dict(rows[1:])
    assert measures["assetCount"] == _as_text(as_json["assetCount"])
    assert measures["acknowledgedAnomalyCount"] == _as_text(as_json["acknowledgedAnomalyCount"])
    for status, count in as_json["assetsByStatus"].items():
        assert measures[f"assetsByStatus.{status}"] == _as_text(count)
    for severity, count in as_json["openAnomaliesBySeverity"].items():
        assert measures[f"openAnomaliesBySeverity.{severity}"] == _as_text(count)


def test_the_overview_csv_has_no_window_columns(client, regular_user, auth_headers):
    """El panorama no tiene periodo, así que no inventa columnas de ventana."""
    rows = _rows(_export(client, auth_headers(regular_user), dataset="overview"))

    assert "periodCoveredFrom" not in rows[0]
