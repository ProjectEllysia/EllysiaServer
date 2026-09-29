"""Webhooks de Iris: la parte pura (firma, id del evento, reintentos, URL y envío).

La firma se comprueba como la comprobaría un receptor: recalculando el HMAC
con el secreto a partir de la cabecera y del cuerpo recibido. El envío pasa por
la puerta de salida real (``egress.fetch``), con la resolución de nombres y la
conexión sustituidas, para fijar que un webhook no puede alcanzar la red
interna aunque su nombre resuelva a ella.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
from datetime import datetime
from unittest.mock import patch

import pytest

from src.modules.features.iris.services.enrichment import egress
from src.modules.features.iris.services.enrichment.egress import EgressResponse
from src.modules.features.iris.services.webhooks import (
    build_delivery_headers,
    build_event_id,
    build_event_payload,
    compute_retry_delay_seconds,
    generate_webhook_secret,
    send_webhook,
    serialize_payload,
    sign_payload,
    validate_webhook_url,
)

pytestmark = pytest.mark.unit


def _verify_like_a_receiver(secret: str, header: str, body: bytes) -> bool:
    """Lo que haría el receptor con la cabecera ``X-Ellysia-Signature``."""
    parts = dict(part.split("=", 1) for part in header.split(","))
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


def test_a_receiver_can_verify_the_signature_with_its_copy_of_the_secret():
    secret = generate_webhook_secret()
    body = serialize_payload({"id": "x", "type": "ping", "data": {"a": 1}})

    header = sign_payload(secret, 1_700_000_000, body)

    assert header.startswith("t=1700000000,v1=")
    assert _verify_like_a_receiver(secret, header, body)


def test_a_tampered_body_or_another_secret_does_not_verify():
    secret = generate_webhook_secret()
    body = serialize_payload({"verdict": "Legitimate"})
    header = sign_payload(secret, 1_700_000_000, body)

    assert not _verify_like_a_receiver(secret, header, serialize_payload({"verdict": "Phishing"}))
    assert not _verify_like_a_receiver(generate_webhook_secret(), header, body)


def test_the_timestamp_is_part_of_what_is_signed():
    """Cambiar la marca de tiempo invalida la firma: un replay no puede rejuvenecerse."""
    secret = generate_webhook_secret()
    body = serialize_payload({"a": 1})
    header = sign_payload(secret, 1_700_000_000, body)
    forged = header.replace("t=1700000000", "t=1800000000")

    assert not _verify_like_a_receiver(secret, forged, body)


def test_secrets_are_prefixed_and_unique():
    first, second = generate_webhook_secret(), generate_webhook_secret()
    assert first.startswith("whsec_") and len(first) > 40
    assert first != second


def test_the_same_fact_always_gets_the_same_event_id():
    assert build_event_id("analysis.finished:42") == build_event_id("analysis.finished:42")
    assert build_event_id("analysis.finished:42") != build_event_id("analysis.finished:43")
    assert len(build_event_id("analysis.finished:42")) == 36


def test_the_payload_serializes_to_the_same_bytes_every_time():
    payload = build_event_payload("id-1", "analysis.finished", {"b": 2, "a": "ñ"}, datetime(2026, 9, 28, 10, 0))
    assert serialize_payload(payload) == serialize_payload(dict(reversed(list(payload.items()))))
    decoded = json.loads(serialize_payload(payload))
    assert decoded["createdAt"] == "2026-09-28T10:00:00Z"
    assert decoded["schemaVersion"] == 1 and decoded["data"]["a"] == "ñ"


def test_delivery_headers_carry_the_event_identity_and_the_attempt():
    headers = build_delivery_headers("id-1", "case.updated", 3, "t=1,v1=abc")
    assert headers["X-Ellysia-Event"] == "case.updated"
    assert headers["X-Ellysia-Event-Id"] == "id-1"
    assert headers["X-Ellysia-Delivery-Attempt"] == "3"
    assert headers["X-Ellysia-Signature"] == "t=1,v1=abc"
    assert headers["Content-Type"].startswith("application/json")


@pytest.mark.parametrize("attempts,expected", [(1, 30), (2, 60), (3, 120), (7, 1920), (8, 3600), (50, 3600)])
def test_retries_back_off_exponentially_up_to_a_ceiling(attempts, expected):
    assert compute_retry_delay_seconds(attempts, 30, 3600) == expected


@pytest.mark.parametrize("url", [
    "https://siem.example.com/hooks/ellysia",
    "https://hooks.example.org:8443/x",
    "  https://soar.example.net/in  ",
])
def test_public_https_urls_are_accepted(url):
    assert validate_webhook_url(url) == url.strip()


@pytest.mark.parametrize("url,reason", [
    ("http://siem.example.com/hook", "https"),
    ("ftp://siem.example.com/hook", "https"),
    ("https://user:pass@siem.example.com/hook", "usuario"),
    ("https://siem.example.com:22/hook", "puertos"),
    ("https://localhost/hook", "red interna"),
    ("https://127.0.0.1/hook", "red interna"),
    ("https://10.0.0.5/hook", "red interna"),
    ("https://[::1]/hook", "red interna"),
    ("https://169.254.169.254/latest", "red interna"),
    ("https://nas.local/hook", "red interna"),
    ("https://intranet/hook", "red interna"),
    ("https:///hook", "servidor"),
])
def test_urls_that_cannot_be_a_webhook_are_rejected_with_a_reason(url, reason):
    with pytest.raises(ValueError, match=reason):
        validate_webhook_url(url)


def _response(status: int, body: bytes = b"ok") -> EgressResponse:
    return EgressResponse(url="https://siem.example.com/h", status=status, headers={}, body=body,
                          is_truncated=False, peer_address="93.184.216.34")


def test_a_2xx_is_delivered_and_anything_else_is_a_failure_with_its_code():
    with patch.object(egress, "fetch", return_value=_response(204, b"")):
        delivered = send_webhook("https://siem.example.com/h", b"{}", {}, timeout_seconds=1, max_response_bytes=10)
    with patch.object(egress, "fetch", return_value=_response(500, b"boom")):
        failed = send_webhook("https://siem.example.com/h", b"{}", {}, timeout_seconds=1, max_response_bytes=10)

    assert delivered.is_delivered and delivered.status_code == 204 and delivered.error is None
    assert not failed.is_delivered and failed.error == "http_500" and failed.response_excerpt == "boom"


def test_a_redirect_is_not_followed_and_counts_as_a_failure():
    with patch.object(egress, "fetch", return_value=_response(302)) as fetch:
        outcome = send_webhook("https://siem.example.com/h", b"{}", {}, timeout_seconds=1, max_response_bytes=10)
    assert fetch.call_count == 1
    assert not outcome.is_delivered and outcome.error == "http_302"


def test_the_signed_request_goes_out_as_a_post_with_the_signature_headers():
    headers = build_delivery_headers("id-1", "ping", 1, "t=1,v1=abc")
    with patch.object(egress, "fetch", return_value=_response(200)) as fetch:
        send_webhook("https://siem.example.com/h", b'{"a":1}', headers, timeout_seconds=3, max_response_bytes=10)

    kwargs = fetch.call_args.kwargs
    assert kwargs["method"] == "POST" and kwargs["body"] == b'{"a":1}'
    assert kwargs["extra_headers"]["X-Ellysia-Signature"] == "t=1,v1=abc"
    assert kwargs["timeout_seconds"] == 3


def test_a_name_that_resolves_to_the_internal_network_is_never_contacted():
    """El nombre parecía público al darlo de alta; al entregar resuelve a una IP interna."""
    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", port))]

    with patch.object(socket, "getaddrinfo", resolve), patch.object(socket, "create_connection") as connect:
        outcome = send_webhook("https://siem.example.com/h", b"{}", {}, timeout_seconds=1, max_response_bytes=10)

    connect.assert_not_called()
    assert not outcome.is_delivered and outcome.error == "private_address"


def test_a_network_error_becomes_a_stable_reason():
    with patch.object(egress, "fetch", side_effect=socket.timeout("slow")):
        outcome = send_webhook("https://siem.example.com/h", b"{}", {}, timeout_seconds=1, max_response_bytes=10)
    assert not outcome.is_delivered and outcome.error == "timeout" and outcome.status_code is None
