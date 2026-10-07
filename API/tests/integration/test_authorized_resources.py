"""Autorización de objetivos que no son IP: dominios y recursos cloud.

El registro de objetivos autorizados pasa a aceptar, además de IP/CIDR, un
dominio (que se autoriza a sí mismo y a sus subdominios) y un recurso cloud
(que se autoriza sólo a sí mismo). Estos tests fijan que cada forma autoriza lo
que debe y nada más, contra una base de datos real.
"""

import pytest

from src.modules.features.themis.managers import AuthorizedTargetManager
from src.modules.features.themis.managers.authorized_target import AUTHORIZATION_DECLARATION_VERSION

pytestmark = pytest.mark.integration


#: Cuerpo mínimo de la declaración que acompaña a todo objetivo que se autoriza.
DECLARATION = {"declarationAccepted": True, "declarationVersion": AUTHORIZATION_DECLARATION_VERSION}

def test_a_cloud_resource_is_authorized_only_after_it_is_declared(app, admin_user):
    manager = AuthorizedTargetManager()
    with app.app_context():
        # Sin declarar, no se toca.
        assert not manager.is_cloud_resource_authorized(admin_user.id, "s3:my-bucket")
        manager.add(admin_user.id, "s3:my-bucket")
        assert manager.is_cloud_resource_authorized(admin_user.id, "s3:my-bucket")
        # La comparación es por forma canónica: la misma en mayúsculas coincide.
        assert manager.is_cloud_resource_authorized(admin_user.id, "S3:My-Bucket")
        # Otro bucket declarado por nadie sigue sin estar autorizado.
        assert not manager.is_cloud_resource_authorized(admin_user.id, "s3:other-bucket")
        # Un recurso mal formado nunca está autorizado.
        assert not manager.is_cloud_resource_authorized(admin_user.id, "s3:")


def test_an_authorized_domain_covers_its_subdomains_but_not_siblings(app, admin_user):
    manager = AuthorizedTargetManager()
    with app.app_context():
        assert not manager.is_domain_authorized(admin_user.id, "example.com")
        manager.add(admin_user.id, "example.com")
        assert manager.is_domain_authorized(admin_user.id, "example.com")
        assert manager.is_domain_authorized(admin_user.id, "dev.example.com")
        # Ni un hermano ni un sufijo engañoso quedan cubiertos.
        assert not manager.is_domain_authorized(admin_user.id, "otro.com")
        assert not manager.is_domain_authorized(admin_user.id, "evil-example.com")


def test_a_cloud_or_domain_entry_never_authorizes_an_ip(app, admin_user):
    # Las tres formas autorizan cosas distintas: un bucket o un dominio en el
    # registro no deben colar una IP por la comprobación de red.
    manager = AuthorizedTargetManager()
    with app.app_context():
        manager.add(admin_user.id, "s3:my-bucket")
        manager.add(admin_user.id, "example.com")
        assert not manager.is_authorized(admin_user.id, "203.0.113.9")


def test_a_long_domain_can_be_registered_over_http(client, admin_user, auth_headers):
    # Un dominio puede tener hasta 253 caracteres y la columna guarda 255: el
    # formulario no puede quedarse en el tope de una dirección IP.
    long_domain = ".".join(["a" * 60, "b" * 60, "c" * 60, "example.com"])
    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": long_domain, **DECLARATION})
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["target"] == long_domain


def test_an_unrecognised_target_explains_the_three_accepted_shapes(client, admin_user, auth_headers):
    # El error nombra las tres formas con un ejemplo de cada una y viaja con su
    # clave de mensaje, para que la interfaz lo enseñe en el idioma activo.
    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": "no es nada", **DECLARATION})
    assert response.status_code == 400
    body = response.get_json()
    assert body["messageKey"] == "invalidAuthorizedTarget"
    assert body["params"] == {"target": "no es nada"}
    assert "example.com" in body["error_description"]


# ------------------------------------------- declaración del titular del sistema


def test_authorizing_a_target_requires_accepting_the_declaration(client, admin_user, auth_headers):
    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": "203.0.113.9", "declarationAccepted": False,
                                 "declarationVersion": AUTHORIZATION_DECLARATION_VERSION})

    assert response.status_code == 400
    assert response.get_json()["messageKey"] == "authorizationDeclarationRequired"
    assert client.get("/themis/authorized-targets",
                      headers=auth_headers(admin_user)).get_json()["targets"] == []


def test_the_declaration_fields_are_mandatory(client, admin_user, auth_headers):
    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": "203.0.113.9"})

    assert response.status_code in (400, 422)


def test_a_stale_declaration_version_is_rejected(client, admin_user, auth_headers):
    """Aceptar un texto que ya cambió no prueba nada: se pide leer el vigente."""
    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": "203.0.113.9", "declarationAccepted": True,
                                 "declarationVersion": "1999-01-01"})

    assert response.status_code == 409
    body = response.get_json()
    assert body["messageKey"] == "authorizationDeclarationOutdated"


def test_the_declaration_is_stored_with_its_version_and_the_ip(client, app, admin_user, auth_headers):
    from src.modules.features.themis.model import AuthorizedTarget
    from src.modules.infrastructure import UnitOfWork

    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": "203.0.113.9", **DECLARATION},
                           environ_overrides={"REMOTE_ADDR": "198.51.100.7"})
    assert response.status_code == 201, response.get_json()

    with app.app_context():
        with UnitOfWork() as uow:
            entry = uow.session.get(AuthorizedTarget, response.get_json()["targetId"])
            assert entry.declaration_version == AUTHORIZATION_DECLARATION_VERSION
            assert entry.declaration_ip == "198.51.100.7"
            assert entry.created_at is not None


def test_the_listing_shows_which_version_each_entry_was_declared_under(
    client, app, admin_user, auth_headers
):
    client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                json={"target": "203.0.113.9", **DECLARATION})
    with app.app_context():
        AuthorizedTargetManager().add(admin_user.id, "203.0.113.10")  # sin declaración: anterior a ella

    targets = {entry["target"]: entry["declarationVersion"]
               for entry in client.get("/themis/authorized-targets",
                                       headers=auth_headers(admin_user)).get_json()["targets"]}

    assert targets == {"203.0.113.9/32": AUTHORIZATION_DECLARATION_VERSION, "203.0.113.10/32": None}


def test_an_entry_without_declaration_still_authorizes_scans(app, admin_user):
    """Las entradas anteriores a la declaración siguen siendo válidas."""
    with app.app_context():
        AuthorizedTargetManager().add(admin_user.id, "203.0.113.10")
        assert AuthorizedTargetManager.is_authorized(admin_user.id, "203.0.113.10")
