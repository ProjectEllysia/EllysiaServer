"""La puerta de salida de Iris a internet: nunca hacia la red interna.

Todo lo que Iris consulta fuera pasa por ``services/enrichment/egress.py``.
Estos tests fijan lo que esa capa promete: solo ``http``/``https`` a puertos
web, ninguna dirección privada (tampoco mezclada con una pública, ni tras un
redirect), la conexión a la IP ya comprobada (sin segunda resolución que un DNS
de rebinding pueda aprovechar), y el cupo por proveedor. La red está sellada en
la suite: cada test sustituye la resolución y la conexión.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from src.modules.features.iris.services.enrichment import egress
from src.modules.features.iris.services.enrichment.egress import (
    EgressBlockedError,
    EgressResponse,
    fetch,
    fetch_following,
    is_blocked_address,
)
from src.modules.features.iris.services.enrichment.policy import ProviderRateLimiter

pytestmark = pytest.mark.unit

_PUBLIC = "93.184.216.34"


def _resolving_to(*addresses):
    return lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
                                         for address in addresses]


@pytest.mark.parametrize("address", [
    "10.0.0.5", "192.168.1.1", "127.0.0.1", "169.254.169.254", "::1", "::ffff:10.0.0.1",
    "100.64.0.1", "0.0.0.0", "224.0.0.1", "fe80::1", "no-es-una-ip",
])
def test_internal_addresses_are_blocked(address):
    assert is_blocked_address(address)


def test_a_public_address_is_allowed():
    assert not is_blocked_address(_PUBLIC)


@pytest.mark.parametrize("url,reason", [
    ("ftp://evil.example/x", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("gopher://evil.example/", "scheme"),
    ("http://evil.example:22/", "port"),
    ("http://evil.example:6379/", "port"),
])
def test_only_web_protocols_and_ports(url, reason):
    with pytest.raises(EgressBlockedError) as error:
        fetch(url, timeout_seconds=1, max_bytes=10)
    assert error.value.reason == reason


def test_a_name_that_resolves_to_a_private_address_is_never_contacted():
    with patch.object(socket, "getaddrinfo", _resolving_to("10.0.0.7")), \
            patch.object(socket, "create_connection") as connect:
        with pytest.raises(EgressBlockedError) as error:
            fetch("http://intranet.evil.example/", timeout_seconds=1, max_bytes=10)
    assert error.value.reason == "private_address"
    connect.assert_not_called()


def test_one_private_address_among_public_ones_is_enough_to_block():
    with patch.object(socket, "getaddrinfo", _resolving_to(_PUBLIC, "127.0.0.1")):
        with pytest.raises(EgressBlockedError) as error:
            fetch("https://mixed.evil.example/", timeout_seconds=1, max_bytes=10)
    assert error.value.reason == "private_address"


def test_the_connection_goes_to_the_checked_address_without_resolving_again():
    """DNS rebinding: una segunda resolución podría devolver una IP interna."""
    resolutions = []

    def resolve(host, port, **kwargs):
        resolutions.append(host)
        return _resolving_to(_PUBLIC)(host, port)

    with patch.object(socket, "getaddrinfo", resolve), \
            patch.object(socket, "create_connection", side_effect=ConnectionRefusedError) as connect:
        with pytest.raises(OSError):
            fetch("http://rebind.evil.example/login", timeout_seconds=1, max_bytes=10)
    assert resolutions == ["rebind.evil.example"]
    assert connect.call_args.args[0][0] == _PUBLIC


def test_credentials_in_the_url_are_never_sent():
    sent = {}

    class _Connection:
        def __init__(self, host, address, port, timeout):
            pass

        def request(self, method, path, headers):
            sent.update(headers)
            raise ConnectionRefusedError

        def close(self):
            pass

    with patch.object(socket, "getaddrinfo", _resolving_to(_PUBLIC)), \
            patch.object(egress, "_PinnedHTTPConnection", _Connection):
        with pytest.raises(OSError):
            fetch("http://paypal.com:secret@evil.example/", timeout_seconds=1, max_bytes=10)
    assert sent["Host"] == "evil.example"
    assert "Authorization" not in sent and "Cookie" not in sent


def _response(url, status, location=None):
    return EgressResponse(url=url, status=status, headers={"location": location} if location else {},
                          body=b"", is_truncated=False, peer_address=_PUBLIC)


def test_a_redirect_into_the_internal_network_is_cut():
    def fake_fetch(url, **kwargs):
        if url == "http://short.example/a":
            return _response(url, 302, "http://127.0.0.1/admin")
        raise EgressBlockedError("private_address", url)

    with patch.object(egress, "fetch", fake_fetch):
        chain = fetch_following("http://short.example/a", max_redirects=5, timeout_seconds=1, max_bytes=10)

    assert [hop.error for hop in chain.hops] == [None, "private_address"]
    assert chain.final.status == 302


def test_redirect_loops_stop():
    with patch.object(egress, "fetch", lambda url, **kwargs: _response(url, 301, url)):
        chain = fetch_following("http://loop.example/", max_redirects=2, timeout_seconds=1, max_bytes=10)

    assert chain.hops[-1].error == "too_many_redirects" and len(chain.hops) == 4


def test_a_timeout_is_a_hop_error_not_an_exception():
    def timing_out(url, **kwargs):
        raise socket.timeout("slow")

    with patch.object(egress, "fetch", timing_out):
        chain = fetch_following("http://slow.example/", max_redirects=2, timeout_seconds=1, max_bytes=10)

    assert chain.hops[0].error == "timeout" and chain.final is None


def test_the_rate_limiter_counts_per_provider_and_per_minute():
    limiter = ProviderRateLimiter()

    assert limiter.try_acquire("rdap", 2, now=0) and limiter.try_acquire("rdap", 2, now=1)
    assert not limiter.try_acquire("rdap", 2, now=2)
    assert limiter.try_acquire("virustotal", 2, now=2)
    assert limiter.try_acquire("rdap", 2, now=61)
