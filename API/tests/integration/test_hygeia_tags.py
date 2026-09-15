"""
Tests de integración HTTP del etiquetado de activos de Hygeia.

Cubre lo que de verdad puede romperse en un sistema de etiquetas con dos
dueños distintos:

- que el catálogo común y el repositorio personal se vean como una sola lista,
  pero solo las propias se puedan borrar;
- que una etiqueta personal de otro usuario sea indistinguible de una
  inexistente (misma respuesta, sin enumerar catálogos ajenos);
- y sobre todo, que **borrar una etiqueta no borre los activos que la
  llevaban**, que es la garantía explícita del producto.

Los tests siembran sus propias ``SystemTag``: la suite crea el esquema con
``Base.metadata.create_all()`` y no pasa por Alembic, así que las 12 filas
que siembra la migración no existen aquí.
"""

import secrets
from datetime import datetime, timezone

import pytest

from src.modules.infrastructure import UnitOfWork
from src.modules.features.hygeia.model import MonitoredAsset, SystemTag, UserTag
from src.modules.features.hygeia.repositories import (
    HygeiaTagRepository,
    MonitoredAssetRepository,
)

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int, hostname: str = "tag-test") -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname,
                agent_key_id=secrets.token_hex(8),
                agent_key_hash="dummy",
                heartbeat_interval_sec=15,
                status="pending",
                user_id=user_id,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _create_system_tag(app, name: str = "Producción", color: str = "red") -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            tag = SystemTag(name=name, color=color)
            HygeiaTagRepository(uow).save(tag)
            return tag.id


def _create_user_tag(app, user_id: int, name: str, color: str = "slate") -> int:
    with app.app_context():
        with UnitOfWork() as uow:
            tag = UserTag(name=name, color=color, user_id=user_id)
            HygeiaTagRepository(uow).save(tag)
            return tag.id


def _asset_exists(app, asset_id: int) -> bool:
    with app.app_context():
        with UnitOfWork() as uow:
            return MonitoredAssetRepository(uow).get_by_id(asset_id) is not None


# ---------------------------------------------------------------------------
# Catálogo: qué ve cada usuario
# ---------------------------------------------------------------------------

def test_catalog_mixes_system_and_own_tags(app, client, regular_user, auth_headers):
    _create_system_tag(app)

    created = client.post(
        "/hygeia/tags",
        json={"name": "Mi etiqueta", "color": "blue"},
        headers=auth_headers(regular_user),
    )
    assert created.status_code == 201
    assert created.get_json()["tagType"] == "user"

    listed = client.get("/hygeia/tags", headers=auth_headers(regular_user))
    assert listed.status_code == 200

    tags = listed.get_json()["tags"]
    assert {tag["name"] for tag in tags} == {"Producción", "Mi etiqueta"}
    # Las de sistema primero: la lista sale ya agrupada de la base de datos.
    assert [tag["tagType"] for tag in tags] == ["system", "user"]


def test_personal_tags_of_other_users_are_invisible(app, client, make_user, auth_headers):
    owner = make_user()
    stranger = make_user()
    _create_user_tag(app, owner.id, "Solo mía")

    resp = client.get("/hygeia/tags", headers=auth_headers(stranger))

    assert resp.status_code == 200
    assert resp.get_json()["tags"] == []


def test_duplicate_name_is_rejected_ignoring_case(app, client, regular_user, auth_headers):
    client.post(
        "/hygeia/tags",
        json={"name": "Cocina", "color": "green"},
        headers=auth_headers(regular_user),
    )

    resp = client.post(
        "/hygeia/tags",
        json={"name": "  cocina  ", "color": "red"},
        headers=auth_headers(regular_user),
    )

    assert resp.status_code == 409


def test_cannot_shadow_a_system_tag_name(app, client, regular_user, auth_headers):
    _create_system_tag(app, "Backup", "slate")

    resp = client.post(
        "/hygeia/tags",
        json={"name": "backup"},
        headers=auth_headers(regular_user),
    )

    assert resp.status_code == 409


