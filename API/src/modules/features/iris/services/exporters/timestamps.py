"""Formato de fechas común a los exportadores."""

from __future__ import annotations

from datetime import datetime


def format_timestamp(moment: datetime) -> str:
    """Fecha en UTC con milisegundos y sufijo ``Z``, como exigen STIX y MISP.

    Args:
        moment: Instante naive en UTC (el formato con que Ellysia guarda las
            fechas).

    Returns:
        str: ``AAAA-MM-DDTHH:MM:SS.mmmZ``.
    """
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
