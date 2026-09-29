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
