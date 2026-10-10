"""Exportación de todos los datos de un usuario (RGPD, artículos 15 y 20).

Cubre tres cosas que no se pueden dejar al azar:

- **Que no falte nada**: un test recorre el grafo real de claves ajenas hacia
  ``User`` y exige que cada tabla esté exportada o declarada como no exportada,
  con motivo. Una tabla nueva sin decidir rompe aquí.
- **Que no sobre nada**: ninguna credencial ni secreto sale en el archivo, y un
  test recorre todas las columnas exportadas para impedir que uno nuevo se cuele.
- **El ciclo de vida del archivo**: se pide con la contraseña, se escribe, se
  descarga una sola vez y se borra, y no se puede pedir ni leer el de otro.
"""

import io
import json
import os
import zipfile
from datetime import timedelta
from unittest import mock

import pytest

from src.modules.infrastructure import unit_of_work
from src.modules.shared import Base, EncryptedText, utcnow_naive
from src.modules.users.managers import DATA_EXPORT_VALIDITY, DataExportManager, _run_export
from src.modules.users.model import DataExport
from src.modules.users.services.data_export import (
    NOT_EXPORTED_TABLES,
    export_modules,
    write_export_archive,
)

pytestmark = pytest.mark.integration

PASSWORD = "Secret123!"

#: Atributos cuyo nombre sugiere un secreto y que, revisados, sí se exportan.
#: La bóveda va cifrada tal cual (``vault_key``, ``salt``, ``checker`` son material
#: criptográfico del propio usuario que solo abre su contraseña maestra) y
#: ``key_id`` es el identificador público de un token, no su secreto.
REVIEWED_SENSITIVE_LOOKING = {
    ("Vault", "vault_key"), ("Vault", "salt"), ("Vault", "checker"),
    ("IrisIntegrationToken", "key_id"),
    ("MonitoredAsset", "agent_key_id"),
    ("IrisUrlExpansion", "url_sha256"), ("IrisAnalysis", "content_sha256"),
    # Fechas, banderas y claves internas de deduplicación: nombres que contienen
    # «password», «token» o «key» sin guardar ningún secreto.
    ("User", "password_changed_at"), ("User", "password_reset_expires_at"), ("User", "must_change_password"),
    ("Finding", "dedup_key"), ("IrisAnalysis", "integration_token_id"),
    ("EunomiaFrameworkAdoption", "framework_key"),
    ("IrisActionAudit", "idempotency_key"), ("IrisMailboxConnection", "access_token_expires_at"),
}

_SENSITIVE_FRAGMENTS = ("password", "secret", "token", "hash", "salt", "key", "sha256")


class _FakeQueue:
    """Cola en memoria: guarda lo publicado y responde a ``is_recoverable``."""

    def __init__(self, recoverable: bool = False):
        self.submitted: list[dict] = []
        self._recoverable = recoverable

    def submit(self, **kwargs):
        self.submitted.append(kwargs)
        return mock.Mock(id="job-1")

    def is_recoverable(self, external_id, category=None):
        return self._recoverable


@pytest.fixture()
def exports_dir(tmp_path, monkeypatch):
    """Redirige la carpeta de exportaciones a una temporal del test."""
    monkeypatch.setattr("src.modules.users.managers._exports_directory", lambda: tmp_path)
    return tmp_path


def _all_exported_tables() -> dict[str, list]:
    return {module: list(tables) for module, tables in export_modules().items()}


# ------------------------------------------------ que no falte ni sobre nada

def test_every_table_pointing_at_user_is_exported_or_declared_not_exported(app):
    """Recorre las claves ajenas hacia ``User``: una tabla nueva sin decidir rompe aquí."""
    from sqlalchemy import inspect as sa_inspect

    # Con herencia de tablas unidas (un informe de Themis es un ``Document``), exportar la
    # subclase exporta también las columnas de su tabla base.
    exported = {
        mapped.name
        for tables in export_modules().values()
        for table in tables
        for mapped in sa_inspect(table.model).tables
    }
    pointing_at_user = {
        table.name
        for table in Base.metadata.tables.values()
        if table.name != "User" and any(
            fk.column.table.name == "User" for column in table.columns for fk in column.foreign_keys
        )
    }

    assert not exported & set(NOT_EXPORTED_TABLES), "una tabla no puede estar exportada y no exportada"
    assert pointing_at_user - exported - set(NOT_EXPORTED_TABLES) == set()
    assert set(NOT_EXPORTED_TABLES) <= pointing_at_user, "NOT_EXPORTED_TABLES tiene una tabla que ya no existe"


