"""
hygeia.services.stats_cache
───────────────────────────
Cuándo se reutiliza una estadística ya calculada y cuándo se recalcula.

El mecanismo (guardar con caducidad en Redis, degradar si falla) es
``infrastructure.ExpiringCache``; aquí vive la política de Hygeia encima:

- **Qué identifica un resultado.** La clave lleva el usuario (cada uno ve solo
  sus activos, así que un resultado nunca se comparte entre usuarios), la
  generación de caché de ese usuario, el tipo de estadística y sus parámetros.
- **Cuánto vive.** Según el periodo pedido, con los tramos de
  ``CR.hygeia_stats_cache()``: el resumen de un día envejece deprisa y el de un
  mes, despacio.
- **Cuándo deja de valer antes de tiempo.** Cuando cambian los activos o las
  etiquetas del usuario, ``invalidate_user_stats`` incrementa su generación.
  Las claves de la generación anterior no se buscan ni se borran: dejan de
  pedirse y caducan solas, lo que evita recorrer Redis por patrón.

Quien llama es responsable de comprobar permisos y validar parámetros **antes**
de pedir el resultado: un activo borrado tiene que dar 404 aunque su resumen
siga guardado.

Functions:
    resolve_cached_stats:  Devuelve el resultado guardado o lo calcula y lo guarda.
    invalidate_user_stats: Deja sin efecto todo lo guardado para un usuario.
    resolve_ttl_seconds:   Vida de un resultado según el periodo pedido.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Callable, Mapping, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import ExpiringCache, get_shared_cache

#: Umbrales de periodo que separan los tres tramos de vida de la config.
_SHORT_PERIOD_LIMIT = timedelta(hours=24)
_MEDIUM_PERIOD_LIMIT = timedelta(days=7)

#: Cuántas veces la vida más larga de un resultado dura el contador de
#: generación. Tiene que durar más que cualquier resultado que dependa de él:
#: si caducara antes, volvería a cero y coincidiría con claves antiguas vivas.
_GENERATION_TTL_FACTOR = 2

#: Versión del formato de las claves. Se sube si cambia lo que se guarda, para
#: que un despliegue no lea resultados con la forma anterior.
_KEY_VERSION = 1


def _build_generation_key(user_id: int) -> str:
    """Clave del contador de generación de caché de un usuario.

    Args:
        user_id: Primary key del usuario.

    Returns:
        str: La clave lógica, sin el prefijo común de ``ExpiringCache``.
    """
    return f"hygeia:stats-generation:{user_id}"


def _build_result_key(
    user_id: int, generation: int, dataset: str, parameters: Mapping[str, Any],
) -> str:
    """Clave de un resultado concreto.

    Los parámetros se resumen con un hash de su JSON con las claves ordenadas:
    así el orden en que llegaron no cambia la clave y la clave no crece con el
    número de parámetros.

    Args:
        user_id: Primary key del usuario dueño del resultado.
        generation: Generación de caché vigente del usuario.
        dataset: Tipo de estadística (``"summary"``, ``"tag-stats"``,
            ``"ranking"``, ``"series"``).
        parameters: Todo lo que cambia el resultado; tiene que poder pasarse a
            JSON (los valores que no, se convierten con ``str``).

    Returns:
        str: La clave lógica, sin el prefijo común de ``ExpiringCache``.
    """
    canonical = json.dumps(parameters, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"hygeia:stats:v{_KEY_VERSION}:{user_id}:g{generation}:{dataset}:{digest}"


def resolve_ttl_seconds(requested_duration: timedelta) -> int:
    """Vida de un resultado guardado según el periodo pedido.

    Args:
        requested_duration: Duración del periodo pedido por el usuario, antes
            de recortarlo a lo que se conserva.

    Returns:
        int: ``shortPeriodTtlSeconds`` para periodos de hasta 24 horas,
            ``mediumPeriodTtlSeconds`` hasta 7 días y ``longPeriodTtlSeconds``
            para los más largos.
    """
    config = CR.hygeia_stats_cache()
    if requested_duration <= _SHORT_PERIOD_LIMIT:
        return config.short_period_ttl_seconds
    if requested_duration <= _MEDIUM_PERIOD_LIMIT:
        return config.medium_period_ttl_seconds
    return config.long_period_ttl_seconds


def resolve_cached_stats(  # pylint: disable=too-many-arguments
    user_id: int,
    dataset: str,
    parameters: Mapping[str, Any],
    requested_duration: timedelta,
    compute: Callable[[], dict],
    *,
    is_refresh: bool = False,
    cache: Optional[ExpiringCache] = None,
) -> dict:
    """Devuelve un resultado de estadísticas guardado, o lo calcula y lo guarda.

    Calcula sin mirar ni guardar nada si la caché está desactivada en la config
    o si Redis no responde al leer la generación del usuario: en ese caso el
    resultado es el mismo que sin caché, solo que sin ahorro.

    Args:
        user_id: Primary key del usuario que pide; separa los resultados de
            cada usuario.
        dataset: Tipo de estadística (``"summary"``, ``"tag-stats"``,
            ``"ranking"``, ``"series"``); separa resultados con parámetros
            parecidos pero de distinta clase.
        parameters: Todo lo que cambia el resultado además del usuario, incluida
            la duración pedida.
        requested_duration: Duración del periodo pedido; decide la vida del
            resultado guardado.
        compute: Función sin argumentos que calcula el resultado. Solo se llama
            si no hay uno guardado utilizable.
        is_refresh: Si es ``True`` se ignora lo guardado, se calcula de nuevo y
            se guarda en su lugar. Por defecto ``False``.
        cache: Caché a usar. Por defecto ``None``, que usa la compartida del
            proceso; los tests inyectan una sobre un Redis en memoria.

    Returns:
        dict: El resultado, guardado o recién calculado; en los dos casos, lo
            que devolvió ``compute``.
    """
    if not CR.hygeia_stats_cache().is_enabled:
        return compute()

    cache = cache or get_shared_cache()
    generation = cache.get_counter(_build_generation_key(user_id))
    if generation is None:
        return compute()

    key = _build_result_key(user_id, generation, dataset, parameters)
    if not is_refresh:
        cached = cache.get_value(key)
        if cached is not None:
            return cached

    result = compute()
    cache.set_value(key, result, resolve_ttl_seconds(requested_duration))
    return result


def invalidate_user_stats(user_id: int, cache: Optional[ExpiringCache] = None) -> None:
    """Deja sin efecto todas las estadísticas guardadas de un usuario.

    Se llama cuando cambia algo que altera sus resultados: el conjunto de
    activos o las etiquetas que llevan. Si Redis no responde no hace nada;
    tampoco se podrá leer lo guardado mientras siga así.

    Warning:
        Dentro de una request, la invalidación ocurre antes de que se confirme
        la transacción. Una consulta de estadísticas que llegue justo en ese
        hueco puede calcular con los datos anteriores y guardarlos en la
        generación nueva, que duraría hasta caducar. El hueco es de
        milisegundos y el panel permite pedir un resultado recalculado.

    Args:
        user_id: Primary key del usuario.
        cache: Caché a usar. Por defecto ``None``, que usa la compartida.

    Returns:
        None.
    """
    cache = cache or get_shared_cache()
    config = CR.hygeia_stats_cache()
    longest_ttl_seconds = max(
        config.short_period_ttl_seconds,
        config.medium_period_ttl_seconds,
        config.long_period_ttl_seconds,
    )
    ttl_seconds = longest_ttl_seconds * _GENERATION_TTL_FACTOR
    cache.increment_counter(_build_generation_key(user_id), ttl_seconds)
