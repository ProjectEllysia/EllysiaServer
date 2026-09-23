"""La evidencia cruda de un hallazgo: redacción, truncado y hash.

La parte pura, sin ORM ni red. La redacción es lo que separa «guardo lo que vi»
de «me quedo con las llaves de casa del cliente», así que la mayoría de estos
tests son sobre lo que **no** debe acabar en la base de datos.
"""

import pytest

from src.modules.features.themis.lybra.evidence import (
    EvidenceRecorder,
    build_recorder,
    evidence_hash,
    prepare_evidence,
    redact_evidence,
    redact_headers,
)

pytestmark = pytest.mark.unit


def test_sensitive_headers_lose_their_value_but_keep_their_name():
    """Se conserva que la cabecera estaba —más honesto que fingir que no— y se
    borra sólo el secreto."""
    headers = {
        "Server": "nginx",
        "Set-Cookie": "PHPSESSID=deadbeef; HttpOnly",
        "Authorization": "Bearer supersecret",
        "X-Api-Key": "abc123",
    }
    redacted = redact_headers(headers)
    assert redacted["Server"] == "nginx"
    assert redacted["Set-Cookie"] == "[redacted]"
    assert redacted["Authorization"] == "[redacted]"
    assert redacted["X-Api-Key"] == "[redacted]"


def test_redaction_is_case_insensitive_on_the_header_name():
    assert redact_headers({"set-COOKIE": "x"})["set-COOKIE"] == "[redacted]"
    assert redact_headers({"AUTHORIZATION": "x"})["AUTHORIZATION"] == "[redacted]"


def test_the_body_is_truncated_to_the_configured_cap():
    payload = {"body": "A" * 20000}
    redacted = redact_evidence(payload, max_body_bytes=100)
    assert len(redacted["body"].encode("utf-8")) == 100
    assert redacted["body_truncated_bytes"] == 19900


def test_a_short_body_is_left_alone():
    payload = {"body": "corto"}
    redacted = redact_evidence(payload, max_body_bytes=8192)
    assert redacted["body"] == "corto"
    assert "body_truncated_bytes" not in redacted


def test_the_hash_is_stable_for_the_same_content():
    payload = {"status": 200, "headers": {"b": "2", "a": "1"}, "body": "x"}
    # El mismo contenido con las claves en otro orden produce el mismo hash.
    other = {"body": "x", "status": 200, "headers": {"a": "1", "b": "2"}}
    assert evidence_hash(payload) == evidence_hash(other)
    assert len(evidence_hash(payload)) == 64


def test_the_hash_changes_if_the_content_changes():
    a = evidence_hash({"body": "hola"})
    b = evidence_hash({"body": "adios"})
    assert a != b


def test_prepare_evidence_redacts_and_hashes_in_one_step():
    payload = {"status": 200, "headers": {"Cookie": "secret"}, "body": "B" * 100}
    prepared = prepare_evidence(payload, max_body_bytes=10)
    assert prepared["payload"]["headers"]["Cookie"] == "[redacted]"
    assert len(prepared["payload"]["body"].encode("utf-8")) == 10
    # El hash es del contenido ya redactado, no del original.
    assert prepared["content_hash"] == evidence_hash(prepared["payload"])


def test_the_recorder_accumulates_records():
    recorder = EvidenceRecorder()
    recorder.record("k1", "http_response", {"status": 200})
    recorder.record("k2", "http_response", {"status": 404})
    assert [r.dedup_key for r in recorder.records] == ["k1", "k2"]


def test_build_recorder_returns_none_when_disabled():
    assert build_recorder(False) is None
    assert isinstance(build_recorder(True), EvidenceRecorder)


# ========================================================== secretos del cuerpo


def test_secrets_in_a_body_are_redacted_but_their_names_kept():
    from src.modules.features.themis.lybra.evidence import redact_evidence

    body = ("class JConfig {\n\tpublic $password = 'hunter2';\n}\n"
            "define('DB_PASSWORD', 's3cr3t');\n"
            '{"password":"abc","dbtype":"mysqli"}\n'
            "SECRET_KEY=zzz\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----")

    redacted = redact_evidence({"body": body})["body"]

    for secret in ("hunter2", "s3cr3t", '"abc"', "zzz", "MIIE"):
        assert secret not in redacted
    assert "$password" in redacted and "DB_PASSWORD" in redacted and "mysqli" in redacted


def test_a_nul_byte_in_the_body_is_stripped_so_postgres_can_store_it():
    """PostgreSQL rechaza el carácter NUL en texto/JSONB. Un cuerpo comprimido
    (gzip del check BREACH) llega lleno de NUL; sin quitarlos, el INSERT de la
    evidencia revienta y tumba el escaneo entero."""
    import json
    from src.modules.features.themis.lybra.evidence import redact_evidence

    redacted = redact_evidence({"body": "gzip\x00\x1f\x8b\x00binario", "status": 200})

    assert "\x00" not in redacted["body"]
    json.dumps(redacted)   # serializable a JSONB, que es lo que fallaba