def test_no_encrypted_column_is_exported(app):
    """Una columna cifrada se descifra al leerla: sacarla sería entregar el secreto en claro."""
    from sqlalchemy import inspect as sa_inspect

    leaks = []
    for module, tables in export_modules().items():
        for table in tables:
            mapper = sa_inspect(table.model)
            for attribute in mapper.column_attrs:
                is_encrypted = any(isinstance(column.type, EncryptedText) for column in attribute.columns)
                if is_encrypted and attribute.key not in table.exclude:
                    leaks.append(f"{module}.{table.name}.{attribute.key}")

    assert leaks == []


def test_no_column_that_looks_like_a_secret_is_exported_without_review(app):
    """Un nombre que suena a secreto (password, token, hash, key…) o se excluye o se revisa."""
    from sqlalchemy import inspect as sa_inspect

    unreviewed = []
    for module, tables in export_modules().items():
        for table in tables:
            for attribute in sa_inspect(table.model).column_attrs:
                key = attribute.key
                looks_sensitive = any(fragment in key.lower() for fragment in _SENSITIVE_FRAGMENTS)
                if looks_sensitive and key not in table.exclude \
                        and (table.model.__name__, key) not in REVIEWED_SENSITIVE_LOOKING:
                    unreviewed.append(f"{module}.{table.name}.{key}")

    assert unreviewed == []


# ------------------------------------------------ el contenido del archivo

def _seed(app, user_id: int) -> None:
    """Datos de varios módulos, incluidos secretos que no deben salir."""
    from src.modules.features.aegis.model import AegisDocument, Campaign, CampaignRecipient, DistributionList, Topic
    from src.modules.features.iris.model import IrisMailboxConnection
    from src.modules.features.themis.model import AuthorizedTarget

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            session = uow.session
            session.add(AuthorizedTarget(user_id=user_id, target="10.0.0.1/32", label="mi servidor"))
            session.add(IrisMailboxConnection(
                user_id=user_id, provider="gmail", account_email="yo@ejemplo.test",
                scopes="", refresh_token="REFRESH-SECRETO", access_token="ACCESS-SECRETO",
            ))
            topic = Topic(title="Phishing")
            lista = DistributionList(user_id=user_id, name="Plantilla")
            session.add_all([topic, lista])
            session.flush()
            document = AegisDocument(
                title="pildora", filename="/srv/interno/ruta-secreta.json", status="done", format="json",
                topic_id=topic.id, user_id=user_id,
            )
            session.add(document)
            session.flush()
            campaign = Campaign(user_id=user_id, document_id=document.id, list_id=lista.id, name="Campaña")
            session.add(campaign)
            session.flush()
            session.add(CampaignRecipient(
                campaign_id=campaign.id, recipient_email="empleado@empresa.test",
                recipient_name="Empleado", token="TOKEN-DEL-QUIZ",
            ))


def _build_archive(app, user_id: int, tmp_path) -> zipfile.ZipFile:
    destination = tmp_path / "datos.zip"
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            write_export_archive(uow.session, user_id, destination, utcnow_naive())
    return zipfile.ZipFile(destination)


def test_the_archive_holds_one_json_per_module_and_a_manifest(app, regular_user, tmp_path):
    archive = _build_archive(app, regular_user.id, tmp_path)

    assert set(archive.namelist()) == {
        "manifest.json", "profile.json", "accounts.json", "themis.json",
        "aegis.json", "iris.json", "hygeia.json", "acheron.json", "eunomia.json",
    }
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["userId"] == regular_user.id
    assert manifest["formatVersion"] == 1
    assert set(manifest["notIncluded"]) == set(NOT_EXPORTED_TABLES)
    # Todos los ficheros son JSON válido, también los de módulos sin datos.
    for name in archive.namelist():
        json.loads(archive.read(name))


def test_the_archive_holds_the_users_own_data(app, regular_user, tmp_path):
    _seed(app, regular_user.id)

    archive = _build_archive(app, regular_user.id, tmp_path)

    profile = json.loads(archive.read("profile.json"))
    assert profile["user"][0]["username"] == regular_user.username
    themis = json.loads(archive.read("themis.json"))
    assert [row["target"] for row in themis["authorized_targets"]] == ["10.0.0.1/32"]
    iris = json.loads(archive.read("iris.json"))
    assert iris["mailbox_connections"][0]["account_email"] == "yo@ejemplo.test"
    aegis = json.loads(archive.read("aegis.json"))
    assert aegis["campaign_recipients"][0]["recipient_email"] == "empleado@empresa.test"
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["modules"]["themis"]["authorized_targets"] == 1


