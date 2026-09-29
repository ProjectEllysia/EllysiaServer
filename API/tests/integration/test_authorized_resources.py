"""Autorización de objetivos que no son IP: dominios y recursos cloud.

El registro de objetivos autorizados pasa a aceptar, además de IP/CIDR, un
dominio (que se autoriza a sí mismo y a sus subdominios) y un recurso cloud
(que se autoriza sólo a sí mismo). Estos tests fijan que cada forma autoriza lo
que debe y nada más, contra una base de datos real.
"""

import pytest

from src.modules.features.themis.managers import AuthorizedTargetManager

pytestmark = pytest.mark.integration


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
                           json={"target": long_domain})
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["target"] == long_domain


def test_an_unrecognised_target_explains_the_three_accepted_shapes(client, admin_user, auth_headers):
    # El error nombra las tres formas con un ejemplo de cada una y viaja con su
    # clave de mensaje, para que la interfaz lo enseñe en el idioma activo.
    response = client.post("/themis/authorized-targets", headers=auth_headers(admin_user),
                           json={"target": "no es nada"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["messageKey"] == "invalidAuthorizedTarget"
    assert body["params"] == {"target": "no es nada"}
    assert "example.com" in body["error_description"]
