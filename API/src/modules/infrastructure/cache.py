"""
Caché con caducidad sobre Redis, pensada para que nunca pueda romper nada.

Guarda resultados caros de calcular durante un tiempo y los devuelve mientras
no caduquen. Su contrato central es que **un fallo de la caché equivale a no
tener nada guardado**: si Redis está caído, lento o devuelve algo ilegible, se
registra un aviso y quien la usa calcula como si la caché no existiera. Nunca
lanza.

Los valores se serializan con ``pickle`` para devolver exactamente los mismos
objetos que se guardaron (``dataclass``, ``datetime``…), sin pasar por un
formato intermedio que obligue a reconstruirlos. ``pickle`` ejecuta código al
deserializar, así que solo es aceptable porque el origen es el Redis interno
del despliegue, el mismo en el que RQ ya guarda los trabajos de la TaskQueue
serializados con ``pickle``: quien pudiera escribir ahí ya podría ejecutar
código a través de la cola. **No uses esta caché con un Redis compartido con
terceros.**

Classes:
    ExpiringCache: Lectura, escritura y contadores con caducidad.

Functions:
    get_shared_cache: La instancia de proceso, con su conexión perezosa.
"""

from __future__ import annotations

import logging
import pickle
import threading
from typing import Any, Optional

import redis as redis_lib

logger = logging.getLogger(__name__)

#: Prefijo de todas las claves de la caché, para distinguirlas en Redis de las
#: de la TaskQueue y del rate limiter y poder inspeccionarlas juntas.
_KEY_PREFIX = "cache:"

#: Tiempo máximo que una operación puede esperar a Redis, en segundos. La caché
#: está para ahorrar tiempo: un Redis lento no debe añadir más espera a la
#: petición de la que ahorraría.
_SOCKET_TIMEOUT_SECONDS = 1

_SHARED_CACHE: Optional["ExpiringCache"] = None
_SHARED_CACHE_LOCK = threading.Lock()


def _build_redis_client() -> redis_lib.Redis:
    """Crea el cliente Redis de la caché a partir de la configuración central.

    Conexión binaria (``decode_responses=False``) porque los valores son bytes
    de ``pickle``, y con ``socket_timeout`` corto por lo explicado en
    ``_SOCKET_TIMEOUT_SECONDS``.

    Returns:
        redis_lib.Redis: Cliente sin conectar; la conexión se abre en el
            primer comando.
    """
    # Import diferido, como en ``engine.py``: ``config_reading`` carga
    # ``shared``, y ``shared`` carga ``infrastructure``; importarlo al cargar
    # este módulo cerraría el ciclo.
    from src.modules.system import config_reading as CR  # pylint: disable=import-outside-toplevel

    return redis_lib.Redis(
        **CR.redis_config().connection_kwargs(),
        socket_timeout=_SOCKET_TIMEOUT_SECONDS,
        decode_responses=False,
    )


