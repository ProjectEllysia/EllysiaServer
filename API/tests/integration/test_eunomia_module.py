"""El módulo Eunomia está dado de alta en la aplicación."""

import pytest

pytestmark = pytest.mark.integration


def test_the_eunomia_blueprint_is_registered_under_its_prefix(client):
    assert "eunomia" in client.application.blueprints

