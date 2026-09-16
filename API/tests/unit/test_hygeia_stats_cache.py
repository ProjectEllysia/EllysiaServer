"""Política de caché de las estadísticas de Hygeia (``services/stats_cache.py``).

Qué resultado se reutiliza, durante cuánto y cuándo deja de valer. La caché va
sobre un Redis en memoria (``tests/_redis_doubles.py``), y el caso «Redis
caído» sobre el cliente real, que la suite hace fallar al instante.
"""

import copy
from datetime import timedelta

import pytest

import src.modules.system.config_reading as CR
from _redis_doubles import InMemoryRedis
from src.modules.features.hygeia.services.stats_cache import (
    invalidate_user_stats,
    resolve_cached_stats,
    resolve_ttl_seconds,
)
from src.modules.infrastructure import ExpiringCache

pytestmark = pytest.mark.unit

_DAY = timedelta(hours=24)


class _CountingComputation:
    """Cálculo de prueba que cuenta cuántas veces se ejecuta.

    Attributes:
        call_count: Veces que se ha llamado.
        next_value: Lo que devuelve la próxima llamada.
    """

    def __init__(self, value: int = 1) -> None:
        """Empieza sin llamadas, devolviendo ``{"value": value}``."""
        self.call_count = 0
        self.next_value = value

    def __call__(self) -> dict:
        """Cuenta la llamada y devuelve el valor vigente."""
        self.call_count += 1
        return {"value": self.next_value}


@pytest.fixture
def fake_redis():
    """Redis en memoria, nuevo en cada test."""
    return InMemoryRedis()


@pytest.fixture
def cache(fake_redis):
    """Caché sobre el Redis en memoria."""
    return ExpiringCache(redis_client=fake_redis)


@pytest.fixture
def stats_cache_config(monkeypatch):
    """Permite cambiar ``features.hygeia.statsCache`` solo para un test.

    Returns:
        Callable: Recibe los pares ``clave=valor`` a sobrescribir en el bloque.
    """
    def _override(**values):
        configs = copy.deepcopy(CR._configs)
        configs["features"]["hygeia"]["statsCache"].update(values)
        monkeypatch.setattr(CR, "_configs", configs)

    return _override


def _resolve(cache, computation, user_id=1, parameters=None, duration=_DAY, is_refresh=False):
    """Atajo de ``resolve_cached_stats`` con valores de prueba por defecto."""
    return resolve_cached_stats(
        user_id, "summary", parameters or {"assetId": 7, "durationSeconds": duration.total_seconds()},
        duration, computation, is_refresh=is_refresh, cache=cache,
    )


class TestReuse:
    def test_the_second_request_reuses_the_first_result(self, cache):
        computation = _CountingComputation()
        assert _resolve(cache, computation) == {"value": 1}
        assert _resolve(cache, computation) == {"value": 1}
        assert computation.call_count == 1

    def test_a_result_is_recomputed_after_it_expires(self, cache, fake_redis):
        computation = _CountingComputation()
        _resolve(cache, computation)
        fake_redis.advance(CR.hygeia_stats_cache().short_period_ttl_seconds)
        _resolve(cache, computation)
        assert computation.call_count == 2

    def test_users_never_share_a_result(self, cache):
        computation = _CountingComputation()
        _resolve(cache, computation, user_id=1)
        computation.next_value = 2
        assert _resolve(cache, computation, user_id=2) == {"value": 2}

    def test_different_parameters_are_different_results(self, cache):
        computation = _CountingComputation()
        _resolve(cache, computation, parameters={"assetId": 7})
        _resolve(cache, computation, parameters={"assetId": 8})
        assert computation.call_count == 2

    def test_the_order_of_the_parameters_does_not_matter(self, cache):
        computation = _CountingComputation()
        _resolve(cache, computation, parameters={"assetId": 7, "metrics": ["cpuPct"]})
        _resolve(cache, computation, parameters={"metrics": ["cpuPct"], "assetId": 7})
        assert computation.call_count == 1


class TestRefreshAndInvalidation:
    def test_refresh_recomputes_and_replaces_the_stored_result(self, cache):
        computation = _CountingComputation()
        _resolve(cache, computation)
        computation.next_value = 2
        assert _resolve(cache, computation, is_refresh=True) == {"value": 2}
        assert _resolve(cache, computation) == {"value": 2}
        assert computation.call_count == 2

    def test_invalidating_a_user_discards_everything_stored_for_them(self, cache):
        computation = _CountingComputation()
        _resolve(cache, computation)
        invalidate_user_stats(1, cache=cache)
        computation.next_value = 2
        assert _resolve(cache, computation) == {"value": 2}

    def test_invalidating_a_user_leaves_other_users_alone(self, cache):
        computation = _CountingComputation()
        _resolve(cache, computation, user_id=2)
        invalidate_user_stats(1, cache=cache)
        _resolve(cache, computation, user_id=2)
        assert computation.call_count == 1

    # El contador tiene que sobrevivir a cualquier resultado que dependa de él:
    # si volviera a cero antes, las claves antiguas volverían a leerse.
    def test_the_generation_outlives_the_longest_result(self, cache, fake_redis):
        invalidate_user_stats(1, cache=cache)
        fake_redis.advance(CR.hygeia_stats_cache().long_period_ttl_seconds)
        assert cache.get_counter("hygeia:stats-generation:1") == 1


class TestDegradation:
    def test_with_the_cache_disabled_everything_is_computed(self, cache, stats_cache_config):
        stats_cache_config(isEnabled=False)
        computation = _CountingComputation()
        _resolve(cache, computation)
        _resolve(cache, computation)
        assert computation.call_count == 2

    def test_without_redis_the_result_is_still_computed(self):
        computation = _CountingComputation()
        assert _resolve(ExpiringCache(), computation) == {"value": 1}
        assert _resolve(ExpiringCache(), computation) == {"value": 1}
        assert computation.call_count == 2

    def test_invalidating_without_redis_does_not_raise(self):
        invalidate_user_stats(1, cache=ExpiringCache())


class TestTimeToLive:
    @pytest.mark.parametrize("duration, field_name", [
        (timedelta(hours=1), "short_period_ttl_seconds"),
        (timedelta(hours=24), "short_period_ttl_seconds"),
        (timedelta(hours=25), "medium_period_ttl_seconds"),
        (timedelta(days=7), "medium_period_ttl_seconds"),
        (timedelta(days=8), "long_period_ttl_seconds"),
        (timedelta(days=30), "long_period_ttl_seconds"),
    ])
    def test_the_lifetime_grows_with_the_period(self, duration, field_name):
        assert resolve_ttl_seconds(duration) == getattr(CR.hygeia_stats_cache(), field_name)

    def test_the_stored_result_uses_that_lifetime(self, cache, fake_redis):
        _resolve(cache, _CountingComputation(), duration=timedelta(days=30))
        [key] = [key for key in fake_redis.values_by_key if ":stats:" in key]
        assert fake_redis.expiry_by_key[key] == CR.hygeia_stats_cache().long_period_ttl_seconds
