"""Tokens de integración de Iris: forma, verificación y canal declarado."""

from __future__ import annotations

import pytest

from src.modules.features.iris.services.integration_tokens import (
    generate_integration_token,
    hash_secret,
    is_secret_valid,
    parse_integration_token,
    parse_report_channel,
)

pytestmark = pytest.mark.unit


def test_an_issued_token_parses_back_into_its_parts_and_verifies():
    issued = generate_integration_token()

    parts = parse_integration_token(issued.token)

    assert issued.token.startswith("irt_")
    assert parts is not None and parts[0] == issued.key_id
    assert is_secret_valid(parts[1], issued.secret_sha256)
    assert issued.secret_sha256 == hash_secret(parts[1])
    assert parts[1] not in issued.secret_sha256, "no se guarda el secreto, solo su hash"


def test_two_tokens_never_share_parts():
    first, second = generate_integration_token(), generate_integration_token()
    assert first.key_id != second.key_id and first.token != second.token


def test_a_wrong_secret_does_not_verify():
    issued = generate_integration_token()
    assert not is_secret_valid("x" * 43, issued.secret_sha256)


@pytest.mark.parametrize("raw", [
    None, "", "   ",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.firma",          # un JWT de sesión
    "irt_0123456789abcdef",                                 # sin secreto
    "irt_XYZ3456789abcdef.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # key_id no hexadecimal
    "irt_0123456789abcdef.corto",                           # secreto demasiado corto
    "0123456789abcdef.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # sin prefijo
])
def test_anything_that_is_not_an_integration_token_is_rejected(raw):
    assert parse_integration_token(raw) is None


@pytest.mark.parametrize("value,expected", [
    ("outlook_addin", "outlook_addin"),
    ("Outlook-Addin", "outlook_addin"),
    ("gmail_addon", "gmail_addon"),
    ("browser_extension", "browser_extension"),
    ("api", "api"),
    (None, "api"),
    ("thunderbird", "api"),
])
def test_the_declared_channel_falls_back_to_api(value, expected):
    assert parse_report_channel(value) == expected
