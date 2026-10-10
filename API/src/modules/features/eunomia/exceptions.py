"""
Excepciones específicas del módulo Eunomia.

Hierarchy:
    EunomiaError (EllysiaException)
    └── FrameworkNotFoundError (404)
"""

from __future__ import annotations

from src.modules.shared._exceptions import EllysiaException, EntityNotFoundError, ErrorCode


class EunomiaError(EllysiaException):
    """Excepción base para todos los errores del módulo Eunomia."""
    default_code = ErrorCode.UNKNOWN_ERROR
    default_status_code = 500


class FrameworkNotFoundError(EntityNotFoundError, EunomiaError):
    """El catálogo no tiene ese marco, o no tiene esa versión de él."""

    entity_label = "Marco de cumplimiento"
    id_field = "framework"
