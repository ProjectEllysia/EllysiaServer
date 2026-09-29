"""La sonda de exposición en la nube (``lybra/cloud.py::CloudProbe``).

Pura: la petición HTTP y la resolución de CNAME se sustituyen por funciones que
devuelven respuestas fabricadas, así que ninguna prueba sale a la red.
"""

import pytest

from src.modules.features.themis.lybra import CloudProbe, load_takeover_signatures, parse_cloud_resource
from src.modules.features.themis.lybra.checks import Response

pytestmark = pytest.mark.unit

_S3_LISTING = '<?xml version="1.0"?><ListBucketResult><Name>b</Name></ListBucketResult>'
_S3_DENIED = "<Error><Code>AccessDenied</Code></Error>"
_AZURE_LISTING = "<EnumerationResults><Blobs/></EnumerationResults>"


def _probe(responses: dict, cnames: dict = None) -> CloudProbe:
    """Una sonda cuyo fetch contesta según `(host, ruta)` y cuya resolución según `cnames`."""
    requested = []

    def fetch(host, port, path):
        requested.append((host, port, path))
        return responses.get((host, path))

    probe = CloudProbe(fetch, lambda name: (cnames or {}).get(name))
    probe.requested = requested
    return probe


def _resource(text: str):
    return parse_cloud_resource(text)


# ------------------------------------------------------------ almacenamiento

def test_a_public_s3_bucket_is_reported():
    probe = _probe({("mi-bucket.s3.amazonaws.com", "/"): Response(200, _S3_LISTING, {})})
    finding = probe.probe_resource(_resource("s3:mi-bucket"))

    assert finding["category"] == "cloud_exposure" and finding["severity"] == "HIGH"
    assert finding["service"] == "s3:mi-bucket" and finding["port"] is None


def test_a_private_s3_bucket_is_not_reported():
    probe = _probe({("mi-bucket.s3.amazonaws.com", "/"): Response(403, _S3_DENIED, {})})
    assert probe.probe_resource(_resource("s3:mi-bucket")) is None


def test_a_bucket_answering_200_without_a_listing_is_not_reported():
    # Un 200 con cualquier otra cosa (una página de error amable) no es un listado.
    probe = _probe({("mi-bucket.s3.amazonaws.com", "/"): Response(200, "<html>hola</html>", {})})
    assert probe.probe_resource(_resource("s3:mi-bucket")) is None


def test_a_public_gcs_bucket_is_reported():
    probe = _probe({("storage.googleapis.com", "/datos/"): Response(200, _S3_LISTING, {})})
    assert probe.probe_resource(_resource("gcs:datos"))["check_id"] == "lybra:cloud-gcs-public-bucket@1"


def test_a_public_azure_container_is_reported_and_a_private_one_is_not():
    path = "/publico?restype=container&comp=list"
    probe = _probe({("cuenta1.blob.core.windows.net", path): Response(200, _AZURE_LISTING, {})})
    assert probe.probe_resource(_resource("azure:cuenta1/publico")) is not None
    assert probe.probe_resource(_resource("azure:cuenta1/privado")) is None


def test_a_request_without_an_answer_reports_nothing():
    assert _probe({}).probe_resource(_resource("s3:mi-bucket")) is None


# ------------------------------------------------------------------- Firebase

@pytest.mark.parametrize("status, body, is_reported", [
    (200, '{"usuarios": {"a": 1}}', True),
    (401, '{"error": "Permission denied"}', False),   # con reglas
    (200, "null", False),                              # vacía: nada expuesto
    (200, "{}", False),
    (200, "no es json", False),
])
def test_firebase_is_reported_only_when_it_hands_over_data(status, body, is_reported):
    probe = _probe({("mi-proyecto.firebaseio.com", "/.json"): Response(status, body, {})})
    finding = probe.probe_resource(_resource("firebase:mi-proyecto"))
    assert (finding is not None) is is_reported
    if is_reported:
        assert finding["severity"] == "CRITICAL"


# ------------------------------------------------------------------- takeover

def test_every_bundled_signature_is_well_formed():
    signatures = load_takeover_signatures()
    assert len(signatures) >= 10
    for signature in signatures:
        assert signature.cnames and signature.fingerprints, signature.service


@pytest.mark.parametrize("signature", load_takeover_signatures(), ids=lambda item: item.service)
def test_each_signature_flags_a_dangling_subdomain(signature):
    destination = f"algo.{signature.cnames[0]}"
    probe = _probe({("blog.example.com", "/"): Response(404, f"...{signature.fingerprints[0]}...", {})},
                   cnames={"blog.example.com": destination})

    finding = probe.probe_subdomain("blog.example.com")

    assert finding is not None and finding["service"] == "blog.example.com"
    assert finding["check_id"] == f"lybra:cloud-takeover-{signature.service}@1"


def test_a_cname_to_a_third_party_that_still_hosts_the_resource_is_not_a_takeover():
    probe = _probe({("blog.example.com", "/"): Response(200, "<html>mi blog</html>", {})},
                   cnames={"blog.example.com": "usuario.github.io."})
    assert probe.probe_subdomain("blog.example.com") is None


def test_a_generic_404_is_not_a_takeover():
    probe = _probe({("blog.example.com", "/"): Response(404, "Not Found", {})},
                   cnames={"blog.example.com": "usuario.github.io"})
    assert probe.probe_subdomain("blog.example.com") is None


def test_a_name_that_is_not_a_cname_costs_no_request():
    probe = _probe({})
    assert probe.probe_subdomain("www.example.com") is None
    assert probe.requested == []


def test_a_cname_to_an_unknown_service_costs_no_request():
    probe = _probe({}, cnames={"www.example.com": "lb.interno.example.net"})
    assert probe.probe_subdomain("www.example.com") is None
    assert probe.requested == []


def test_two_dangling_subdomains_get_distinct_dedup_identities():
    from src.modules.features.themis.lybra import compute_dedup_key

    responses = {(name, "/"): Response(404, "There isn't a GitHub Pages site here", {})
                 for name in ("a.example.com", "b.example.com")}
    probe = _probe(responses, cnames={name: "x.github.io" for name, _ in responses})

    keys = {compute_dedup_key({**probe.probe_subdomain(name), "host_id": None})
            for name in ("a.example.com", "b.example.com")}
    assert len(keys) == 2
