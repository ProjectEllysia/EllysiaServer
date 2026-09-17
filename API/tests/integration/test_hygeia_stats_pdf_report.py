"""
Tests del informe PDF de estadísticas de Hygeia (documento ``stats-pdf``).

No repite las garantías de acceso del CSV (misma validación,
``_build_stats_csv_parameters``, ya cubierta por
``test_hygeia_stats_export.py``): lo que comprueba este fichero es lo propio
del PDF — que se genera sin reventar para cada juego de datos, que un alcance
sin datos produce un documento que lo dice y no un error ni una página en
blanco, y que el texto impreso nombra lo que tiene que nombrar. La lectura del
texto se salta sola si no hay ``pypdf`` instalado (no está en
``requirements.txt``, igual que en ``test_hygeia_inventory_report.py``).
"""

import io
import secrets
from datetime import timedelta
from unittest import mock

import pytest

from src.modules.features.hygeia.managers import HygeiaDocumentManager
from src.modules.features.hygeia.model import AssetSnapshot, MonitoredAsset, UserTag
from src.modules.features.hygeia.repositories import (
    AssetSnapshotRepository,
    HygeiaTagRepository,
    MonitoredAssetRepository,
)
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.system.taskqueue import TaskQueue

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


def _export(client, headers: dict, **request):
    """Pide el PDF como lo hace el panel y devuelve la respuesta de la descarga.

    Pide el documento ``stats-pdf``, ejecuta su generación como haría el
    worker y descarga el fichero.

    Args:
        client: Cliente HTTP de test.
        headers: Cabeceras de autenticación.
        **request: Campos de ``POST /hygeia/documents`` además de ``kind``
            (``dataset``, ``assetId``, ``metrics``, ``period``…).

    Returns:
        La respuesta de ``GET /hygeia/documents/<id>/download`` si se aceptó
        la petición, o la propia respuesta de la petición si se rechazó.
    """
    created = client.post(
        "/hygeia/documents", json={"kind": "stats-pdf", **request}, headers=headers,
    )
    if created.status_code != 202:
        return created
    document_id = created.get_json()["id"]
    HygeiaDocumentManager.execute_document_generation(document_id)
    return client.get(f"/hygeia/documents/{document_id}/download", headers=headers)


