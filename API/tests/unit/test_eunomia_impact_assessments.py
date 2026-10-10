"""Registro de evaluaciones de impacto: el campo que enlaza con otro registro."""

import pytest

from src.modules.features.eunomia.services.catalog import CatalogFormatError
from src.modules.features.eunomia.services.registers import FIELD_RECORD, get_register, parse_register, validate_values

pytestmark = pytest.mark.unit


def test_the_impact_assessment_links_to_a_processing_activity():
    register = get_register("rgpd-evaluaciones-impacto")
    field = register.field("treatment")

    assert field.type == FIELD_RECORD and field.register == "rgpd-actividades-tratamiento"
    assert validate_values(register, {"name": "EIPD", "treatment": "abc", "trigger": "profiling"}) == ["treatment"]
    assert validate_values(register, {"name": "EIPD", "treatment": "7", "trigger": "profiling"}) == []


@pytest.mark.parametrize("field", [
    {"key": "link", "label": "Enlace", "type": "record"},
    {"key": "link", "label": "Enlace", "type": "record", "register": "demo"},
    {"key": "link", "label": "Enlace", "type": "text", "register": "otro"},
])
def test_a_record_field_needs_a_target_register_other_than_its_own(field):
    document = {"key": "demo", "version": "1", "title": "D", "summary": "s", "titleField": "name",
                "fields": [{"key": "name", "label": "N", "type": "text"}, field]}

    with pytest.raises(CatalogFormatError):
        parse_register(document)
