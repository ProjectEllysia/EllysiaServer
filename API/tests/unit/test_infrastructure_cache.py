"""La caché con caducidad degrada en silencio y devuelve lo que se guardó.

Se prueba con un doble de Redis en memoria con reloj propio
(``tests/_redis_doubles.py``), para poder hacer
caducar valores sin esperar. El caso «Redis caído» usa en cambio el cliente
real: ``tests/conftest.py`` hace fallar al instante toda conexión, que es
justo la situación que la caché tiene que soportar.
"""

from dataclasses import dataclass
from datetime import datetime

import pytest
import redis as redis_lib

from _redis_doubles import InMemoryRedis
from src.modules.infrastructure import ExpiringCache, get_shared_cache

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Summary:
    """Valor de ejemplo con los tipos que devuelve un manager de estadísticas."""
    maximum: float
    measured_at: datetime


@pytest.fixture
def fake_redis():
    """Redis en memoria, nuevo en cada test."""
    return InMemoryRedis()


@pytest.fixture
def cache(fake_redis):
    """Caché sobre el Redis en memoria."""
    return ExpiringCache(redis_client=fake_redis)


class TestValues:
    def test_returns_the_same_objects_it_stored(self, cache):
        stored = {"metrics": {"cpuPct": _Summary(92.5, datetime(2026, 9, 1, 12, 0))}}
        cache.set_value("summary", stored, ttl_seconds=60)
        assert cache.get_value("summary") == stored

    def test_missing_key_reads_as_none(self, cache):
        assert cache.get_value("nothing-here") is None

    def test_value_expires_after_its_ttl(self, cache, fake_redis):
        cache.set_value("summary", {"value": 1}, ttl_seconds=60)
        fake_redis.advance(59)
        assert cache.get_value("summary") == {"value": 1}
        fake_redis.advance(1)
        assert cache.get_value("summary") is None

    def test_keys_are_namespaced(self, cache, fake_redis):
        cache.set_value("summary", {"value": 1}, ttl_seconds=60)
        assert list(fake_redis.values_by_key) == ["cache:summary"]

    def test_none_is_not_stored(self, cache, fake_redis):
        cache.set_value("summary", None, ttl_seconds=60)
        assert fake_redis.values_by_key == {}

    def test_non_positive_ttl_is_not_stored(self, cache, fake_redis):
        cache.set_value("summary", {"value": 1}, ttl_seconds=0)
        assert fake_redis.values_by_key == {}

    # Un pickle viejo cuya clase ya no existe, o bytes corruptos: recalcular.
    def test_unreadable_value_reads_as_none(self, cache, fake_redis):
        fake_redis.set("cache:summary", b"not a pickle")
        assert cache.get_value("summary") is None

    def test_unpicklable_value_is_skipped_without_raising(self, cache, fake_redis):
        cache.set_value("summary", {"callback": lambda: None}, ttl_seconds=60)
        assert fake_redis.values_by_key == {}


class TestCounters:
    def test_missing_counter_reads_as_zero(self, cache):
        assert cache.get_counter("generation") == 0

    def test_increment_returns_and_stores_the_new_value(self, cache):
        assert cache.increment_counter("generation", ttl_seconds=60) == 1
        assert cache.increment_counter("generation", ttl_seconds=60) == 2
        assert cache.get_counter("generation") == 2

    def test_increment_renews_the_expiry(self, cache, fake_redis):
        cache.increment_counter("generation", ttl_seconds=60)
        fake_redis.advance(50)
        cache.increment_counter("generation", ttl_seconds=60)
        fake_redis.advance(50)
        assert cache.get_counter("generation") == 2

    def test_unreadable_counter_reads_as_none(self, cache, fake_redis):
        fake_redis.set("cache:generation", b"many")
        assert cache.get_counter("generation") is None


class TestRedisUnavailable:
    """Con el cliente real: la suite corta toda conexión a Redis."""

    def test_read_returns_none(self):
        assert ExpiringCache().get_value("summary") is None

    def test_write_does_not_raise(self):
        ExpiringCache().set_value("summary", {"value": 1}, ttl_seconds=60)

    def test_counters_return_none(self):
        cache = ExpiringCache()
        assert cache.get_counter("generation") is None
        assert cache.increment_counter("generation", ttl_seconds=60) is None

    def test_other_redis_errors_are_also_absorbed(self):
        class _TimingOutRedis:
            def get(self, key):
                raise redis_lib.TimeoutError("lento")

        assert ExpiringCache(redis_client=_TimingOutRedis()).get_value("summary") is None


def test_shared_cache_is_one_instance_per_process():
    assert get_shared_cache() is get_shared_cache()
