"""
services/retention.py — política de retención de Iris.

Job idempotente, invocado periódicamente por ``IrisMailboxScheduler``
(``services/mailbox/scheduling.py``, sin ``add_job`` propio para no sumar
un scheduler más al módulo -- mismo criterio que el chequeo de
notificaciones). Dos pasos independientes:

1. **Purgar el raw vencido** (``iris.rawMessageRetentionDays``, por defecto
   90 días): borra ``IrisRawMessage`` de cada análisis lo bastante viejo,
   conservando el análisis y sus resultados -- "el resultado puede
   conservarse sin el raw" es el comportamiento por defecto, no una
   opción.
2. **Borrar análisis enteros** solo si ``iris.analysisRetentionDays`` está
   activo (``> 0``; ``0`` lo desactiva). Con cascada real hacia
   ``IrisRuleResult`` y ``IrisDocument`` -- ver
   ``IrisAnalysisRepository.get_analyses_older_than`` sobre por qué esto va
   fila a fila por el ORM en vez de un ``DELETE`` masivo.

Volver a ejecutar ``run_retention()`` sin datos nuevos que purgar/borrar no
hace nada -- ambos pasos son consultas "¿qué sigue vencido?" seguidas de la
acción, sin ningún contador que pudiera desincronizarse entre ejecuciones.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

from ..repositories import IrisAnalysisRepository

logger = logging.getLogger(__name__)


def run_retention() -> Dict[str, Any]:
    """
    Ejecuta los dos pasos de retención y devuelve cuántas filas tocó cada uno:

    1. Purga de raw vencido.
    2. Borrado de análisis enteros (si está activado).

    Returns:
        dict: Diccionario con las claves ``purgedRawMessages`` y
            ``deletedAnalyses`` indicando cuántas filas fueron afectadas por
            cada paso.
    """
    config = CR.iris_config()
    now = utcnow_naive()

    with UnitOfWork() as uow:
        repo = IrisAnalysisRepository(uow)
        purged_raw = repo.purge_raw_messages_older_than(
            now - timedelta(days=config.raw_message_retention_days)
        )

        deleted_analyses = 0

        if config.analysis_retention_days > 0:
            for analysis in repo.get_analyses_older_than(
                now - timedelta(days=config.analysis_retention_days)
            ):
                repo.delete(analysis)
                deleted_analyses += 1

        report = {"purgedRawMessages": purged_raw, "deletedAnalyses": deleted_analyses}
        if purged_raw or deleted_analyses:
            logger.info("Retención de Iris: %s", report)
    
    return report