class ExpiringCache:
    """Caché de valores con caducidad sobre Redis que degrada en silencio.

    Todas las operaciones capturan los errores de Redis y de deserialización:
    una lectura fallida devuelve ``None`` (como si no hubiera nada guardado),
    una escritura fallida no hace nada y un contador fallido devuelve ``None``.

    Attributes:
        _client: Cliente Redis que se usa, o ``None`` hasta la primera
            operación si no se inyectó uno (se construye entonces con la
            configuración central).
    """

    def __init__(self, redis_client: Optional[redis_lib.Redis] = None) -> None:
        """Prepara la caché, opcionalmente con un cliente ya construido.

        Args:
            redis_client: Cliente Redis (o un doble con ``get``, ``set``,
                ``incr``, ``expire``) a usar. Por defecto ``None``: se crea uno
                con la configuración central la primera vez que hace falta.
        """
        self._client = redis_client

    @property
    def _redis(self) -> redis_lib.Redis:
        """Cliente Redis, creado la primera vez que se pide si no se inyectó."""
        if self._client is None:
            self._client = _build_redis_client()
        return self._client

    def get_value(self, key: str) -> Optional[Any]:
        """Devuelve el valor guardado bajo una clave, si sigue vivo.

        Args:
            key: Clave lógica, sin el prefijo común de la caché.

        Returns:
            Optional[Any]: El objeto guardado, tal cual se guardó; ``None`` si
                no hay nada, si caducó, si Redis falla o si lo guardado no se
                puede deserializar (por ejemplo, porque la clase del objeto se
                renombró en un despliegue posterior).
        """
        try:
            payload = self._redis.get(_KEY_PREFIX + key)
        except redis_lib.RedisError as e:
            logger.warning("Caché no disponible al leer %s: %s", key, e)
            return None
        if payload is None:
            return None
        try:
            return pickle.loads(payload)
        # Cualquier cosa puede salir de un pickle viejo o corrupto
        # (UnpicklingError, AttributeError, ModuleNotFoundError, EOFError…), y
        # en todos los casos la respuesta correcta es recalcular.
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Valor ilegible en caché bajo %s; se descarta: %s", key, e)
            return None

    def set_value(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Guarda un valor bajo una clave durante un tiempo.

        Args:
            key: Clave lógica, sin el prefijo común de la caché.
            value: Objeto a guardar; tiene que poder serializarse con
                ``pickle``. ``None`` no se guarda, porque al leer no se
                distinguiría de «no hay nada».
            ttl_seconds: Segundos que el valor sigue vivo; si no es positivo,
                no se guarda nada.

        Returns:
            None.
        """
        if value is None or ttl_seconds <= 0:
            return
        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            self._redis.set(_KEY_PREFIX + key, payload, ex=ttl_seconds)
        except (redis_lib.RedisError, pickle.PicklingError, TypeError, AttributeError) as e:
            logger.warning("No se pudo guardar %s en caché: %s", key, e)

    def get_counter(self, key: str) -> Optional[int]:
        """Lee un contador entero.

        Args:
            key: Clave lógica del contador, sin el prefijo común.

        Returns:
            Optional[int]: El valor del contador; ``0`` si no existe todavía;
                ``None`` si Redis falla o lo guardado no es un entero.
        """
        try:
            payload = self._redis.get(_KEY_PREFIX + key)
        except redis_lib.RedisError as e:
            logger.warning("Caché no disponible al leer el contador %s: %s", key, e)
            return None
        if payload is None:
            return 0
        try:
            return int(payload)
        except (TypeError, ValueError):
            logger.warning("Contador ilegible en caché bajo %s", key)
            return None

    def increment_counter(self, key: str, ttl_seconds: int) -> Optional[int]:
        """Incrementa un contador entero y renueva su caducidad.

        Args:
            key: Clave lógica del contador, sin el prefijo común.
            ttl_seconds: Segundos que el contador sigue vivo desde este
                incremento. Debe superar la vida de cualquier valor que
                dependa de él: si el contador caducara antes, volvería a
                empezar desde cero y podría coincidir con claves antiguas
                todavía vivas.

        Returns:
            Optional[int]: El valor tras incrementar; ``None`` si Redis falla.
        """
        try:
            value = self._redis.incr(_KEY_PREFIX + key)
            self._redis.expire(_KEY_PREFIX + key, ttl_seconds)
        except redis_lib.RedisError as e:
            logger.warning("No se pudo incrementar el contador %s en caché: %s", key, e)
            return None
        return int(value)


def get_shared_cache() -> ExpiringCache:
    """Devuelve la caché compartida por todo el proceso.

    Una sola instancia, y por tanto un solo pool de conexiones, por proceso: el
    cliente de redis-py es seguro entre hilos y crear uno por petición abriría
    una conexión nueva cada vez.

    Returns:
        ExpiringCache: La instancia de proceso, creada la primera vez que se
            pide.
    """
    global _SHARED_CACHE  # pylint: disable=global-statement
    if _SHARED_CACHE is None:
        with _SHARED_CACHE_LOCK:
            if _SHARED_CACHE is None:
                _SHARED_CACHE = ExpiringCache()
    return _SHARED_CACHE
