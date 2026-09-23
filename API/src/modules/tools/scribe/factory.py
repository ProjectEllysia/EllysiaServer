"""
scribe.factory
──────────────
Construcción de ``AIGenerator`` por inyección de dependencias.

``build_generator(module)`` decide qué estrategia usar leyendo
``SecOpsConfig.json`` (bloque ``tools.scribe``) — permitiendo una estrategia distinta por
módulo, p.ej. Ollama para Themis y OpenAI para Aegis — y la construye con las
credenciales del ``.env``. El modelo puede sobreescribirse desde la config.
"""

from __future__ import annotations

import logging
from typing import Optional

import src.modules.system.config_reading as CR
from src.modules.shared import assert_surface_enabled

from .generator import AIGenerator
from .strategies import ModelStrategy

logger = logging.getLogger(__name__)


def _build_strategy(name: str) -> ModelStrategy:
    """Instancia la estrategia ``name`` con credenciales de entorno/config.

    Despacha por ``ModelStrategy._registry`` (B4) en vez de una cadena
    ``if/elif`` por nombre — un proveedor nuevo se da de alta junto a su
    propia clase en ``strategies.py``, sin volver a tocar esta factory.
    """
    name = (name or "ollama").lower()
    overrides = CR.scribe_config().options_for(name)
    return ModelStrategy.resolve(name, overrides)


def _assert_strategy_allowed(name: str) -> None:
    """Rechaza una estrategia que saca datos del servidor si la IA externa está cerrada.

    Se comprueba sobre la clase, sin construirla: construir un proveedor
    externo exige sus credenciales, y la respuesta tiene que ser «cerrado»
    aunque falten.

    Args:
        name: Nombre de la estrategia tal como sale de la config (``"openai"``,
            ``"ollama"``…). Vacío equivale a ``"ollama"``, como en
            ``_build_strategy``.

    Raises:
        SurfaceDisabledError: Si la estrategia envía datos fuera del servidor y
            la superficie ``externalAi`` está cerrada.
    """
    strategy_class = ModelStrategy.resolve_class((name or "ollama").lower())
    if strategy_class.sends_data_off_server:
        assert_surface_enabled(CR.LaunchSurface.EXTERNAL_AI)


def build_generator(module: Optional[str] = None) -> AIGenerator:
    """
    Construye un ``AIGenerator`` para el módulo dado.

    Un proveedor que envía datos fuera del servidor (OpenAI, Google) solo se
    construye con la superficie ``externalAi`` de ``general.launch`` abierta;
    Ollama, que aloja quien opera la instalación, no depende de ella. No hay
    exención de rol: el generador no sabe en nombre de quién trabaja.

    Args:
        module: Nombre del módulo consumidor ('aegis', 'themis', …). Si la
            config no define una estrategia para él, se usa ``defaultStrategy``.

    Returns:
        Un AIGenerator listo para ``digest``.

    Raises:
        SurfaceDisabledError: Si la estrategia del módulo es externa y la IA
            externa está cerrada al público.
    """
    strategy_name = CR.scribe_config().strategy_for(module)
    logger.info("[scribe] módulo=%s → estrategia=%s", module, strategy_name)
    _assert_strategy_allowed(strategy_name)

    # La resiliencia se pasa desde aquí y no se deja en los defaults de
    # ``AIGenerator``: la factory es el único sitio que construye generadores
    # de producción, así que es donde la configuración tiene que entrar. Los
    # defaults de la firma siguen valiendo para quien instancia el generador
    # a mano en un test.
    resilience = CR.scribe_resilience_config()
    return AIGenerator(
        _build_strategy(strategy_name),
        max_retries=resilience.max_retries,
        retry_base=resilience.retry_base_seconds,
        breaker_threshold=resilience.breaker_threshold,
        breaker_timeout=resilience.breaker_timeout_seconds,
    )
