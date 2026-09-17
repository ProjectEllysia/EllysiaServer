"""
hygeia.services.export
───────────────────────
Volcado de una respuesta de estadísticas a CSV.

No calcula nada y no puede: recibe **la respuesta ya serializada** por el mismo
schema Marshmallow que sirve el JSON del endpoint, y la reordena en filas. Esa
es la garantía de que el CSV descargado y el JSON del mismo endpoint contienen
exactamente los mismos valores — no son dos caminos que haya que mantener en
sincronía, es un único camino con dos salidas.

Cada juego de datos tiene su propia forma de tabla, porque las preguntas son
distintas: el resumen de un activo es una fila por métrica, el ranking del
parque una fila por activo, y el panorama una tabla de dos columnas, porque es
una foto y no una serie.

Funciones puras: entra un diccionario, sale texto. Sin Flask, sin ORM.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: Columnas que describen la ventana cubierta. Viajan en **cada fila** en vez de
#: en una cabecera aparte: un CSV con dos tablas dentro deja de ser un CSV que
#: una hoja de cálculo pueda abrir, y perder el dato sería peor — un "máximo de
#: los últimos 30 días" calculado sobre 12 tiene que decirlo también aquí.
_WINDOW_COLUMNS = ("periodCoveredFrom", "periodCoveredTo", "isPeriodClipped")

#: Agregados de una métrica en el resumen de un activo, en el orden en que se
#: leen en la tabla del panel.
_SUMMARY_COLUMNS = (
    "min", "avg", "p95", "max", "current", "sampleCount",
    "timestampOfMax", "timestampOfMin",
)


def _render(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Escribe una tabla como texto CSV.

    Los valores ausentes salen como celda **vacía** y no como ``None``: una
    hoja de cálculo entiende una celda vacía como "sin dato", que es lo que
    significa, mientras que el texto ``None`` sería un dato falso. Los
    booleanos salen como ``true``/``false``, igual que en el JSON, y no como
    ``True``/``False`` de Python.

    Args:
        header: Nombres de las columnas, en camelCase como las claves del JSON.
        rows: Filas, cada una con tantos valores como columnas.

    Returns:
        str: El CSV completo, con el salto de línea ``\\r\\n`` que pide el
            formato.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([
            "" if value is None
            else ("true" if value is True else "false" if value is False else value)
            for value in row
        ])
    return buffer.getvalue()


def _window_values(payload: Mapping[str, Any]) -> List[Any]:
    """Los valores de las columnas de ventana de una respuesta.

    Args:
        payload: Respuesta ya serializada. Una que no traiga ventana (el
            panorama del parque) da celdas vacías, no un error.

    Returns:
        List[Any]: Un valor por columna de :data:`_WINDOW_COLUMNS`.
    """
    return [payload.get(column) for column in _WINDOW_COLUMNS]


def summary_to_csv(payload: Mapping[str, Any]) -> str:
    """Vuelca el resumen estadístico de un activo: una fila por métrica.

    Args:
        payload: Respuesta serializada de
            ``GET /hygeia/assets/<id>/stats/summary``.

    Returns:
        str: CSV con ``metric`` y los agregados de cada métrica, ordenadas por
            nombre para que dos descargas del mismo activo sean comparables
            línea a línea.
    """
    metrics: Dict[str, Any] = payload.get("metrics") or {}
    rows = [
        [name] + [summary.get(column) for column in _SUMMARY_COLUMNS] + _window_values(payload)
        for name, summary in sorted(metrics.items())
    ]
    return _render(("metric", *_SUMMARY_COLUMNS, *_WINDOW_COLUMNS), rows)


def tag_stats_to_csv(payload: Mapping[str, Any]) -> str:
    """Vuelca las métricas agregadas de una etiqueta: una fila por métrica.

    La etiqueta y la agregación se repiten en cada fila por el mismo motivo
    que la ventana: es lo que permite juntar en una hoja de cálculo las
    descargas de dos etiquetas y seguir sabiendo cuál es cuál.

    Args:
        payload: Respuesta serializada de ``GET /hygeia/stats/by-tag/<tagId>``.

    Returns:
        str: CSV con la etiqueta, la métrica, su unidad, el valor combinado y
            cuántos activos aportaron datos.
    """
    tag = payload.get("tag") or {}
    metrics: Dict[str, Any] = payload.get("metrics") or {}
    rows = [
        [
            tag.get("id"), tag.get("name"), payload.get("agg"), payload.get("assetCount"),
            name, aggregate.get("unit"), aggregate.get("value"), aggregate.get("assetsWithData"),
        ] + _window_values(payload)
        for name, aggregate in sorted(metrics.items())
    ]
    return _render(
        (
            "tagId", "tagName", "agg", "assetCount",
            "metric", "unit", "value", "assetsWithData", *_WINDOW_COLUMNS,
        ),
        rows,
    )


def ranking_to_csv(payload: Mapping[str, Any]) -> str:
    """Vuelca el ranking de activos por una métrica: una fila por activo.

    El orden de las filas es el que decidió el servidor, y ``position`` lo
    deja escrito: una hoja de cálculo reordena por cualquier columna en dos
    clics, y sin la posición no habría forma de recuperar el ranking original.

    Args:
        payload: Respuesta serializada de ``GET /hygeia/stats/ranking``.

    Returns:
        str: CSV con la posición, el activo, su valor y cuántas muestras lo
            sostienen.
    """
    metric = payload.get("metric")
    unit = payload.get("unit")
    aggregation = payload.get("agg")
    order = payload.get("order")
    window = _window_values(payload)
    rows = [
        [
            position, entry.get("assetId"), entry.get("hostname"),
            metric, unit, aggregation, order, entry.get("value"), entry.get("sampleCount"),
        ] + window
        for position, entry in enumerate(payload.get("assets") or [], start=1)
    ]
    return _render(
        (
            "position", "assetId", "hostname", "metric", "unit", "agg", "order",
            "value", "sampleCount", *_WINDOW_COLUMNS,
        ),
        rows,
    )


def overview_to_csv(payload: Mapping[str, Any]) -> str:
    """Vuelca el panorama del parque como una tabla de medida y valor.

    El panorama no es una serie ni una lista: es una foto del estado actual con
    recuentos de naturalezas distintas (activos por estado, anomalías por
    severidad, un tiempo medio, un instante). Una tabla de dos columnas es la
    forma honesta de volcarlo; forzarlo a una fila ancha obligaría a inventar
    un nombre de columna por cada clave anidada.

    Los recuentos anidados se aplanan con la clave compuesta que ya usan en el
    JSON (``assetsByStatus.online``), así que la ruta del dato es la misma en
    los dos formatos.

    Args:
        payload: Respuesta serializada de ``GET /hygeia/stats/overview``.

    Returns:
        str: CSV de dos columnas, ``measure`` y ``value``.
    """
    rows: List[Tuple[str, Any]] = [("assetCount", payload.get("assetCount"))]
    for group in ("assetsByStatus", "openAnomaliesBySeverity"):
        for key, count in sorted((payload.get(group) or {}).items()):
            rows.append((f"{group}.{key}", count))
    rows += [
        ("acknowledgedAnomalyCount", payload.get("acknowledgedAnomalyCount")),
        ("averageUptimeSec", payload.get("averageUptimeSec")),
        ("lastActivityAt", payload.get("lastActivityAt")),
    ]
    return _render(("measure", "value"), rows)


#: Qué función vuelca cada juego de datos. Añadir un endpoint exportable es
#: añadir una entrada aquí y su volcador, no una rama en el endpoint.
CSV_RENDERERS = {
    "summary": summary_to_csv,
    "tag-stats": tag_stats_to_csv,
    "ranking": ranking_to_csv,
    "overview": overview_to_csv,
}


def build_csv(dataset: str, payload: Mapping[str, Any]) -> Tuple[bytes, str]:
    """Vuelca una respuesta de estadísticas y compone el nombre de su fichero.

    El texto se codifica en UTF-8 **con BOM**. No es un capricho: sin él, Excel
    interpreta el fichero en la codificación local de Windows y un hostname o
    una etiqueta con acentos aparecen ilegibles. El BOM no molesta a ninguna
    otra herramienta que lea CSV.

    Args:
        dataset: Clave del juego de datos (``summary``, ``tag-stats``,
            ``ranking``, ``overview``).
        payload: La respuesta **ya serializada** por el schema del endpoint,
            que es lo que garantiza que el CSV y el JSON digan lo mismo.

    Returns:
        Tuple[bytes, str]: El contenido del fichero y su nombre.

    Raises:
        KeyError: Si el juego de datos no está registrado; es un error de
            programación, no un dato de entrada del usuario.
    """
    content = CSV_RENDERERS[dataset](payload)
    return content.encode("utf-8-sig"), f"hygeia-{dataset}.csv"


def build_export_file_name(
    dataset: str, scope_label: Optional[str], period: Optional[str], extension: str = "csv",
) -> str:
    """Nombre de fichero de una exportación de estadísticas.

    Lleva el alcance y el periodo, que es lo que distingue dos descargas en la
    carpeta de descargas: ``hygeia-summary-host-web-24h.csv`` se reconoce y
    ``hygeia-summary.csv (3)`` no. El alcance se normaliza a minúsculas, sin
    acentos y con guiones, porque un hostname o una etiqueta pueden traer
    cualquier carácter.

    Args:
        dataset: Juego de datos (``summary``, ``tag-stats``, ``ranking``,
            ``overview``).
        scope_label: Nombre del activo o de la etiqueta, o ``None`` en los
            alcances que no tienen uno (el parque).
        period: Periodo pedido (``24h``), o ``None`` si el juego de datos no
            tiene periodo (el panorama).
        extension: Extensión del fichero, sin punto. Por defecto ``"csv"``;
            el mismo dataset exportado en PDF pasa ``"pdf"``.

    Returns:
        str: El nombre con su extensión; sin partes vacías ni guiones
            colgando.
    """
    slug = None
    if scope_label:
        ascii_label = (
            unicodedata.normalize("NFD", scope_label).encode("ascii", "ignore").decode("ascii")
        )
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_label.lower()).strip("-") or None
    parts = [f"hygeia-{dataset}", slug, period]
    return "-".join(part for part in parts if part) + f".{extension}"