def test_color_outside_the_palette_is_rejected(client, regular_user, auth_headers):
    resp = client.post(
        "/hygeia/tags",
        json={"name": "Fucsia", "color": "#ff00ff"},
        headers=auth_headers(regular_user),
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Borrado: quién puede, y qué se lleva por delante
# ---------------------------------------------------------------------------

def test_system_tags_cannot_be_deleted(app, client, regular_user, auth_headers):
    tag_id = _create_system_tag(app)

    resp = client.delete(f"/hygeia/tags/{tag_id}", headers=auth_headers(regular_user))

    # 403 y no 404: la etiqueta existe y el usuario la ve, lo que no puede es
    # tocarla — el catálogo es común.
    assert resp.status_code == 403


def test_deleting_another_users_tag_is_indistinguishable_from_missing(
    app, client, make_user, auth_headers,
):
    owner = make_user()
    stranger = make_user()
    tag_id = _create_user_tag(app, owner.id, "Ajena")

    existing = client.delete(f"/hygeia/tags/{tag_id}", headers=auth_headers(stranger))
    missing = client.delete("/hygeia/tags/999999", headers=auth_headers(stranger))

    assert existing.status_code == 404
    assert missing.status_code == 404


def test_deleting_a_tag_keeps_the_assets_that_carried_it(
    app, client, regular_user, auth_headers,
):
    """La garantía explícita del producto: se van las asociaciones, no los activos."""
    asset_id = _create_asset(app, regular_user.id)
    tag_id = _create_user_tag(app, regular_user.id, "Efímera")

    assigned = client.put(
        f"/hygeia/assets/{asset_id}/tags",
        json={"tagIds": [tag_id]},
        headers=auth_headers(regular_user),
    )
    assert assigned.status_code == 200
    assert [tag["id"] for tag in assigned.get_json()["tags"]] == [tag_id]

    deleted = client.delete(f"/hygeia/tags/{tag_id}", headers=auth_headers(regular_user))
    assert deleted.status_code == 200

    assert _asset_exists(app, asset_id)
    asset = client.get(f"/hygeia/assets/{asset_id}", headers=auth_headers(regular_user))
    assert asset.status_code == 200
    assert asset.get_json()["tags"] == []


# ---------------------------------------------------------------------------
# Asignación
# ---------------------------------------------------------------------------

def test_assigning_tags_replaces_the_whole_set(app, client, regular_user, auth_headers):
    asset_id = _create_asset(app, regular_user.id)
    first = _create_user_tag(app, regular_user.id, "Primera")
    second = _create_user_tag(app, regular_user.id, "Segunda")

    client.put(
        f"/hygeia/assets/{asset_id}/tags",
        json={"tagIds": [first, second]},
        headers=auth_headers(regular_user),
    )
    resp = client.put(
        f"/hygeia/assets/{asset_id}/tags",
        json={"tagIds": [second]},
        headers=auth_headers(regular_user),
    )

    assert resp.status_code == 200
    assert [tag["id"] for tag in resp.get_json()["tags"]] == [second]


def test_cannot_assign_a_tag_owned_by_someone_else(app, client, make_user, auth_headers):
    owner = make_user()
    stranger = make_user()
    stranger_asset = _create_asset(app, stranger.id)
    owner_tag = _create_user_tag(app, owner.id, "Ajena")

    resp = client.put(
        f"/hygeia/assets/{stranger_asset}/tags",
        json={"tagIds": [owner_tag]},
        headers=auth_headers(stranger),
    )

    assert resp.status_code == 404


def test_cannot_tag_an_asset_owned_by_someone_else(app, client, make_user, auth_headers):
    owner = make_user()
    stranger = make_user()
    owner_asset = _create_asset(app, owner.id)
    stranger_tag = _create_user_tag(app, stranger.id, "Suya")

    resp = client.put(
        f"/hygeia/assets/{owner_asset}/tags",
        json={"tagIds": [stranger_tag]},
        headers=auth_headers(stranger),
    )

    assert resp.status_code == 404


def test_asset_count_only_counts_your_own_assets(app, client, make_user, auth_headers):
    owner = make_user()
    stranger = make_user()
    shared_tag = _create_system_tag(app, "Cloud", "teal")

    for user in (owner, stranger):
        asset_id = _create_asset(app, user.id, hostname=f"host-{user.id}")
        client.put(
            f"/hygeia/assets/{asset_id}/tags",
            json={"tagIds": [shared_tag]},
            headers=auth_headers(user),
        )

    resp = client.get("/hygeia/tags", headers=auth_headers(owner))

    # Uno, no dos: el recuento de una etiqueta compartida no puede delatar
    # cuántos activos ajenos la llevan.
    assert resp.get_json()["tags"][0]["assetCount"] == 1


# ---------------------------------------------------------------------------
# Invariante de modelo
# ---------------------------------------------------------------------------

def test_a_personal_tag_without_an_owner_is_rejected_by_the_database(app):
    """El CheckConstraint, no el manager: la regla vive en el esquema.

    Se espera ``SQLAlchemyError`` y no ``IntegrityError`` porque
    ``BaseRepository.save`` reenvuelve el error del driver; lo que importa
    aquí es que el ``INSERT`` no pasa, y el mensaje nombra la constraint.
    """
    from sqlalchemy.exc import SQLAlchemyError

    with app.app_context():
        with pytest.raises(SQLAlchemyError, match="ck_hygeiatag_owner"):
            with UnitOfWork() as uow:
                HygeiaTagRepository(uow).save(UserTag(name="Huérfana", color="slate"))


# ---------------------------------------------------------------------------
# Catálogo: última actividad de cada etiqueta
# ---------------------------------------------------------------------------

def _set_last_seen(app, asset_id: int, last_seen_at) -> None:
    """Fija la última señal de un activo, como si hubiera latido en ese instante."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = MonitoredAssetRepository(uow)
            asset = repo.get_by_id(asset_id)
            asset.last_seen_at = last_seen_at
            repo.update(asset)


def _parse_utc(text: str):
    """Convierte un instante ISO de la API (``Z`` o ``+00:00``) en naive-UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def test_catalog_reports_the_last_activity_of_your_own_assets(app, client, make_user, auth_headers):
    """``lastActivityAt`` es la última señal del activo más reciente del usuario, no de uno ajeno."""
    owner = make_user()
    stranger = make_user()
    shared_tag = _create_system_tag(app, "Cloud", "teal")
    older = _create_asset(app, owner.id, hostname="older")
    newer = _create_asset(app, owner.id, hostname="newer")
    foreign = _create_asset(app, stranger.id, hostname="foreign")
    _set_last_seen(app, older, datetime(2026, 9, 1, 8, 0, 0))
    _set_last_seen(app, newer, datetime(2026, 9, 1, 9, 30, 0))
    _set_last_seen(app, foreign, datetime(2026, 9, 1, 23, 0, 0))
    for user, asset_id in ((owner, older), (owner, newer), (stranger, foreign)):
        client.put(
            f"/hygeia/assets/{asset_id}/tags", json={"tagIds": [shared_tag]},
            headers=auth_headers(user),
        )

    tag = client.get("/hygeia/tags", headers=auth_headers(owner)).get_json()["tags"][0]

    assert tag["assetCount"] == 2
    # La del activo ajeno es más reciente, pero delataría cuándo estuvo
    # encendido un servidor de otro usuario: no cuenta.
    assert _parse_utc(tag["lastActivityAt"]) == datetime(2026, 9, 1, 9, 30, 0)


def test_a_tag_without_activity_has_no_last_activity(app, client, regular_user, auth_headers):
    """Sin activos, o con activos que nunca han reportado, ``lastActivityAt`` es ``null``."""
    empty_tag = _create_user_tag(app, regular_user.id, "Vacía")
    silent_tag = _create_user_tag(app, regular_user.id, "Silenciosa")
    silent_asset = _create_asset(app, regular_user.id, hostname="never-reported")
    client.put(
        f"/hygeia/assets/{silent_asset}/tags", json={"tagIds": [silent_tag]},
        headers=auth_headers(regular_user),
    )

    tags = {
        tag["id"]: tag
        for tag in client.get("/hygeia/tags", headers=auth_headers(regular_user)).get_json()["tags"]
    }

    assert tags[empty_tag]["assetCount"] == 0
    assert tags[empty_tag]["lastActivityAt"] is None
    assert tags[silent_tag]["assetCount"] == 1
    assert tags[silent_tag]["lastActivityAt"] is None


def test_a_new_tag_starts_without_activity(client, regular_user, auth_headers):
    """El alta devuelve la etiqueta sin activos ni actividad."""
    created = client.post(
        "/hygeia/tags", json={"name": "Recién creada", "color": "green"},
        headers=auth_headers(regular_user),
    ).get_json()

    assert created["assetCount"] == 0
    assert created["lastActivityAt"] is None