def test_no_credential_or_secret_ends_up_in_the_archive(app, regular_user, tmp_path):
    """Lo que no se exporta no puede aparecer ni de refilón, en ningún fichero."""
    _seed(app, regular_user.id)

    archive = _build_archive(app, regular_user.id, tmp_path)
    everything = "".join(archive.read(name).decode("utf-8") for name in archive.namelist())

    for secret in ("REFRESH-SECRETO", "ACCESS-SECRETO", "TOKEN-DEL-QUIZ", "ruta-secreta"):
        assert secret not in everything
    user_row = json.loads(archive.read("profile.json"))["user"][0]
    assert not {"password_hash", "password_salt"} & set(user_row)


def test_the_archive_never_holds_another_users_data(app, regular_user, admin_user, tmp_path):
    _seed(app, admin_user.id)

    archive = _build_archive(app, regular_user.id, tmp_path)
    themis = json.loads(archive.read("themis.json"))
    iris = json.loads(archive.read("iris.json"))

    assert themis["authorized_targets"] == []
    assert iris["mailbox_connections"] == []
    assert json.loads(archive.read("profile.json"))["user"][0]["id"] == regular_user.id


def test_a_failed_write_leaves_no_partial_zip(app, regular_user, tmp_path):
    destination = tmp_path / "datos.zip"

    with app.app_context():
        with mock.patch("src.modules.users.services.data_export._write_module",
                        side_effect=RuntimeError("fallo")):
            with unit_of_work.UnitOfWork() as uow:
                with pytest.raises(RuntimeError):
                    write_export_archive(uow.session, regular_user.id, destination, utcnow_naive())

    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------ el ciclo de vida por HTTP

def _request(client, user, auth_headers, password=PASSWORD):
    return client.post("/users/me/export", headers=auth_headers(user), json={"password": password})


def _finish_export(app, export_id: int, exports_dir):
    """Ejecuta el cuerpo del job, como lo haría el worker."""
    with app.app_context():
        _run_export(export_id)


@pytest.fixture()
def queue():
    fake = _FakeQueue()
    with mock.patch("src.modules.users.managers.TaskQueue", create=True), \
         mock.patch("src.modules.system.taskqueue.TaskQueue.get_instance", return_value=fake):
        yield fake


def test_requesting_an_export_queues_it_and_returns_its_state(client, regular_user, auth_headers, queue, exports_dir):
    response = _request(client, regular_user, auth_headers)

    assert response.status_code == 202, response.get_json()
    body = response.get_json()
    assert body["status"] == "pending"
    assert body["expiresAt"] is None and body["sizeBytes"] is None
    assert len(queue.submitted) == 1
    assert queue.submitted[0]["category"] == "users.export"
    assert list(queue.submitted[0]["args"]) == [body["id"]]


def test_requesting_an_export_needs_the_current_password(client, regular_user, auth_headers, queue, exports_dir):
    response = _request(client, regular_user, auth_headers, password="otra-clave")

    assert response.status_code == 401
    assert queue.submitted == []


def test_a_second_request_while_one_is_running_is_rejected(client, regular_user, auth_headers, queue, exports_dir):
    assert _request(client, regular_user, auth_headers).status_code == 202

    second = _request(client, regular_user, auth_headers)

    assert second.status_code == 409
    assert second.get_json()["messageKey"] == "dataExportInProgress"


def test_a_finished_export_is_downloaded_once_and_its_file_is_deleted(
    client, app, regular_user, auth_headers, queue, exports_dir
):
    _seed(app, regular_user.id)
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]
    _finish_export(app, export_id, exports_dir)

    state = client.get("/users/me/export", headers=auth_headers(regular_user)).get_json()["export"]
    assert state["status"] == "done" and state["sizeBytes"] > 0 and state["expiresAt"] is not None

    first = client.get(f"/users/me/export/{export_id}/download", headers=auth_headers(regular_user))
    assert first.status_code == 200
    assert first.mimetype == "application/zip"
    assert first.headers["Cache-Control"] == "no-store"
    archive = zipfile.ZipFile(io.BytesIO(first.data))
    assert "manifest.json" in archive.namelist()
    # Leer la respuesta entera agota el generador, y su cierre borra el fichero.
    assert list(exports_dir.iterdir()) == []

    second = client.get(f"/users/me/export/{export_id}/download", headers=auth_headers(regular_user))
    assert second.status_code == 410
    assert second.get_json()["messageKey"] == "dataExportGone"


def test_downloading_before_it_is_ready_says_so(client, regular_user, auth_headers, queue, exports_dir):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]

    response = client.get(f"/users/me/export/{export_id}/download", headers=auth_headers(regular_user))

    assert response.status_code == 409
    assert response.get_json()["messageKey"] == "dataExportNotReady"