def _pdf_text(data: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture()
def asset_with_history(app, regular_user):
    """Un activo con cuatro latidos de CPU y memoria en la última hora."""
    asset_id = _create_asset(app, regular_user.id)
    _seed(app, asset_id, [
        (timedelta(minutes=40), {"cpu_pct": 10.0, "mem_pct": 60.0}),
        (timedelta(minutes=30), {"cpu_pct": 50.0, "mem_pct": 62.0}),
        (timedelta(minutes=20), {"cpu_pct": 30.0, "mem_pct": 64.0}),
        (timedelta(minutes=10), {"cpu_pct": 20.0, "mem_pct": 66.0}),
    ])
    return asset_id


# =============================================================================
# LOS CUATRO JUEGOS DE DATOS SE GENERAN SIN REVENTAR
# =============================================================================

def test_the_asset_summary_returns_a_pdf(client, asset_with_history, regular_user, auth_headers):
    resp = _export(
        client, auth_headers(regular_user),
        dataset="summary", assetId=asset_with_history, period="24h",
    )

    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"


def test_the_tag_stats_return_a_pdf(app, client, asset_with_history, regular_user, auth_headers):
    tag_id = _tag_asset(app, regular_user.id, asset_with_history)

    resp = _export(client, auth_headers(regular_user), dataset="tag-stats", tagId=tag_id)

    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_the_ranking_returns_a_pdf(app, client, regular_user, auth_headers):
    for position, cpu in enumerate([90.0, 50.0, 10.0], start=1):
        asset_id = _create_asset(app, regular_user.id, f"host-{position}")
        _seed(app, asset_id, [(timedelta(minutes=10), {"cpu_pct": cpu})])

    resp = _export(client, auth_headers(regular_user), dataset="ranking", metric="cpuPct")

    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_the_overview_returns_a_pdf(client, regular_user, auth_headers):
    resp = _export(client, auth_headers(regular_user), dataset="overview")

    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_the_pdf_is_served_as_a_download(
    client, asset_with_history, regular_user, auth_headers,
):
    """Llega como fichero adjunto, con un nombre que dice qué es y de qué formato."""
    resp = _export(
        client, auth_headers(regular_user),
        dataset="summary", assetId=asset_with_history, period="7d",
    )

    assert "attachment" in resp.headers["Content-Disposition"]
    assert "hygeia-summary-host-export-7d.pdf" in resp.headers["Content-Disposition"]


# =============================================================================
# UN ALCANCE SIN DATOS LO DICE, NO REVIENTA
# =============================================================================

def test_a_metric_without_samples_still_produces_a_document(
    client, asset_with_history, regular_user, auth_headers,
):
    resp = _export(
        client, auth_headers(regular_user),
        dataset="summary", assetId=asset_with_history, metrics=["powerWatts"],
    )

    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_an_asset_without_any_history_still_produces_a_document(
    app, client, regular_user, auth_headers,
):
    """Un activo recién dado de alta, sin snapshots, trae una fila por
    métrica igual que uno con historial — solo que con guiones en vez de
    cifras (``get_stats_summary`` siempre responde por métrica pedida, tenga
    o no muestras) — y el PDF no falla al maquetarlas."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname="recien-llegado", agent_key_id=secrets.token_hex(8),
                agent_key_hash="dummy", heartbeat_interval_sec=15, user_id=regular_user.id,
                status="pending",
            )
            MonitoredAssetRepository(uow).save(asset)
            asset_id = asset.id

    resp = _export(
        client, auth_headers(regular_user), dataset="summary", assetId=asset_id, period="24h",
    )

    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"
    text = _pdf_text(resp.data)
    assert "recien-llegado" in text
    assert "cpuPct" in text


def test_a_ranking_without_matching_assets_says_so_in_the_pdf(client, regular_user, auth_headers):
    """Sin activos con la métrica pedida, el ranking está vacío: se declara,
    no se cuelga en una tabla de cero filas."""
    resp = _export(client, auth_headers(regular_user), dataset="ranking", metric="cpuPct")

    assert resp.status_code == 200
    text = _pdf_text(resp.data)
    assert "No hay datos" in text


# =============================================================================
# EL TEXTO DICE LO QUE TIENE QUE DECIR
# =============================================================================

def test_the_summary_pdf_names_the_asset_and_its_metrics(
    client, asset_with_history, regular_user, auth_headers,
):
    resp = _export(
        client, auth_headers(regular_user),
        dataset="summary", assetId=asset_with_history, period="24h",
    )
    text = _pdf_text(resp.data)

    assert "host-export" in text
    assert "cpuPct" in text


def test_the_tag_pdf_names_the_tag(app, client, asset_with_history, regular_user, auth_headers):
    tag_id = _tag_asset(app, regular_user.id, asset_with_history, name="produccion")

    resp = _export(client, auth_headers(regular_user), dataset="tag-stats", tagId=tag_id)
    text = _pdf_text(resp.data)

    assert "produccion" in text


def test_the_ranking_pdf_names_every_asset_in_order(app, client, regular_user, auth_headers):
    for position, cpu in enumerate([90.0, 50.0, 10.0], start=1):
        asset_id = _create_asset(app, regular_user.id, f"host-{position}")
        _seed(app, asset_id, [(timedelta(minutes=10), {"cpu_pct": cpu})])

    resp = _export(client, auth_headers(regular_user), dataset="ranking", metric="cpuPct")
    text = _pdf_text(resp.data)

    assert text.index("host-1") < text.index("host-2") < text.index("host-3")
