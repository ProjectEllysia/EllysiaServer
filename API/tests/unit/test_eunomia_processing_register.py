"""El registro de actividades de tratamiento cubre el contenido que fija el artículo 30.1 del RGPD."""

import pytest

from src.modules.features.eunomia.services.registers import get_register, validate_values
from src.modules.features.eunomia.services.documents.register_export import build_csv

pytestmark = pytest.mark.unit

#: Letra del art. 30.1 → campo de la ficha que la recoge.
_ARTICLE_30_1 = {
    "a": "joint_controller",   # el responsable y su contacto salen del perfil de empresa
    "b": "purposes",
    "c": ("data_subjects", "data_categories"),
    "d": "recipients",
    "e": "transfers",
    "f": "retention",
    "g": "security_measures",
}


@pytest.fixture(scope="module")
def register():
    found = get_register("rgpd-actividades-tratamiento")
    assert found is not None
    return found


def test_the_definition_has_a_field_for_every_letter_of_article_30_1(register):
    keys = {field.key for field in register.fields}
    needed = {key for value in _ARTICLE_30_1.values() for key in ((value,) if isinstance(value, str) else value)}

    assert needed <= keys


def test_the_example_records_meet_the_definition_and_are_the_five_expected(register):
    assert [example["name"] for example in register.examples] == [
        "Nóminas y personal", "Clientes", "Proveedores", "Videovigilancia", "Candidatos y selección de personal"]
    for example in register.examples:
        assert validate_values(register, example) == []


def test_the_export_includes_every_field_of_article_30_1(register):
    header = build_csv(register, []).decode("utf-8-sig").splitlines()[0]

    for label in ("Fines del tratamiento", "Categorías de interesados", "Categorías de datos personales",
                  "Categorías de destinatarios", "Transferencias internacionales", "Plazos de supresión",
                  "Medidas técnicas y organizativas de seguridad"):
        assert label in header


def test_the_register_is_evidence_of_article_30_of_the_catalog(register):
    assert register.controls == {"rgpd": ("art.30",)}
