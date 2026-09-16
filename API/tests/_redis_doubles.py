"""Doble de Redis en memoria para los tests de la caché con caducidad.

La suite corta toda conexión a Redis (``tests/conftest.py``), así que los tests
que necesitan que la caché *guarde* algo le inyectan este doble. Tiene reloj
propio para hacer caducar valores sin esperar.

No es un test: pytest no lo recoge (no empieza por ``test_``). Vive en
``tests/`` porque el conftest de ahí pone el directorio en ``sys.path`` y así
lo importan igual los tests unitarios y los de integración.
"""

from __future__ import annotations


class InMemoryRedis:
    """Doble mínimo de ``redis.Redis`` con caducidad controlada a mano.

    Solo implementa lo que usa ``ExpiringCache``: ``get``, ``set`` con ``ex``,
    ``incr`` y ``expire``.

    Attributes:
        now_seconds: Reloj simulado, en segundos; lo mueve ``advance``.
        values_by_key: Bytes guardados, por clave completa (con prefijo).
        expiry_by_key: Instante de caducidad de cada clave que la tiene.
    """

    def __init__(self) -> None:
        """Arranca vacío y con el reloj en cero."""
        self.now_seconds = 0
        self.values_by_key = {}
        self.expiry_by_key = {}

    def advance(self, seconds: int) -> None:
        """Avanza el reloj simulado.

        Args:
            seconds: Segundos a avanzar.
        """
        self.now_seconds += seconds

    def is_alive(self, key: str) -> bool:
        """Dice si una clave existe y no ha caducado, borrándola si caducó.

        Args:
            key: Clave completa, con prefijo.

        Returns:
            bool: ``True`` si la clave sigue guardada.
        """
        expiry = self.expiry_by_key.get(key)
        if expiry is not None and expiry <= self.now_seconds:
            self.values_by_key.pop(key, None)
            self.expiry_by_key.pop(key, None)
        return key in self.values_by_key

    def get(self, key):
        """Devuelve los bytes guardados, o ``None``."""
        return self.values_by_key[key] if self.is_alive(key) else None

    def set(self, key, value, ex=None):
        """Guarda bytes con caducidad opcional en segundos."""
        self.values_by_key[key] = value
        if ex is not None:
            self.expiry_by_key[key] = self.now_seconds + ex

    def incr(self, key):
        """Incrementa un entero guardado como bytes y devuelve el nuevo valor."""
        current = int(self.values_by_key[key]) if self.is_alive(key) else 0
        self.values_by_key[key] = str(current + 1).encode()
        return current + 1

    def expire(self, key, seconds):
        """Fija la caducidad de una clave existente."""
        if self.is_alive(key):
            self.expiry_by_key[key] = self.now_seconds + seconds
