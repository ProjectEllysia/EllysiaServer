"""Las plantillas de documentos son datos validados contra el catálogo y el perfil de empresa."""

import copy
import json

import pytest

from src.modules.features.eunomia.services.catalog import CatalogFormatError
from src.modules.features.eunomia.services.templates import (
    TEMPLATES_ROOT,
    get_template,
    load_templates,
    parse_template,
    templates_for_control,
)

pytestmark = pytest.mark.unit


def _document():
    return json.loads((TEMPLATES_ROOT / "nis2" / "security-policy@1.json").read_text(encoding="utf-8"))


def test_the_four_first_templates_are_valid():
    assert {item.key for item in load_templates()} >= {
        "incident-procedure", "security-policy", "supplier-register", "continuity-plan"}


def test_a_template_knows_which_controls_it_helps_to_meet():
    keys = {item.key for item in templates_for_control("nis2", "23.4.b")}

    assert keys == {"incident-procedure", "incident-notification"}


def test_the_latest_version_is_the_one_returned_by_default():
    assert get_template("security-policy").version == "1"
    assert get_template("no-existe") is None


def test_the_incident_procedure_states_the_article_23_deadlines():
    body = " ".join(section.body for section in get_template("incident-procedure").sections)

    assert "24 horas" in body and "72 horas" in body and "un mes" in body


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["sections"].append({"heading": "x", "body": "{{sin_campo}}"}), "marcadores sin campo"),
    (lambda d: d["fields"].append({"key": "huerfano", "label": "x", "type": "text"}), "no usa"),
    (lambda d: d["fields"][0].update({"source": "company.noExiste"}), "dato de empresa"),
    (lambda d: d["fields"][0].update({"source": "assessment.RE.9.9.responsible"}), "origen que no existe"),
    (lambda d: d["controls"].append("no-existe"), "no existe o no es evaluable"),
    (lambda d: d["controls"].append("RE.3"), "no existe o no es evaluable"),
    (lambda d: d["fields"][0].update({"type": "rara"}), "tipo desconocido"),
    (lambda d: d["fields"].append(dict(d["fields"][0])), "repetido"),
])
def test_an_invalid_template_is_rejected(mutate, message):
    document = copy.deepcopy(_document())
    mutate(document)

    with pytest.raises(CatalogFormatError, match=message):
        parse_template(document, "nis2")


def test_the_gdpr_templates_are_valid_and_cover_their_articles():
    keys = {item.key for item in load_templates() if item.framework == "rgpd"}

    assert keys >= {"privacy-policy", "information-clause-direct", "information-clause-indirect",
                    "processor-agreement", "rights-procedure"}
    assert {t.key for t in templates_for_control("rgpd", "art.28")} == {"processor-agreement"}
    assert "processor-agreement" in {t.key for t in templates_for_control("rgpd", "art.32")}


def test_the_processor_agreement_states_every_minimum_content_of_article_28_3():
    template = get_template("processor-agreement")
    text = " ".join(section.body for section in template.sections)

    for expected in ("instrucciones documentadas", "confidencialidad", "artículo 32", "otro encargado",
                     "derechos de los interesados", "artículos 32 a 36", "auditorías", "infringe"):
        assert expected in text
