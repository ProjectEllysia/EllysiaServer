"""Tests unitarios de la capa pura de exposición en la nube (``lybra/cloud.py``).

Cubre la gramática de un recurso cloud: qué formas se aceptan, cuáles se
rechazan y cómo se canonizan.
"""

import pytest

from src.modules.features.themis.lybra.cloud import CloudResource, parse_cloud_resource

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw, expected", [
    ("s3:my-bucket", "s3:my-bucket"),
    ("S3:My-Bucket", "s3:my-bucket"),          # se pasa a minúsculas
    ("  gcs:data.store  ", "gcs:data.store"),  # se recortan los bordes
    ("azure:account1/container-a", "azure:account1/container-a"),
    ("firebase:my-project-01", "firebase:my-project-01"),
])
def test_valid_resources_parse_to_their_canonical_form(raw, expected):
    resource = parse_cloud_resource(raw)
    assert resource is not None
    assert resource.canonical == expected


@pytest.mark.parametrize("raw", [
    "",                       # vacío
    "my-bucket",              # sin prefijo de proveedor
    "s3:",                    # sin identificador
    "ftp:whatever",           # proveedor desconocido
    "s3:ab",                  # bucket demasiado corto (< 3)
    "s3:UPPER",               # ya en minúsculas, pero las mayúsculas se bajan; esto es válido
    "azure:account",          # falta el contenedor
    "azure:ACCOUNT_TOO_LONG_FOR_AZURE_STORAGE/container",  # cuenta > 24
    "firebase:ab",            # proyecto demasiado corto
    "s3:-badstart",           # no puede empezar por guion
])
def test_invalid_resources_return_none(raw):
    # ``s3:UPPER`` se canoniza a ``s3:upper`` (5 chars, válido), así que lo
    # tratamos aparte: no debe ser None.
    if raw == "s3:UPPER":
        assert parse_cloud_resource(raw) == CloudResource("s3", "upper")
        return
    assert parse_cloud_resource(raw) is None


def test_azure_lowercases_both_account_and_container():
    resource = parse_cloud_resource("azure:MyAccount/MyContainer")
    assert resource == CloudResource("azure", "myaccount/mycontainer")
