"""
Acceso a datos del módulo Hygeia.

Extiende BaseRepository para CRUD tipado sobre MonitoredAsset, AssetSnapshot,
Anomaly y HygeiaTag. Las lecturas se construyen con ``build_repository``
(sesión ambiental, sin demarcar transacción); las escrituras, dentro de un
``UnitOfWork``. Ningún método de este módulo crea ni cierra sesiones.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Dict, List, Literal, Mapping, Optional, Tuple

from sqlalchemy import func, update
from sqlalchemy.orm.attributes import InstrumentedAttribute

from src.modules.infrastructure import BaseRepository

from .model import Anomaly, AssetSnapshot, AssetTag, HygeiaTag, MonitoredAsset

#: Cómo se resume una métrica dentro de un cubo de tiempo de un mismo activo.
BucketAggregation = Literal["min", "avg", "max"]

#: Cómo se combinan entre activos los valores ya resumidos por cubo.
AssetAggregation = Literal["sum", "avg", "max"]

_BUCKET_AGGREGATE_FUNCTIONS: Mapping[str, Callable] = {
    "min": func.min, "avg": func.avg, "max": func.max,
}
_ASSET_AGGREGATE_FUNCTIONS: Mapping[str, Callable] = {
    "sum": func.sum, "avg": func.avg, "max": func.max,
}


def _bucket_id_expression(bucket_seconds: int):
    """Número de cubo de cada snapshot: ``floor(epoch(received_at) / bucket_seconds)``.

    Es portable entre Postgres y el SQLite de los tests: en SQLite el
    ``extract`` se compila a ``strftime('%s')`` (división entera, que para
    valores positivos ya aplana) y en Postgres a doble precisión con
    ``floor`` — mismo resultado.

    Args:
        bucket_seconds: Tamaño del cubo en segundos; positivo.

    Returns:
        La expresión SQL etiquetada como ``bucket_id``.
    """
    return func.floor(
        func.extract("epoch", AssetSnapshot.received_at) / bucket_seconds
    ).label("bucket_id")


def _bucket_start(bucket_id, bucket_seconds: int) -> datetime:
    """Inicio de un cubo como datetime naive-UTC, a partir de su número.

    Args:
        bucket_id: Número de cubo tal como lo devuelve la consulta; ``int``,
            ``float`` o ``Decimal`` según el motor.
        bucket_seconds: Tamaño del cubo en segundos.

    Returns:
        datetime: El instante de inicio del cubo, sin zona horaria.
    """
    return datetime.fromtimestamp(
        int(bucket_id) * bucket_seconds, tz=timezone.utc,
    ).replace(tzinfo=None)


def _resolve_aggregate(functions_by_name: Mapping[str, Callable], name: str) -> Callable:
    """Traduce el nombre de una agregación a su función SQL.

    Args:
        functions_by_name: Tabla de agregaciones admitidas en este punto.
        name: Nombre pedido (``"max"``, ``"sum"``…).

    Returns:
        Callable: La función de SQLAlchemy (``func.max``…).

    Raises:
        ValueError: Si el nombre no está en la tabla; es un error de
            programación, porque el schema del endpoint valida el parámetro.
    """
    if name not in functions_by_name:
        raise ValueError(
            f"Agregación {name!r} no admitida aquí; valores válidos: {sorted(functions_by_name)}"
        )
    return functions_by_name[name]


def _validate_bucket_count(
    since: datetime, until: datetime, bucket_seconds: int, max_buckets: int,
) -> None:
    """Rechaza un cubo tan fino que la ventana produciría más cubos de los permitidos.

    Las consultas multi-activo no llevan ``LIMIT``: con varios activos, un
    tope de filas cortaría la serie de los últimos activos del orden sin que
    nada lo dijera. En su lugar se comprueba de antemano que la ventana cabe
    en ``max_buckets`` cubos por activo (``+1`` porque la ventana no tiene por
    qué empezar alineada con un cubo y puede asomar a uno más).

    Args:
        since: Inicio de la ventana.
        until: Fin de la ventana.
        bucket_seconds: Tamaño del cubo en segundos.
        max_buckets: Máximo de cubos por activo.

    Raises:
        ValueError: Si ``bucket_seconds`` no es positivo o la ventana
            necesitaría más de ``max_buckets`` cubos.
    """
    if bucket_seconds <= 0:
        raise ValueError(f"El cubo debe ser positivo; se pidió {bucket_seconds} s")
    bucket_count = math.ceil((until - since).total_seconds() / bucket_seconds) + 1
    if bucket_count > max_buckets:
        raise ValueError(
            f"Un cubo de {bucket_seconds} s sobre esta ventana da {bucket_count} cubos; "
            f"el máximo es {max_buckets}"
        )


class MonitoredAssetRepository(BaseRepository[MonitoredAsset]):
    """Acceso a datos de MonitoredAsset."""

    _MODEL = MonitoredAsset

    def get_by_user(self, user_id: int) -> List[MonitoredAsset]:
        """Devuelve todos los activos monitorizados de un usuario, más recientes primero."""
        return (
            self._session.query(MonitoredAsset)
            .filter(MonitoredAsset.user_id == user_id)
            .order_by(MonitoredAsset.created_at.desc())
            .all()
        )

    def get_by_users(self, user_ids: List[int]) -> List[MonitoredAsset]:
        """Activos de un conjunto de usuarios, para el informe de organización.

        Ordena por dueño y luego por hostname para que el informe salga ya
        agrupado sin reordenar en Python. Una lista vacía devuelve una lista
        vacía en vez de todos los activos del sistema: un ``IN ()`` mal formado
        aquí sería una fuga de datos, no un error de rendimiento.
        """
        if not user_ids:
            return []
        return (
            self._session.query(MonitoredAsset)
            .filter(MonitoredAsset.user_id.in_(user_ids))
            .order_by(MonitoredAsset.user_id.asc(), MonitoredAsset.hostname.asc())
            .all()
        )

    def get_by_tag(self, user_id: int, tag_id: int) -> List[MonitoredAsset]:
        """Activos **del usuario** que llevan una etiqueta, ordenados por hostname.

        El filtro por dueño es la garantía de privacidad de las estadísticas
        por etiqueta: una etiqueta de sistema la usa todo el mundo, y sin él
        el agregado de "producción" incluiría los servidores de otros
        usuarios. Que la etiqueta sea visible para el usuario lo comprueba el
        manager antes de llamar aquí.

        Args:
            user_id: Dueño de los activos.
            tag_id: Etiqueta cuyos activos se buscan.

        Returns:
            List[MonitoredAsset]: Los activos, vacía si la etiqueta no está en
                ninguno del usuario.
        """
        return (
            self._session.query(MonitoredAsset)
            .join(AssetTag, AssetTag.c.asset_id == MonitoredAsset.id)
            .filter(AssetTag.c.tag_id == tag_id, MonitoredAsset.user_id == user_id)
            .order_by(MonitoredAsset.hostname.asc(), MonitoredAsset.id.asc())
            .all()
        )

    def count_by_status(self, user_id: int) -> Dict[str, int]:
        """Cuántos activos del usuario hay en cada estado de presencia.

        Args:
            user_id: Dueño de los activos.

        Returns:
            Dict[str, int]: ``{estado: activos}``. Los estados sin ningún
                activo no aparecen; el manager los completa con 0.
        """
        rows = (
            self._session.query(MonitoredAsset.status, func.count(MonitoredAsset.id))
            .filter(MonitoredAsset.user_id == user_id)
            .group_by(MonitoredAsset.status)
            .all()
        )
        return dict(rows)

    def get_average_online_uptime(self, user_id: int) -> Optional[float]:
        """Uptime medio, en segundos, de los activos del usuario que están en línea.

        Solo los ``online``: el ``uptime_sec`` de un activo caído es el del
        último heartbeat que mandó, y meterlo en la media la inflaría con un
        equipo que ya no está encendido.

        Args:
            user_id: Dueño de los activos.

        Returns:
            Optional[float]: La media, o ``None`` si no hay ningún activo en
                línea que haya reportado su uptime.
        """
        average = (
            self._session.query(func.avg(MonitoredAsset.uptime_sec))
            .filter(
                MonitoredAsset.user_id == user_id,
                MonitoredAsset.status == "online",
                MonitoredAsset.uptime_sec.isnot(None),
            )
            .scalar()
        )
        return None if average is None else float(average)

    def get_last_activity(self, user_id: int) -> Optional[datetime]:
        """Último heartbeat recibido de cualquiera de los activos del usuario.

        Args:
            user_id: Dueño de los activos.

        Returns:
            Optional[datetime]: El ``last_seen_at`` más reciente, o ``None`` si
                ningún activo ha reportado nunca.
        """
        return (
            self._session.query(func.max(MonitoredAsset.last_seen_at))
            .filter(MonitoredAsset.user_id == user_id)
            .scalar()
        )

    def get_by_agent_key_id(self, agent_key_id: str) -> Optional[MonitoredAsset]:
        """Localiza el activo cuya clave de agente empieza por ``agent_key_id``.

        Es la única consulta que ejecuta la superficie de ingesta: el índice
        sobre ``agent_key_id`` la resuelve en O(1), una sola fila, sin tener
        que recorrer ni verificar el Argon2 de ningún otro activo.
        """
        return self.get_by_field("agent_key_id", agent_key_id)

    def count_by_user(self, user_id: int) -> int:
        """Cuenta cuántos activos tiene ya dados de alta un usuario (para la cuota)."""
        return (
            self._session.query(MonitoredAsset)
            .filter(MonitoredAsset.user_id == user_id)
            .count()
        )

    def get_active_for_presence_check(self) -> List[MonitoredAsset]:
        """Activos candidatos a que el detector de presencia los reevalúe.

        Excluye los que ya están ``offline``: un job que corre cada minuto
        no debe seguir tocando activos que ya se declararon caídos.
        """
        return (
            self._session.query(MonitoredAsset)
            .filter(MonitoredAsset.status.in_(["online", "stale"]))
            .all()
        )

    def transition_status_if_still_silent(
        self, asset_id: int, cutoff: datetime, from_status: str, new_status: str,
    ) -> bool:
        """Realiza la transición de presencia con una escritura condicional atómica.

        Si se leyera ``last_seen_at`` en Python y se decidiera la transición
        antes de escribir, un heartbeat que llegase justo en ese instante
        dejaría la lectura obsoleta y el activo se marcaría caído pese a
        haber respondido. Al mover tanto la condición ``last_seen_at < cutoff``
        como el estado de origen esperado al propio UPDATE, es Postgres quien
        decide de forma atómica si el activo seguía realmente en el estado y
        silencio esperados en el momento de escribir — a salvo también de dos
        ejecuciones del job solapadas.

        Args:
            asset_id: Activo a transicionar.
            cutoff: Instante límite; solo transiciona si ``last_seen_at`` es
                anterior a este valor.
            from_status: Estado en el que debe estar la fila para que la
                transición aplique ("online" | "stale").
            new_status: Nuevo estado ("stale" | "offline").

        Returns:
            True si la fila se actualizó (seguía en ``from_status`` y en
            silencio), False si no (un heartbeat la actualizó primero, otro
            job ya la transicionó, o ya no cumplía la condición).
        """
        result = self._session.execute(
            update(MonitoredAsset)
            .where(
                MonitoredAsset.id == asset_id,
                MonitoredAsset.status == from_status,
                MonitoredAsset.last_seen_at < cutoff,
            )
            .values(status=new_status)
        )
        return result.rowcount > 0


class AssetSnapshotRepository(BaseRepository[AssetSnapshot]):
    """Acceso a datos de AssetSnapshot (heartbeats)."""

    _MODEL = AssetSnapshot

    def get_series(
        self, asset_id: int, since: Optional[datetime] = None,
        until: Optional[datetime] = None, limit: int = 1000,
    ) -> List[AssetSnapshot]:
        """Devuelve los ``limit`` snapshots **más recientes** de un activo, en orden cronológico.

        El recorte se aplica por la cola, no por la cabeza: se ordena de más
        nuevo a más viejo, se corta a ``limit`` y se reinvierte en memoria. Un
        ``ORDER BY ... ASC`` con ``LIMIT`` devolvería los puntos más antiguos,
        que para una gráfica de pulso es justo lo contrario de lo que se pide.

        El eje es ``received_at`` (reloj del servidor), nunca ``collected_at``
        (reloj del agente): ``check_clock_skew`` solo acota la deriva del
        agente a una banda de ± unos minutos, y dentro de esa banda un reloj
        desviado bastaría para desordenar la serie o para anclar la ventana
        en filas viejas. Los filtros ``since``/``until`` se aplican sobre el
        mismo campo, para que ventana y orden hablen del mismo reloj.

        Args:
            asset_id: Activo cuya serie se consulta.
            since: Límite inferior opcional de ``received_at``.
            until: Límite superior opcional de ``received_at``.
            limit: Máximo de puntos a devolver, para no cargar un histórico sin fin.

        Returns:
            Lista de snapshots ordenados de más antiguo a más reciente.
        """
        query = self._session.query(AssetSnapshot).filter(AssetSnapshot.asset_id == asset_id)
        if since is not None:
            query = query.filter(AssetSnapshot.received_at >= since)
        if until is not None:
            query = query.filter(AssetSnapshot.received_at <= until)

        rows = query.order_by(AssetSnapshot.received_at.desc()).limit(limit).all()
        rows.reverse()
        return rows

    def get_series_bucketed(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, asset_id: int, bucket: int, since: Optional[datetime] = None,
        until: Optional[datetime] = None, limit: int = 1000,
        aggregation: BucketAggregation = "max",
    ) -> List[dict]:
        """Serie temporal agregada por cubos de ``bucket`` segundos.

        Un punto por cubo con el agregado pedido de cada métrica
        desnormalizada. Por defecto **el máximo**: es el agregado que no se
        traga un pico puntual dentro de un cubo de ítems — para una gráfica de
        monitorización, perder el pico sería mentir sobre el tramo. ``avg`` es
        la media **aritmética** de los heartbeats del cubo, también para la
        potencia: la misma media que usa el resumen estadístico, para que una
        gráfica y un resumen del mismo tramo no den dos medias distintas (la
        ponderada por duración se queda en el cálculo de energía). El
        percentil 95 no se resuelve aquí: no hay una función SQL portable
        entre Postgres y SQLite, y lo calcula el manager en Python.

        Los cubos sin ningún heartbeat simplemente no existen en el resultado:
        la ausencia de señal es precisamente el dato que el frontend pinta como
        tiempo apagado.

        El instante del punto es el **inicio** del cubo (suelo de
        ``epoch(received_at) / bucket``), así el punto se lee como "el estado
        de este intervalo" y el eje sigue siendo ``received_at``, el mismo de
        la serie cruda.

        El agrupado lo hace ``_bucket_id_expression``, portable entre Postgres
        y SQLite.

        ``disk_max_mount`` se queda fuera del agregado, igual que
        ``power_estimated``/``power_source``: el montaje asociado al máximo,
        o la fuente asociada al pico de potencia, exigirían una función de
        ventana por cubo para un dato que el gráfico de líneas no consume.
        Los tres llegan ``None`` y se documentan en el contrato; la interfaz
        los toma del endpoint de últimas métricas.

        Args:
            asset_id: Activo cuya serie se consulta.
            bucket: Tamaño del cubo en segundos.
            since: Límite inferior opcional de ``received_at``.
            until: Límite superior opcional de ``received_at``.
            limit: Tope de cubos, por defensa (una ventana de 30 días con un
                cubo de 1 s sería 2,5 millones de filas).
            aggregation: Cómo se resume cada cubo: ``"min"``, ``"avg"`` o
                ``"max"``. Por defecto ``"max"``.

        Returns:
            Lista de puntos agregados (diccionarios en la misma forma que
            ``AssetSnapshot.to_dict``), de más antiguo a más reciente.

        Raises:
            ValueError: Si ``aggregation`` no es una de las admitidas.
        """
        aggregate = _resolve_aggregate(_BUCKET_AGGREGATE_FUNCTIONS, aggregation)
        bucket_id = _bucket_id_expression(bucket)

        query = (
            self._session.query(
                bucket_id,
                aggregate(AssetSnapshot.cpu_pct).label("cpu_pct"),
                aggregate(AssetSnapshot.mem_pct).label("mem_pct"),
                aggregate(AssetSnapshot.swap_pct).label("swap_pct"),
                aggregate(AssetSnapshot.load1).label("load1"),
                aggregate(AssetSnapshot.disk_max_pct).label("disk_max_pct"),
                aggregate(AssetSnapshot.net_rx_bps).label("net_rx_bps"),
                aggregate(AssetSnapshot.net_tx_bps).label("net_tx_bps"),
                aggregate(AssetSnapshot.power_watts).label("power_watts"),
            )
            .filter(AssetSnapshot.asset_id == asset_id)
        )
        if since is not None:
            query = query.filter(AssetSnapshot.received_at >= since)
        if until is not None:
            query = query.filter(AssetSnapshot.received_at <= until)

        rows = (
            query.group_by(bucket_id)
            .order_by(bucket_id.asc())
            .limit(limit)
            .all()
        )

        return [
            {
                "collectedAt": _bucket_start(row.bucket_id, bucket),
                "receivedAt": _bucket_start(row.bucket_id, bucket),
                "cpuPct": row.cpu_pct,
                "memPct": row.mem_pct,
                "swapPct": row.swap_pct,
                "load1": row.load1,
                "diskMaxPct": row.disk_max_pct,
                "diskMaxMount": None,
                "netRxBps": row.net_rx_bps,
                "netTxBps": row.net_tx_bps,
                "powerWatts": row.power_watts,
                "powerEstimated": None,
                "powerSource": None,
            }
            for row in rows
        ]

    def get_power_samples(
        self, asset_id: int, since: datetime, until: datetime,
    ) -> List[tuple]:
        """Instantes y vatios de un activo en una ventana, para el cálculo de energía.

        A diferencia de ``get_series``, no aplica ``limit``: la media ponderada
        por duración del consumo eléctrico necesita **todos** los
        intervalos de la ventana para no subestimar el tiempo observado, y
        una ventana de 30 días a 15 s de cadencia son ~172.000 filas —
        demasiado para el tope de la serie gráfica (1.000 puntos), pero
        trivial cuando se proyectan solo dos columnas en vez del snapshot
        completo.

        Los snapshots sin lectura de potencia (``power_watts IS NULL``, sea
        porque el agente no tiene fuente compatible o porque son anteriores
        a que el agente reportase potencia) se excluyen: para el cálculo de
        energía equivalen a un hueco, no a un cero.

        Returns:
            Lista de ``(received_at, power_watts)`` ordenada de más antiguo
            a más reciente.
        """
        rows = (
            self._session.query(AssetSnapshot.received_at, AssetSnapshot.power_watts)
            .filter(
                AssetSnapshot.asset_id == asset_id,
                AssetSnapshot.received_at >= since,
                AssetSnapshot.received_at <= until,
                AssetSnapshot.power_watts.isnot(None),
            )
            .order_by(AssetSnapshot.received_at.asc())
            .all()
        )
        return [(row.received_at, row.power_watts) for row in rows]

    def get_metric_aggregates_by_asset(
        self, asset_ids: List[int], column: InstrumentedAttribute,
        since: datetime, until: datetime,
    ) -> Dict[int, Tuple[Optional[float], Optional[float], int]]:
        """Media, máximo y número de muestras de una métrica por activo, en una sola consulta.

        Es el camino de las estadísticas por etiqueta: se agrega en la base de
        datos (``GROUP BY asset_id``) en vez de traer las muestras, porque 30
        días de heartbeats de todos los activos de una etiqueta son millones
        de filas y aquí solo hacen falta tres números por activo. Los
        snapshots sin valor para la métrica no cuentan: son ausencia de dato.

        Args:
            asset_ids: Activos a consultar; ya filtrados por dueño. Una lista
                vacía devuelve un diccionario vacío sin consultar.
            column: Columna de ``AssetSnapshot`` de la métrica.
            since: Inicio de la ventana, sobre ``received_at``, inclusivo.
            until: Fin de la ventana, sobre ``received_at``, inclusivo.

        Returns:
            Dict[int, Tuple[Optional[float], Optional[float], int]]: Por cada
                ``asset_id`` pedido, en el mismo orden, ``(media, máximo,
                muestras)``. Un activo sin muestras en la ventana conserva su
                entrada como ``(None, None, 0)``.
        """
        if not asset_ids:
            return {}
        rows = (
            self._session.query(
                AssetSnapshot.asset_id,
                func.avg(column).label("average"),
                func.max(column).label("maximum"),
                func.count(column).label("sample_count"),
            )
            .filter(
                AssetSnapshot.asset_id.in_(asset_ids),
                AssetSnapshot.received_at >= since,
                AssetSnapshot.received_at <= until,
                column.isnot(None),
            )
            .group_by(AssetSnapshot.asset_id)
            .all()
        )
        aggregates_found = {
            row.asset_id: (float(row.average), float(row.maximum), row.sample_count)
            for row in rows
        }
        return {asset_id: aggregates_found.get(asset_id, (None, None, 0)) for asset_id in asset_ids}

    def get_asset_ids_with_estimated_power(
        self, asset_ids: List[int], since: datetime, until: datetime,
    ) -> set[int]:
        """Qué activos tuvieron alguna lectura de potencia estimada por modelo en la ventana.

        Una potencia estimada (``power_estimated``, p. ej. el modelo de
        utilización de Windows) no es una medición, y un total de energía que
        la incluye tiene que poder decirlo. Basta una lectura estimada en la
        ventana para marcar al activo: sus kWh ya no son medidos del todo.

        Args:
            asset_ids: Activos a consultar; ya filtrados por dueño. Una lista
                vacía devuelve un conjunto vacío sin consultar.
            since: Inicio de la ventana, sobre ``received_at``, inclusivo.
            until: Fin de la ventana, sobre ``received_at``, inclusivo.

        Returns:
            set[int]: Los ``asset_id`` con al menos una lectura estimada.
        """
        if not asset_ids:
            return set()
        rows = (
            self._session.query(AssetSnapshot.asset_id)
            .filter(
                AssetSnapshot.asset_id.in_(asset_ids),
                AssetSnapshot.received_at >= since,
                AssetSnapshot.received_at <= until,
                AssetSnapshot.power_estimated.is_(True),
            )
            .distinct()
            .all()
        )
        return {row.asset_id for row in rows}

    def get_metric_samples_by_asset(
        self, asset_ids: List[int], column: InstrumentedAttribute,
        since: datetime, until: datetime,
    ) -> Dict[int, List[Tuple[datetime, float]]]:
        """Muestras crudas de una métrica para varios activos, en una sola consulta.

        Es el camino para lo que SQL no resuelve de forma portable —el
        percentil 95, el instante del máximo—: el resumen se calcula después
        en Python con ``services/stats.py`` sobre estas series. Proyecta solo
        dos columnas, igual que ``get_power_samples``, porque recorre todos
        los heartbeats de la ventana.

        Los snapshots sin valor para la métrica se excluyen: son ausencia de
        dato, no un cero.

        Args:
            asset_ids: Activos a consultar; ya filtrados por dueño en el
                manager. Una lista vacía devuelve un diccionario vacío sin
                consultar: un ``IN ()`` mal formado aquí sería una fuga de
                datos, no un error de rendimiento.
            column: Columna de ``AssetSnapshot`` de la métrica (la de
                ``MetricDefinition.column``).
            since: Inicio de la ventana, sobre ``received_at``, inclusivo.
            until: Fin de la ventana, sobre ``received_at``, inclusivo.

        Returns:
            Dict[int, List[Tuple[datetime, float]]]: Por cada ``asset_id``
                pedido, sus ``(received_at, valor)`` de más antiguo a más
                reciente. Un activo sin muestras en la ventana conserva su
                entrada con una lista vacía.
        """
        if not asset_ids:
            return {}
        rows = (
            self._session.query(
                AssetSnapshot.asset_id, AssetSnapshot.received_at, column.label("value"),
            )
            .filter(
                AssetSnapshot.asset_id.in_(asset_ids),
                AssetSnapshot.received_at >= since,
                AssetSnapshot.received_at <= until,
                column.isnot(None),
            )
            .order_by(AssetSnapshot.asset_id.asc(), AssetSnapshot.received_at.asc())
            .all()
        )
        samples_by_asset: Dict[int, List[Tuple[datetime, float]]] = {
            asset_id: [] for asset_id in asset_ids
        }
        for row in rows:
            samples_by_asset[row.asset_id].append((row.received_at, float(row.value)))
        return samples_by_asset

    def get_bucketed_metric_by_asset(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, asset_ids: List[int], column: InstrumentedAttribute, bucket_seconds: int,
        since: datetime, until: datetime, *, within_bucket: BucketAggregation = "max",
        max_buckets: int = 1000,
    ) -> Dict[int, List[Tuple[datetime, float]]]:
        """Serie por cubos de una métrica, una por activo, en una sola consulta.

        Generaliza ``get_series_bucketed`` a una lista de activos y a una sola
        métrica, con el mismo agrupado portable (``_bucket_id_expression``).
        Los cubos sin ningún heartbeat con dato no aparecen: la ausencia de
        señal es el dato que la gráfica pinta como tiempo sin reportar.

        Args:
            asset_ids: Activos a consultar; ya filtrados por dueño. Una lista
                vacía devuelve un diccionario vacío sin consultar.
            column: Columna de ``AssetSnapshot`` de la métrica.
            bucket_seconds: Tamaño del cubo en segundos; positivo.
            since: Inicio de la ventana, sobre ``received_at``, inclusivo.
            until: Fin de la ventana, sobre ``received_at``, inclusivo.
            within_bucket: Cómo se resume el cubo de un activo: ``"min"``,
                ``"avg"`` o ``"max"``. Por defecto ``"max"``, el mismo que usa
                la serie de un activo para no tragarse un pico.
            max_buckets: Máximo de cubos por activo. Por defecto ``1000``.

        Returns:
            Dict[int, List[Tuple[datetime, float]]]: Por cada ``asset_id``
                pedido, sus ``(inicio_del_cubo, valor)`` en orden cronológico;
                un activo sin datos en la ventana conserva su entrada vacía.

        Raises:
            ValueError: Si la agregación no es válida o la ventana necesita
                más de ``max_buckets`` cubos.
        """
        aggregate = _resolve_aggregate(_BUCKET_AGGREGATE_FUNCTIONS, within_bucket)
        _validate_bucket_count(since, until, bucket_seconds, max_buckets)
        if not asset_ids:
            return {}

        bucket_id = _bucket_id_expression(bucket_seconds)
        rows = (
            self._session.query(AssetSnapshot.asset_id, bucket_id, aggregate(column).label("value"))
            .filter(
                AssetSnapshot.asset_id.in_(asset_ids),
                AssetSnapshot.received_at >= since,
                AssetSnapshot.received_at <= until,
                column.isnot(None),
            )
            .group_by(AssetSnapshot.asset_id, bucket_id)
            .order_by(AssetSnapshot.asset_id.asc(), bucket_id.asc())
            .all()
        )
        series_by_asset: Dict[int, List[Tuple[datetime, float]]] = {
            asset_id: [] for asset_id in asset_ids
        }
        for row in rows:
            series_by_asset[row.asset_id].append(
                (_bucket_start(row.bucket_id, bucket_seconds), float(row.value))
            )
        return series_by_asset

    def get_bucketed_metric_across_assets(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, asset_ids: List[int], column: InstrumentedAttribute, bucket_seconds: int,
        since: datetime, until: datetime, *, within_bucket: BucketAggregation = "max",
        across_assets: AssetAggregation = "sum", max_buckets: int = 1000,
    ) -> List[Tuple[datetime, float, int]]:
        """Una única serie por cubos que combina varios activos, en una sola consulta.

        Agrega en dos niveles, y el orden importa: primero cada activo dentro
        de su cubo (``within_bucket``) y después esos valores entre activos
        (``across_assets``). Sumar directamente las filas crudas contaría dos
        veces a un activo que mandó dos heartbeats dentro del mismo cubo: la
        "memoria total de la etiqueta" dependería de la cadencia de cada
        agente. Los dos niveles van en la misma sentencia, con una subconsulta.

        Args:
            asset_ids: Activos a combinar; ya filtrados por dueño. Una lista
                vacía devuelve una lista vacía sin consultar.
            column: Columna de ``AssetSnapshot`` de la métrica.
            bucket_seconds: Tamaño del cubo en segundos; positivo.
            since: Inicio de la ventana, sobre ``received_at``, inclusivo.
            until: Fin de la ventana, sobre ``received_at``, inclusivo.
            within_bucket: Cómo se resume el cubo de cada activo: ``"min"``,
                ``"avg"`` o ``"max"``. Por defecto ``"max"``.
            across_assets: Cómo se combinan los activos: ``"sum"``, ``"avg"``
                o ``"max"``. Por defecto ``"sum"``.
            max_buckets: Máximo de cubos de la serie. Por defecto ``1000``.

        Returns:
            List[Tuple[datetime, float, int]]: ``(inicio_del_cubo, valor,
                activos_con_dato)`` en orden cronológico. El tercer elemento
                dice cuántos activos aportaron a ese cubo: una suma sobre dos
                activos no es comparable con una sobre tres, y quien la pinta
                tiene que poder decirlo.

        Raises:
            ValueError: Si alguna agregación no es válida o la ventana
                necesita más de ``max_buckets`` cubos.
        """
        bucket_aggregate = _resolve_aggregate(_BUCKET_AGGREGATE_FUNCTIONS, within_bucket)
        asset_aggregate = _resolve_aggregate(_ASSET_AGGREGATE_FUNCTIONS, across_assets)
        _validate_bucket_count(since, until, bucket_seconds, max_buckets)
        if not asset_ids:
            return []

        bucket_id = _bucket_id_expression(bucket_seconds)
        per_asset = (
            self._session.query(
                AssetSnapshot.asset_id, bucket_id, bucket_aggregate(column).label("value"),
            )
            .filter(
                AssetSnapshot.asset_id.in_(asset_ids),
                AssetSnapshot.received_at >= since,
                AssetSnapshot.received_at <= until,
                column.isnot(None),
            )
            .group_by(AssetSnapshot.asset_id, bucket_id)
            .subquery()
        )
        rows = (
            self._session.query(
                per_asset.c.bucket_id,
                asset_aggregate(per_asset.c.value).label("value"),
                func.count(per_asset.c.asset_id).label("asset_count"),
            )
            .group_by(per_asset.c.bucket_id)
            .order_by(per_asset.c.bucket_id.asc())
            .all()
        )
        return [
            (_bucket_start(row.bucket_id, bucket_seconds), float(row.value), row.asset_count)
            for row in rows
        ]

    def get_latest(self, asset_id: int) -> Optional[AssetSnapshot]:
        """Devuelve el último snapshot recibido de un activo, o ``None`` si nunca reportó.

        Ordena por ``received_at`` como ``get_series``, y por el mismo motivo:
        con ``collected_at``, un agente con el reloj adelantado se declararía
        "el más reciente" indefinidamente.
        """
        return (
            self._session.query(AssetSnapshot)
            .filter(AssetSnapshot.asset_id == asset_id)
            .order_by(AssetSnapshot.received_at.desc())
            .first()
        )

    def delete_older_than(self, cutoff: datetime) -> int:
        """Elimina snapshots anteriores a ``cutoff`` (job de retención).

        Poda por ``received_at``, el mismo eje que ordena la serie: con
        ``collected_at`` las filas de un agente con el reloj adelantado
        sobrevivirían a su ventana de retención.

        Returns:
            Número de filas eliminadas.
        """
        result = self._session.query(AssetSnapshot).filter(
            AssetSnapshot.received_at < cutoff
        ).delete(synchronize_session=False)
        return result


class AnomalyRepository(BaseRepository[Anomaly]):
    """Acceso a datos de Anomaly."""

    _MODEL = Anomaly

    #: Estados que cuentan como "todavía activa" a efectos de detección:
    #: reconocer una anomalía (``acknowledged``) no la da por resuelta, así
    #: que sigue bloqueando una reapertura duplicada y sigue siendo
    #: candidata a auto-resolverse cuando la métrica vuelve a la normalidad.
    #: Solo ``resolved`` es un estado terminal.
    _ACTIVE_STATES = ("open", "acknowledged")

    def get_active(self, asset_id: int, kind: str, metric: Optional[str] = None) -> Optional[Anomaly]:
        """Devuelve la anomalía activa (abierta o reconocida) de un tipo/métrica para un activo.

        ``metric`` distingue instancias del mismo ``kind`` que pueden
        coexistir activas a la vez — p. ej. ``disk_full`` en ``/`` y en
        ``/data`` son dos anomalías independientes del mismo activo. Para
        tipos sin métrica asociada (``host_down``), se pasa ``None``.

        Se usa tanto para la apertura idempotente (no duplicar una anomalía
        ya activa) como para la resolución (localizar cuál cerrar).
        """
        query = self._session.query(Anomaly).filter(
            Anomaly.asset_id == asset_id,
            Anomaly.kind == kind,
            Anomaly.state.in_(self._ACTIVE_STATES),
        )
        query = query.filter(Anomaly.metric.is_(None) if metric is None else Anomaly.metric == metric)
        return query.one_or_none()

    def get_all_active(self, asset_id: int) -> List[Anomaly]:
        """Todas las anomalías activas (abiertas o reconocidas) de un activo.

        Usado por la evaluación de umbrales para saber, de un vistazo, qué
        está ya activo antes de decidir qué abrir o resolver en este
        heartbeat — un ``ack`` no debe hacer que se reabra como si fuera
        nueva.
        """
        return (
            self._session.query(Anomaly)
            .filter(Anomaly.asset_id == asset_id, Anomaly.state.in_(self._ACTIVE_STATES))
            .all()
        )

    def get_by_id_for_user(self, anomaly_id: int, user_id: int) -> Optional[Anomaly]:
        """Obtiene una anomalía por id, verificando que pertenece a un activo del usuario.

        El JOIN con MonitoredAsset es la comprobación de propiedad: devuelve
        None tanto si la anomalía no existe como si pertenece a un activo de
        otro usuario, para no permitir enumerar anomalías ajenas.
        """
        return (
            self._session.query(Anomaly)
            .join(MonitoredAsset, Anomaly.asset_id == MonitoredAsset.id)
            .filter(Anomaly.id == anomaly_id, MonitoredAsset.user_id == user_id)
            .one_or_none()
        )

    def get_for_user(
        self, user_id: int, state: Optional[str] = None,
        severity: Optional[str] = None, asset_id: Optional[int] = None,
    ) -> List[Anomaly]:
        """Lista las anomalías de los activos de un usuario, con filtros opcionales.

        El filtro por dueño se aplica a través del JOIN con MonitoredAsset:
        un usuario nunca ve anomalías de activos ajenos.
        """
        query = (
            self._session.query(Anomaly)
            .join(MonitoredAsset, Anomaly.asset_id == MonitoredAsset.id)
            .filter(MonitoredAsset.user_id == user_id)
        )
        if state is not None:
            query = query.filter(Anomaly.state == state)
        if severity is not None:
            query = query.filter(Anomaly.severity == severity)
        if asset_id is not None:
            query = query.filter(Anomaly.asset_id == asset_id)
        return query.order_by(Anomaly.opened_at.desc()).all()

    def count_active_by_state_and_severity(self, user_id: int) -> Dict[Tuple[str, str], int]:
        """Cuántas anomalías activas tienen los activos del usuario, por estado y severidad.

        Solo las activas (``open`` y ``acknowledged``): una resuelta ya no
        pide atención. El filtro por dueño va, como en ``get_for_user``, por
        el JOIN con ``MonitoredAsset``.

        Args:
            user_id: Dueño de los activos.

        Returns:
            Dict[Tuple[str, str], int]: ``{(estado, severidad): anomalías}``.
                Las combinaciones sin ninguna anomalía no aparecen.
        """
        rows = (
            self._session.query(Anomaly.state, Anomaly.severity, func.count(Anomaly.id))
            .join(MonitoredAsset, Anomaly.asset_id == MonitoredAsset.id)
            .filter(MonitoredAsset.user_id == user_id, Anomaly.state.in_(self._ACTIVE_STATES))
            .group_by(Anomaly.state, Anomaly.severity)
            .all()
        )
        return {(state, severity): count for state, severity, count in rows}


class HygeiaTagRepository(BaseRepository[HygeiaTag]):
    """Acceso a datos de HygeiaTag (etiquetas de sistema y personales)."""

    _MODEL = HygeiaTag

    def get_visible_for_user(self, user_id: int) -> List[HygeiaTag]:
        """Catálogo de sistema más el repositorio personal de un usuario.

        Es el conjunto que el usuario puede ver y asignar; cualquier otra
        etiqueta le es invisible. Ordenado primero por tipo (``system``
        antes que ``user``) y luego por nombre, para que la lista salga ya
        agrupada de la base de datos y el frontend no tenga que reordenarla.
        """
        return (
            self._session.query(HygeiaTag)
            .filter(
                (HygeiaTag.user_id.is_(None)) | (HygeiaTag.user_id == user_id)
            )
            .order_by(HygeiaTag.tag_type.asc(), HygeiaTag.name.asc())
            .all()
        )

    def get_asset_activity_per_tag(
        self, user_id: int,
    ) -> Dict[int, Tuple[int, Optional[datetime]]]:
        """Cuántos activos **del usuario** lleva cada etiqueta, y cuándo dio señal el último.

        El filtro por dueño no es cosmético: una etiqueta de sistema la usa
        todo el mundo, y contar sus asociaciones sin filtrar delataría
        cuántos activos ajenos hay, igual que su última señal delataría cuándo
        estuvo encendido un servidor de otro. Los dos datos salen de la misma
        consulta agrupada por etiqueta.

        Args:
            user_id: Dueño de los activos que se cuentan.

        Returns:
            Dict[int, Tuple[int, Optional[datetime]]]: ``{tag_id: (activos,
                última_señal)}``. La última señal es el ``last_seen_at`` más
                reciente entre esos activos, o ``None`` si ninguno ha latido
                nunca. Las etiquetas sin activos del usuario no aparecen; el
                manager las completa con ``(0, None)``.
        """
        rows = (
            self._session.query(
                AssetTag.c.tag_id,
                func.count(AssetTag.c.asset_id),
                func.max(MonitoredAsset.last_seen_at),
            )
            .join(MonitoredAsset, MonitoredAsset.id == AssetTag.c.asset_id)
            .filter(MonitoredAsset.user_id == user_id)
            .group_by(AssetTag.c.tag_id)
            .all()
        )
        return {tag_id: (asset_count, last_seen_at) for tag_id, asset_count, last_seen_at in rows}

    def get_asset_ids_by_tag(self, user_id: int) -> Dict[int, List[int]]:
        """Qué activos **del usuario** lleva cada etiqueta, en una sola consulta.

        Es lo que permite al ranking de etiquetas agregar todas las etiquetas
        con una única consulta de métricas en vez de una por etiqueta. El
        filtro por dueño tiene el mismo porqué que en
        ``get_asset_activity_per_tag``: una etiqueta de sistema la comparten
        todos los usuarios.

        Args:
            user_id: Dueño de los activos.

        Returns:
            Dict[int, List[int]]: ``{tag_id: [asset_id, …]}``, con los ids en
                orden ascendente. Las etiquetas sin activos del usuario no
                aparecen.
        """
        rows = (
            self._session.query(AssetTag.c.tag_id, AssetTag.c.asset_id)
            .join(MonitoredAsset, MonitoredAsset.id == AssetTag.c.asset_id)
            .filter(MonitoredAsset.user_id == user_id)
            .order_by(AssetTag.c.tag_id.asc(), AssetTag.c.asset_id.asc())
            .all()
        )
        asset_ids_by_tag: Dict[int, List[int]] = {}
        for tag_id, asset_id in rows:
            asset_ids_by_tag.setdefault(tag_id, []).append(asset_id)
        return asset_ids_by_tag

    def get_by_name_for_user(self, user_id: int, name: str) -> Optional[HygeiaTag]:
        """Busca una etiqueta visible para el usuario por nombre, sin distinguir mayúsculas.

        Se compara en minúsculas porque «Producción» y «producción» son la
        misma etiqueta para quien la lee: permitir ambas llenaría el catálogo
        de duplicados que solo se distinguen mirándolos con lupa.
        """
        return (
            self._session.query(HygeiaTag)
            .filter(
                (HygeiaTag.user_id.is_(None)) | (HygeiaTag.user_id == user_id),
                func.lower(HygeiaTag.name) == name.lower(),
            )
            .first()
        )

    def count_user_tags(self, user_id: int) -> int:
        """Cuántas etiquetas personales tiene ya creadas un usuario (tope §MAX_TAGS_PER_USER)."""
        return (
            self._session.query(HygeiaTag)
            .filter(HygeiaTag.user_id == user_id)
            .count()
        )
