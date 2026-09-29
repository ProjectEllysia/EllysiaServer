"""Desviación de contacto: un remitente nuevo que imita a uno habitual.

Funciones puras de ``services/graph.py``: leer los participantes de un mensaje
y decidir si el remitente imita el nombre o la dirección de alguien con quien
el usuario habla a menudo. La construcción del grafo contra la base de datos
se prueba en ``tests/integration/test_iris_contact_graph.py``.
"""

from __future__ import annotations

import pytest

from src.modules.features.iris.model import CommunicationKind
from src.modules.features.iris.services.graph import (
    HabitualContact,
    detect_deviation,
    normalize_display_name,
    parse_participants,
)

pytestmark = pytest.mark.unit

_JUAN = HabitualContact(address="juan.perez@empresa.example",
                        display_names=frozenset({"Juan Pérez"}), legitimate_count=12)


def _participants(from_header: str, **headers):
    return parse_participants({"from": from_header, **headers})


def test_participants_include_recipients_copies_and_a_different_reply_to():
    participants = _participants(
        '"Ana" <Ana@Corp.example>', to="luis@corp.example, eva@corp.example", cc="luis@corp.example",
        **{"reply-to": "ana@corp.example"},
    )

    assert participants.sender_address == "ana@corp.example"
    assert participants.sender_domain == "corp.example"
    assert participants.counterparts == (
        (CommunicationKind.TO, "luis@corp.example"),
        (CommunicationKind.TO, "eva@corp.example"),
        (CommunicationKind.CC, "luis@corp.example"),
    )


def test_the_display_name_ignores_case_accents_and_quotes():
    assert normalize_display_name('"JUAN  Perez"') == normalize_display_name("Juan Pérez") == "juan perez"


def test_a_new_address_with_a_habitual_name_is_a_deviation():
    deviation = detect_deviation(_participants('"Juan Perez" <jp.ceo@gmail.com>'), [_JUAN])

    assert deviation == {
        "kind": "display_name_reuse",
        "senderAddress": "jp.ceo@gmail.com",
        "displayName": "Juan Perez",
        "habitualAddress": "juan.perez@empresa.example",
        "habitualMessages": 12,
    }


def test_the_same_address_on_another_domain_is_a_deviation():
    deviation = detect_deviation(_participants("<juan.perez@empresa-mail.example>"), [_JUAN])

    assert deviation["kind"] == "address_domain_change"


def test_the_habitual_contact_itself_is_no_deviation():
    assert detect_deviation(_participants('"Juan Pérez" <juan.perez@empresa.example>'), [_JUAN]) is None


@pytest.mark.parametrize("from_header", [
    '"Marta" <marta@otra.example>',          # otro nombre
    '"JP" <jp@otra.example>',                # nombre demasiado corto para identificar a nadie
    "<info@otra.example>",                   # parte local genérica
])
def test_unrelated_or_generic_senders_are_no_deviation(from_header):
    info = HabitualContact(address="info@empresa.example", display_names=frozenset({"JP"}), legitimate_count=5)

    assert detect_deviation(_participants(from_header), [_JUAN, info]) is None


def test_without_habitual_contacts_nothing_deviates():
    assert detect_deviation(_participants('"Juan Perez" <jp.ceo@gmail.com>'), []) is None
