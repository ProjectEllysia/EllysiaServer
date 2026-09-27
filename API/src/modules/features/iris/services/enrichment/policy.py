"""
Límites comunes del enriquecimiento: cuántas consultas por minuto y cuánto vale una respuesta.

Cada proveedor externo (RDAP, cada servicio de reputación, la expansión de
URLs) tiene su cupo por minuto. Superarlo no es un error del usuario: la
consulta responde ``rate_limited`` y se puede repetir en un rato. El cupo es
por proceso —cada proceso de la API lleva su cuenta—, que basta para no
castigar a un proveedor ni agotar una clave gratuita; la cuota real la
imponen además los ``@limiter`` de cada endpoint, por usuario.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional

from src.modules.shared import utcnow_naive

#: Ventana del cupo por proveedor, en segundos.
_WINDOW_SECONDS = 60.0


class ProviderRateLimiter:
    """Cupo de consultas por minuto de cada proveedor, compartido por los hilos del proceso."""

    def __init__(self) -> None:
        """Crea un limitador sin consultas registradas."""
        self._lock = threading.Lock()
        self._calls_by_provider: Dict[str, Deque[float]] = {}

    def try_acquire(self, provider: str, requests_per_minute: int, now: Optional[float] = None) -> bool:
        """Reserva una consulta al proveedor si le queda cupo.

        Args:
            provider: Nombre del proveedor (``rdap``, ``virustotal``…).
            requests_per_minute: Cupo; ``0`` o menos cierra el proveedor.
            now: Instante en segundos monótonos; ``None`` (por defecto) usa el
                reloj. Existe para los tests.

        Returns:
            bool: ``True`` si hay cupo y la consulta queda contada; ``False``
                si no.
        """
        moment = time.monotonic() if now is None else now
        with self._lock:
            calls = self._calls_by_provider.setdefault(provider, deque())
            while calls and moment - calls[0] >= _WINDOW_SECONDS:
                calls.popleft()
            if len(calls) >= requests_per_minute:
                return False
            calls.append(moment)
            return True

    def reset(self) -> None:
        """Olvida todas las consultas contadas (entre tests)."""
        with self._lock:
            self._calls_by_provider.clear()


#: Limitador del proceso.
RATE_LIMITER = ProviderRateLimiter()


def is_fresh(expires_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    """Si una entrada de caché sigue valiendo.

    Args:
        expires_at: Cuándo caduca; ``None`` si no se llegó a guardar.
        now: Instante de referencia; ``None`` (por defecto) es ahora.

    Returns:
        bool: ``True`` si no ha caducado.
    """
    return expires_at is not None and expires_at > (now or utcnow_naive())


def expiry_after(ttl: timedelta, now: Optional[datetime] = None) -> datetime:
    """Cuándo caduca una entrada que se guarda ahora.

    Args:
        ttl: Tiempo de vida.
        now: Instante de referencia; ``None`` (por defecto) es ahora.

    Returns:
        datetime: ``now + ttl``.
    """
    return (now or utcnow_naive()) + ttl