def test_nobody_can_download_someone_elses_export(
    client, app, regular_user, admin_user, auth_headers, queue, exports_dir
):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]
    _finish_export(app, export_id, exports_dir)

    response = client.get(f"/users/me/export/{export_id}/download", headers=auth_headers(admin_user))

    assert response.status_code == 404
    assert len(list(exports_dir.iterdir())) == 1  # el archivo del dueño sigue ahí


def test_the_latest_export_is_null_when_none_was_requested(client, regular_user, auth_headers):
    body = client.get("/users/me/export", headers=auth_headers(regular_user)).get_json()

    assert body == {"export": None}


def test_a_failed_job_marks_the_export_as_error_and_leaves_no_file(
    client, app, regular_user, auth_headers, queue, exports_dir
):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]

    with mock.patch("src.modules.users.services.data_export.write_export_archive",
                    side_effect=RuntimeError("disco lleno")):
        with pytest.raises(RuntimeError):
            _finish_export(app, export_id, exports_dir)

    state = client.get("/users/me/export", headers=auth_headers(regular_user)).get_json()["export"]
    assert state["status"] == "error"
    assert list(exports_dir.iterdir()) == []
    # Tras un fallo se puede volver a pedir.
    assert _request(client, regular_user, auth_headers).status_code == 202


def test_running_the_job_twice_does_not_write_two_files(
    client, app, regular_user, auth_headers, queue, exports_dir
):
    """La outbox publica «al menos una vez»: el segundo job no debe duplicar el trabajo."""
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]
    _finish_export(app, export_id, exports_dir)
    _finish_export(app, export_id, exports_dir)

    assert len(list(exports_dir.iterdir())) == 1


# ------------------------------------------------ caducidad y limpieza

def _age_export(app, export_id: int, delta: timedelta) -> None:
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            export = uow.session.get(DataExport, export_id)
            export.expires_at = utcnow_naive() - delta


def test_an_expired_export_cannot_be_downloaded_and_is_purged(
    client, app, regular_user, auth_headers, queue, exports_dir
):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]
    _finish_export(app, export_id, exports_dir)
    _age_export(app, export_id, timedelta(minutes=1))

    response = client.get(f"/users/me/export/{export_id}/download", headers=auth_headers(regular_user))
    assert response.status_code == 410

    with app.app_context():
        assert DataExportManager(task_queue=queue).purge_expired_exports() == 1
    assert list(exports_dir.iterdir()) == []
    state = client.get("/users/me/export", headers=auth_headers(regular_user)).get_json()["export"]
    assert state["status"] == "expired"


def test_an_unexpired_export_survives_the_purge(client, app, regular_user, auth_headers, queue, exports_dir):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]
    _finish_export(app, export_id, exports_dir)

    with app.app_context():
        assert DataExportManager(task_queue=queue).purge_expired_exports() == 0
    assert len(list(exports_dir.iterdir())) == 1


def test_the_purge_removes_old_files_no_export_claims(app, exports_dir, queue):
    stray = exports_dir / "export-99-abandonado.zip"
    stray.write_bytes(b"x")
    old = (utcnow_naive() - 3 * DATA_EXPORT_VALIDITY).timestamp()
    os.utime(stray, (old, old))
    recent = exports_dir / "export-98-reciente.zip"
    recent.write_bytes(b"x")

    with app.app_context():
        DataExportManager(task_queue=queue).purge_expired_exports()

    assert not stray.exists()
    assert recent.exists()


def test_startup_marks_orphaned_exports_as_error_but_respects_live_ones(
    client, app, regular_user, auth_headers, queue, exports_dir
):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]

    with app.app_context():
        assert DataExportManager(task_queue=_FakeQueue(recoverable=True)).reconcile_orphaned_exports() == 0
        assert DataExportManager(task_queue=_FakeQueue(recoverable=False)).reconcile_orphaned_exports() == 1

    state = client.get("/users/me/export", headers=auth_headers(regular_user)).get_json()["export"]
    assert state["id"] == export_id and state["status"] == "error"


# ------------------------------------------------ al borrar la cuenta

def test_deleting_the_account_removes_a_pending_export_and_its_file(
    client, app, regular_user, auth_headers, queue, exports_dir
):
    export_id = _request(client, regular_user, auth_headers).get_json()["id"]
    _finish_export(app, export_id, exports_dir)
    assert len(list(exports_dir.iterdir())) == 1

    response = client.delete("/users/me", headers=auth_headers(regular_user), json={"password": PASSWORD})

    assert response.status_code == 200
    assert list(exports_dir.iterdir()) == []
    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            assert uow.session.query(DataExport).count() == 0
