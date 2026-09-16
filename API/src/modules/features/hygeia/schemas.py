"""
Schemas Marshmallow del módulo Hygeia. Claves de respuesta en camelCase,
por convención del proyecto.
"""

from datetime import timedelta, timezone

from marshmallow import EXCLUDE, Schema, ValidationError, fields, post_load, validate, validates_schema

import src.modules.system.config_reading as CR
from src.modules.shared.schemas import UTCDateTime


TAG_COLORS = ("slate", "green", "teal", "blue", "violet", "amber", "red", "pink")
"""Paleta cerrada de colores de etiqueta.

Se guarda el **nombre** del color, no un valor CSS: el frontend lo traduce a
la variable que toque, así que cambiar el tema (o el matiz exacto de "amber")
no obliga a reescribir ninguna fila. Cerrada, además, porque una paleta libre
acaba siendo diez tonos de gris indistinguibles en un badge de 11px.
"""


class TagSchema(Schema):
    """Vista de una etiqueta.

    ``assetCount`` y ``lastActivityAt`` solo los rellena el listado del
    catálogo; las etiquetas anidadas dentro de un activo los omiten (allí no
    significarían nada). ``lastActivityAt`` es la última señal del activo más
    reciente del usuario que lleva la etiqueta, y es nulo si la etiqueta no
    está en ninguno o ninguno ha reportado nunca.
    """
    id = fields.Integer()
    name = fields.String()
    color = fields.String()
    tagType = fields.String()
    assetCount = fields.Integer()
    lastActivityAt = UTCDateTime(allow_none=True)


class TagCreateRequestSchema(Schema):
    """Alta de una etiqueta personal."""
    name = fields.String(required=True, validate=validate.Length(min=1, max=48))
    color = fields.String(load_default="slate", validate=validate.OneOf(TAG_COLORS))


class TagListResponseSchema(Schema):
    """Catálogo visible para el usuario: las de sistema más las suyas."""
    tags = fields.List(fields.Nested(TagSchema))


class AssetTagsRequestSchema(Schema):
    """Conjunto completo de etiquetas de un activo.

    Es un reemplazo, no un añadido: lo que llega es la lista definitiva, y
    las que no aparezcan se quitan. Una sola operación cubre poner, quitar y
    reordenar sin que el cliente tenga que calcular diferencias.
    """
    tagIds = fields.List(fields.Integer(), required=True)


class InventoryReportRequestSchema(Schema):
    """Petición del informe PDF del inventario de activos.

    ``scope`` distingue "mis activos" de "los de toda mi organización"; el
    segundo solo lo puede pedir el dueño, y de eso se encarga el manager, no
    este schema. ``includeSoftware`` viene desactivado porque el anexo de
    software puede multiplicar por veinte el tamaño del documento.
    """
    scope = fields.String(
        load_default="user", validate=validate.OneOf(("user", "organization")),
    )
    includeSoftware = fields.Boolean(load_default=False)


class AssetCreateRequestSchema(Schema):
    """Alta de un nuevo activo a monitorizar."""
    hostname = fields.String(required=True, validate=validate.Length(min=1, max=255))
    os = fields.String(load_default=None, validate=validate.Length(max=64))
    labels = fields.Dict(load_default=dict)
    # Por defecto se espera un host siempre encendido: es el comportamiento
    # que tenía todo activo antes de que existiera esta propiedad.
    isPersistent = fields.Boolean(load_default=True)


class AssetUpdateRequestSchema(Schema):
    """Modificación de un activo. Solo la expectativa de encendido es editable."""
    isPersistent = fields.Boolean(required=True)


class AssetSchema(Schema):
    """Vista de un activo monitorizado (nunca incluye la clave de agente)."""
    id = fields.Integer()
    hostname = fields.String()
    os = fields.String(allow_none=True)
    kernel = fields.String(allow_none=True)
    # Identidad del host, no una métrica: null significa "el agente
    # nunca lo ha reportado" (agente anterior a esta necesidad, o su
    # `gopsutil` no supo detectarlo), no "no es una máquina virtual".
    virtualizationSystem = fields.String(allow_none=True)
    virtualizationRole = fields.String(allow_none=True)
    labels = fields.Dict()
    tags = fields.List(fields.Nested(TagSchema))
    status = fields.String()
    isPersistent = fields.Boolean()
    # Hallazgos del último análisis Lybra del activo, o null si nunca se
    # analizó: lo que la rejilla de agentes de Themis pinta en cada tarjeta.
    totalFindings = fields.Integer(allow_none=True, load_default=None)
    lastSeenAt = UTCDateTime(allow_none=True)
    uptimeSec = fields.Integer(allow_none=True)
    agentVersion = fields.String(allow_none=True)
    # Aviso, no validación: null significa "no se puede saber" (nunca ha
    # reportado versión, o su versión / el suelo configurado no encajan en
    # el formato X.Y.Z...), y no se pinta como si fuera un "no" (services/agent_freshness.py).
    agentOutdated = fields.Boolean(allow_none=True, load_default=None)
    createdAt = UTCDateTime()


class AssetCreatedResponseSchema(Schema):
    """Respuesta del alta: el activo más la clave de agente en claro, una sola vez."""
    asset = fields.Nested(AssetSchema)
    agentKey = fields.String()


class AssetListResponseSchema(Schema):
    """Listado de activos monitorizados del usuario."""
    assets = fields.List(fields.Nested(AssetSchema))


class RotateKeyResponseSchema(Schema):
    """Respuesta de la rotación de clave: la nueva clave en claro, una sola vez."""
    agentKey = fields.String()


# =============================================================================
# INGESTA — el schema valida y descarta lo desconocido: defensa en la
# frontera de confianza, no se relaja aunque el agente sea "de confianza".
# =============================================================================

class _IngestSchema(Schema):
    """Base común de los schemas de ingesta: descarta claves desconocidas."""
    class Meta:
        unknown = EXCLUDE


class HostInfoSchema(_IngestSchema):
    """Identificación del host que envía el heartbeat."""
    hostname = fields.String(required=True, validate=validate.Length(min=1, max=255))
    os = fields.String(load_default=None, validate=validate.Length(max=64))
    kernel = fields.String(load_default=None, validate=validate.Length(max=128))
    uptimeSec = fields.Integer(load_default=None, validate=validate.Range(min=0))
    # Texto libre en vez de un OneOf: gopsutil puede devolver valores
    # nuevos que el servidor todavía no conoce, y un agente con una versión
    # de gopsutil distinta no debe ver su heartbeat rechazado por eso. Solo
    # el literal "guest" dispara el mensaje de máquina virtual; cualquier
    # otro valor (incluido uno que no se reconozca) se trata como "host o
    # desconocido" — la misma doctrina de "ante la duda, no se sabe" que ya
    # sigue el comparador de versiones de agente.
    virtualizationSystem = fields.String(load_default=None, validate=validate.Length(max=32))
    virtualizationRole = fields.String(load_default=None, validate=validate.Length(max=32))


class CpuMetricsSchema(_IngestSchema):
    """Métricas de CPU de un heartbeat."""
    usagePct = fields.Float(required=True, validate=validate.Range(min=0, max=100))
    loadAvg = fields.List(fields.Float(), load_default=list, validate=validate.Length(max=8))
    ctxSwitches = fields.Integer(load_default=None)
    perCorePct = fields.List(fields.Float(), load_default=list, validate=validate.Length(max=1024))


class MemoryMetricsSchema(_IngestSchema):
    """Métricas de memoria de un heartbeat."""
    totalBytes = fields.Integer(load_default=None)
    usedBytes = fields.Integer(load_default=None)
    usagePct = fields.Float(required=True, validate=validate.Range(min=0, max=100))
    swapUsedPct = fields.Float(load_default=None, validate=validate.Range(min=0, max=100))


class DiskMountSchema(_IngestSchema):
    """Uso de un punto de montaje del host."""
    mount = fields.String(required=True, validate=validate.Length(min=1, max=256))
    usagePct = fields.Float(required=True, validate=validate.Range(min=0, max=100))
    freeBytes = fields.Integer(load_default=None)


class NetworkInterfaceSchema(_IngestSchema):
    """Tráfico de una interfaz de red del host."""
    iface = fields.String(required=True, validate=validate.Length(min=1, max=64))
    rxBytesPerSec = fields.Integer(load_default=None)
    txBytesPerSec = fields.Integer(load_default=None)
    errIn = fields.Integer(load_default=None)
    errOut = fields.Integer(load_default=None)


class ProcessInfoSchema(_IngestSchema):
    """
    Un proceso destacado por consumo de CPU o memoria.

    Se reutiliza tanto para ``topCpu`` como para ``topMem``: cada entrada
    solo rellena el campo (``cpuPct`` o ``memPct``) relevante a la lista en
    la que aparece; el otro queda a ``None``.
    """
    pid = fields.Integer(required=True)
    name = fields.String(required=True, validate=validate.Length(min=1, max=256))
    cpuPct = fields.Float(load_default=None, validate=validate.Range(min=0, max=100))
    memPct = fields.Float(load_default=None, validate=validate.Range(min=0, max=100))


class ProcessesMetricsSchema(_IngestSchema):
    """Resumen de procesos del host en el momento del heartbeat."""
    total = fields.Integer(load_default=None)
    zombie = fields.Integer(load_default=None)
    topCpu = fields.List(fields.Nested(ProcessInfoSchema), load_default=list)
    topMem = fields.List(fields.Nested(ProcessInfoSchema), load_default=list)


class PowerMetricsSchema(_IngestSchema):
    """Consumo eléctrico del host, tal como lo reporta el agente.

    Los tres campos son ``required`` dentro del bloque, mientras que el
    bloque entero es opcional en ``MetricsSchema``: no saber la potencia es
    legítimo y se expresa omitiendo ``power``; mandar unos vatios sin decir
    de dónde salieron no lo es.
    """
    watts = fields.Float(required=True, validate=validate.Range(min=0))
    estimated = fields.Boolean(required=True)
    source = fields.String(required=True, validate=validate.Length(min=1, max=64))


class MetricsSchema(_IngestSchema):
    """Payload completo de métricas de un heartbeat."""
    cpu = fields.Nested(CpuMetricsSchema, required=True)
    memory = fields.Nested(MemoryMetricsSchema, required=True)
    disk = fields.List(fields.Nested(DiskMountSchema), load_default=list)
    network = fields.List(fields.Nested(NetworkInterfaceSchema), load_default=list)
    processes = fields.Nested(ProcessesMetricsSchema, load_default=dict)
    # Opcional: un agente sin ninguna fuente de potencia compatible (o más
    # viejo que el contrato) simplemente no lo manda, y eso no rompe nada.
    power = fields.Nested(PowerMetricsSchema, load_default=None, allow_none=True)

    @validates_schema
    def validate_array_limits(self, data, **kwargs):
        """
        Acota disk/network/topCpu/topMem contra los límites configurables de
        ``features.hygeia.limits``.

        Se leen con ``CR`` en cada validación (no se hornean al importar el
        módulo) para que un cambio vía ``PUT /system`` surta efecto sin
        reiniciar la API, igual que el resto de la configuración.
        """
        max_disk = CR.hygeia_limits().max_disk_mounts
        if len(data.get("disk", [])) > max_disk:
            raise ValidationError(
                f"disk excede el máximo de {max_disk} puntos de montaje", field_name="disk",
            )

        max_net = CR.hygeia_limits().max_net_interfaces
        if len(data.get("network", [])) > max_net:
            raise ValidationError(
                f"network excede el máximo de {max_net} interfaces", field_name="network",
            )

        max_procs = CR.hygeia_limits().max_processes
        processes = data.get("processes") or {}
        if len(processes.get("topCpu", [])) > max_procs:
            raise ValidationError(
                f"topCpu excede el máximo de {max_procs} procesos", field_name="processes",
            )
        if len(processes.get("topMem", [])) > max_procs:
            raise ValidationError(
                f"topMem excede el máximo de {max_procs} procesos", field_name="processes",
            )


class SoftwareSchema(_IngestSchema):
    """Una aplicación instalada, tal como la reporta el escaneo de inventario del agente."""
    name = fields.String(required=True, validate=validate.Length(min=1, max=512))
    type = fields.String(load_default=None, validate=validate.Length(max=32))
    vendor = fields.String(load_default=None, validate=validate.Length(max=256))
    version = fields.String(load_default=None, validate=validate.Length(max=128))
    guid = fields.String(load_default=None, validate=validate.Length(max=128))
    # String, no DateTime: viaja tal cual dentro del JSONB `inventory` (nunca
    # se computa contra ella, a diferencia de `collectedAt`), y un `datetime`
    # ahí dentro no sería serializable a JSON al guardar la fila.
    installedAt = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=32))
    installPath = fields.String(load_default=None, validate=validate.Length(max=1024))
    architecture = fields.String(load_default=None, validate=validate.Length(max=16))
    sizeBytes = fields.Integer(load_default=None, validate=validate.Range(min=0))
    status = fields.String(load_default=None, validate=validate.Length(max=32))
    source = fields.String(load_default=None, validate=validate.Length(max=32))


class InventorySchema(_IngestSchema):
    """Inventario de software de un escaneo (§ contrato de ingesta v1.0).

    Sin "delta": cada escaneo trae el estado completo de software instalado,
    nunca un diff — el backend reemplaza por completo el inventario anterior.
    """
    software = fields.List(fields.Nested(SoftwareSchema), required=True)

    @validates_schema
    def validate_max_items(self, data, **kwargs):
        """Acota ``software`` contra ``features.hygeia.limits.maxInventoryItems``."""
        max_items = CR.hygeia_limits().max_inventory_items
        if len(data.get("software", [])) > max_items:
            raise ValidationError(
                f"software excede el máximo de {max_items} elementos", field_name="software",
            )


class IngestRequestSchema(_IngestSchema):
    """Heartbeat completo enviado por un agente Hygeia."""
    agentVersion = fields.String(required=True, validate=validate.Length(min=1, max=32))
    collectedAt = fields.DateTime(required=True, format="iso")
    host = fields.Nested(HostInfoSchema, required=True)
    metrics = fields.Nested(MetricsSchema, required=True)
    localAlerts = fields.List(fields.Raw(), load_default=list)
    # Opcional (omitempty en el agente): solo presente tras un escaneo de
    # software reciente, no en cada heartbeat (§ contrato de ingesta v1.0).
    inventory = fields.Nested(InventorySchema, load_default=None, allow_none=True)

    @post_load
    def normalize_collected_at(self, data, **kwargs):
        """Normaliza ``collectedAt`` a naive-UTC, como el resto de datetimes del esquema.

        Si el agente manda un ISO-8601 con sufijo de zona (el contrato pide
        ``Z``), se convierte a UTC y se descarta el tzinfo. Si llega naive
        (sin zona), se asume ya en UTC — nunca se aplica la zona local del
        servidor, que sería silenciosamente incorrecto.
        """
        collected_at = data["collectedAt"]
        if collected_at.tzinfo is not None:
            collected_at = collected_at.astimezone(timezone.utc).replace(tzinfo=None)
        data["collectedAt"] = collected_at
        return data


class IngestResponseSchema(Schema):
    """Respuesta a un heartbeat: permite al agente auto-ajustarse sin redeploy."""
    ok = fields.Boolean()
    nextIntervalSec = fields.Integer()
    serverTime = UTCDateTime()


# =============================================================================
# ANOMALÍAS — alertas abiertas por la evaluación de umbrales
# =============================================================================

class AnomalySchema(Schema):
    """Vista de una anomalía detectada, con su ciclo de vida."""
    id = fields.Integer()
    assetId = fields.Integer()
    kind = fields.String()
    severity = fields.String()
    metric = fields.String(allow_none=True)
    value = fields.Float(allow_none=True)
    threshold = fields.Float(allow_none=True)
    details = fields.Dict()
    state = fields.String()
    openedAt = UTCDateTime()
    resolvedAt = UTCDateTime(allow_none=True)


class AnomalyQuerySchema(Schema):
    """Filtros opcionales para listar anomalías."""
    state = fields.String(
        load_default=None, validate=validate.OneOf(["open", "acknowledged", "resolved"]),
    )
    severity = fields.String(
        load_default=None, validate=validate.OneOf(["info", "warning", "critical"]),
    )
    assetId = fields.Integer(load_default=None)


class AnomalyListResponseSchema(Schema):
    """Listado de anomalías de los activos del usuario."""
    anomalies = fields.List(fields.Nested(AnomalySchema))


# =============================================================================
# SERIE TEMPORAL DE MÉTRICAS — para el gráfico de la SPA
# =============================================================================

class AssetMetricsQuerySchema(Schema):
    """Filtros opcionales de rango temporal (``?from=&to=``).

    El rango se aplica sobre ``receivedAt`` (reloj del servidor), no sobre
    ``collectedAt`` (reloj del agente): es el mismo eje por el que se ordena
    y se poda la serie, así que ventana y orden no pueden discrepar por una
    deriva de reloj del agente.
    """
    since = fields.DateTime(data_key="from", load_default=None, format="iso")
    until = fields.DateTime(data_key="to", load_default=None, format="iso")
    # Tamaño del cubo de agregación en segundos. Sin él la serie viaja cruda
    # (un punto por heartbeat); con él, un punto por cubo con el máximo de
    # cada métrica, para que ventanas largas (24 h/7 d) no se recorten contra
    # el tope de puntos y los spikes sigan siendo visibles.
    bucket = fields.Integer(load_default=None, validate=validate.Range(min=1))
    # Cómo se resume cada cubo: ``max`` (por defecto, el comportamiento de
    # siempre), ``min``, ``avg`` o ``p95``. Sin ``bucket`` no tiene efecto: la
    # serie cruda no agrega nada.
    agg = fields.String(load_default="max", validate=validate.OneOf(["min", "avg", "p95", "max"]))

    @post_load
    def normalize_range(self, data, **kwargs):
        """Normaliza ``since``/``until`` a naive-UTC, igual que ``collectedAt`` en la ingesta."""
        for key in ("since", "until"):
            value = data.get(key)
            if value is not None and value.tzinfo is not None:
                data[key] = value.astimezone(timezone.utc).replace(tzinfo=None)
        return data


class AssetSnapshotPointSchema(Schema):
    """
    Un punto de la serie temporal: solo lo desnormalizado, sin el JSONB completo.

    Todo lo que no sea el instante es nullable: ``NULL`` significa "el agente
    no reportó esto" (Windows no manda ``load1``, un host sin interfaces
    visibles no manda red), y las filas anteriores a la instrumentación de
    cada columna también llegan vacías. El consumidor debe tratar cada campo
    como opcional y omitir la traza en lugar de dibujar un cero.
    """
    collectedAt = UTCDateTime()
    receivedAt = UTCDateTime()
    cpuPct = fields.Float(allow_none=True)
    memPct = fields.Float(allow_none=True)
    swapPct = fields.Float(allow_none=True)
    load1 = fields.Float(allow_none=True)
    diskMaxPct = fields.Float(allow_none=True)
    diskMaxMount = fields.String(allow_none=True)
    netRxBps = fields.Integer(allow_none=True)
    netTxBps = fields.Integer(allow_none=True)
    powerWatts = fields.Float(allow_none=True)
    # En la serie por cubos estos dos siempre llegan a null: no son
    # magnitudes que se puedan promediar ni maximizar dentro de un cubo. En
    # la serie cruda sí viajan, uno por snapshot.
    powerEstimated = fields.Boolean(allow_none=True)
    powerSource = fields.String(allow_none=True)


class AssetMetricsResponseSchema(Schema):
    """Serie temporal de métricas de un activo, para el gráfico de la SPA.

    ``bucket`` ecoa el cubo de agregación usado: ``null`` = serie cruda (un
    punto por heartbeat), un entero = un punto por cubo. ``agg`` ecoa cómo se
    resumió cada cubo (``min``/``avg``/``p95``/``max``), y es ``null`` en la
    serie cruda. Así el consumidor rotula la ventana con honestidad sin adivinar.
    """
    snapshots = fields.List(fields.Nested(AssetSnapshotPointSchema))
    truncated = fields.Boolean(
        metadata={"description": "La serie se recortó al máximo de puntos: "
                                 "hay más histórico del que se devuelve."},
    )
    bucket = fields.Integer(allow_none=True, load_default=None)
    agg = fields.String(allow_none=True, load_default=None)


class AssetLatestResponseSchema(Schema):
    """
    Últimas métricas completas de un activo — lo que la serie temporal no cabe.

    Aquí viaja el payload íntegro del último heartbeat: uso por punto de
    montaje, tráfico por interfaz, procesos top y uso por núcleo. Reutiliza
    ``MetricsSchema``, el mismo schema con el que se validó al entrar, en
    dirección de volcado: un solo contrato, documentado una vez.

    Los tres campos son nullable porque un activo recién dado de alta existe
    pero aún no ha reportado — un estado legítimo, no un error.
    """
    collectedAt = UTCDateTime(allow_none=True)
    receivedAt = UTCDateTime(allow_none=True)
    metrics = fields.Nested(MetricsSchema, allow_none=True)


# =============================================================================
# ENERGÍA Y COSTE — resumen de consumo de un activo
# =============================================================================

class CurrentPowerSchema(Schema):
    """Última lectura de potencia conocida, tal como la deja el propio heartbeat.

    ``watts`` nulo es "este activo no expone ninguna fuente de potencia
    compatible", no un error; los otros dos campos solo tienen sentido junto
    a una lectura real, así que viajan nulos en el mismo caso.
    """
    watts = fields.Float(allow_none=True)
    estimated = fields.Boolean(allow_none=True)
    source = fields.String(allow_none=True)


class PowerPeriodSchema(Schema):
    """
    Energía y coste de un periodo, con su procedencia.

    ``classification`` distingue tres casos: ``"observed"`` (el periodo cabe
    en la retención y la cobertura de datos es alta), ``"observed_partial"``
    (cabe pero con cobertura baja — se da la cifra igual, marcada) y
    ``"projected"`` (el periodo excede la retención configurada y la cifra
    se extrapola desde la media observada). Un activo sin ni un intervalo
    válido en el periodo devuelve ``averageWatts``/``kwh``/``cost`` a
    ``None`` — no hay cifra que dar, y no es cero.
    """
    averageWatts = fields.Float(allow_none=True)
    kwh = fields.Float(allow_none=True)
    cost = fields.Float(allow_none=True)
    currency = fields.String()
    classification = fields.String()
    coverageFraction = fields.Float(allow_none=True)
    periodFrom = UTCDateTime()
    periodTo = UTCDateTime()


class PowerSummaryResponseSchema(Schema):
    """
    Resumen de consumo de un activo para la ficha: la lectura actual
    más energía y coste de 24 h, 7 d y 30 d, y una proyección mensual.

    ``day``/``week``/``month`` cubren como mucho la ventana de retención
    configurada (30 días por defecto): más allá de ahí no hay histórico que
    observar. ``monthProjected`` sí extrapola siempre, y por eso se marca
    ``"projected"`` sin excepción: contra treinta días de retención, un mes
    natural nunca es dato observado completo.
    """
    current = fields.Nested(CurrentPowerSchema)
    day = fields.Nested(PowerPeriodSchema)
    week = fields.Nested(PowerPeriodSchema)
    month = fields.Nested(PowerPeriodSchema)
    monthProjected = fields.Nested(PowerPeriodSchema)


# =============================================================================
# ESTADÍSTICAS — agregados de las métricas de un activo sobre un periodo
# =============================================================================

#: Unidades que admite ``period``: horas o días, el mismo vocabulario que usa
#: la SPA para rotular las ventanas (``24h``, ``7d``, ``30d``).
_PERIOD_UNITS = {"h": "hours", "d": "days"}


def _build_period_field() -> fields.String:
    """Campo ``period`` de las queries de estadísticas: ``<n>h`` o ``<n>d``, por defecto ``24h``.

    Returns:
        fields.String: Un campo nuevo en cada llamada; marshmallow no admite
            compartir la misma instancia entre schemas.
    """
    return fields.String(
        load_default="24h",
        validate=validate.Regexp(
            r"^[1-9][0-9]{0,4}[hd]$",
            error="El periodo debe tener la forma <n>h o <n>d (por ejemplo 24h o 7d).",
        ),
    )


def _build_format_field() -> fields.String:
    """Campo ``format`` de las queries de estadísticas: ``json`` (por defecto) o ``csv``.

    El JSON es el formato de toda la API, así que pedirlo no requiere nada;
    ``csv`` devuelve **los mismos valores** en un fichero descargable, volcados
    por ``services/export.py`` a partir de la respuesta ya serializada por este
    mismo schema. No hay un segundo cálculo que pueda desviarse del primero.

    Returns:
        fields.String: Un campo nuevo en cada llamada; marshmallow no admite
            compartir la misma instancia entre schemas.
    """
    return fields.String(load_default="json", validate=validate.OneOf(["json", "csv"]))


def _parse_period(period: str) -> timedelta:
    """Convierte un ``period`` ya validado (``24h``, ``7d``…) en su duración.

    Args:
        period: Número positivo seguido de ``h`` (horas) o ``d`` (días).

    Returns:
        timedelta: La duración pedida.
    """
    return timedelta(**{_PERIOD_UNITS[period[-1]]: int(period[:-1])})


class AssetStatsSummaryQuerySchema(Schema):
    """Query de ``GET /hygeia/assets/<id>/stats/summary``.

    ``period`` acepta cualquier ``<n>h`` o ``<n>d``, no solo ``24h``/``7d``/
    ``30d``: un periodo mayor que lo que se puede cubrir no es un error, se
    recorta y la respuesta lo dice (``isPeriodClipped``). ``metrics`` es una
    lista separada por comas de nombres públicos (``cpuPct,memPct``); sin
    ella se resumen todas las métricas. Los nombres no se validan aquí sino
    contra el registro de métricas, que responde con el catálogo válido.

    Tras cargar, la query queda como ``metric_names`` (lista, vacía si no se
    pidió ninguna) y ``requested_duration`` (``timedelta``).
    """
    metrics = fields.String(load_default=None)
    period = _build_period_field()
    format = _build_format_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``metrics`` en lista de nombres y ``period`` en ``timedelta``."""
        raw_metrics = data.pop("metrics")
        data["metric_names"] = (
            [name.strip() for name in raw_metrics.split(",") if name.strip()]
            if raw_metrics else []
        )
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class MetricSummarySchema(Schema):
    """Resumen de una métrica sobre el periodo cubierto.

    Se vuelca directamente desde un ``StatSummary`` (``services/stats.py``),
    cuyos atributos tienen nombres completos; ``data_key`` los publica con las
    claves cortas de la API. Todos los valores son nulos a la vez cuando la
    métrica no tiene ninguna muestra en el periodo (``sampleCount`` es ``0``):
    no se sabe su máximo, y ``0`` sería una cifra inventada.

    ``timestampOfMax``/``timestampOfMin`` son el instante exacto
    (``receivedAt``) del heartbeat que marcó el extremo, no el de un cubo:
    es lo que permite relacionar un pico con lo que pasaba en ese momento
    (una anomalía, un despliegue). Si el extremo se repite, es el de la
    primera vez que se alcanzó.
    """
    minimum = fields.Float(data_key="min", allow_none=True)
    maximum = fields.Float(data_key="max", allow_none=True)
    average = fields.Float(data_key="avg", allow_none=True)
    percentile_95 = fields.Float(data_key="p95", allow_none=True)
    current = fields.Float(allow_none=True)
    sample_count = fields.Integer(data_key="sampleCount")
    timestamp_of_maximum = UTCDateTime(data_key="timestampOfMax", allow_none=True)
    timestamp_of_minimum = UTCDateTime(data_key="timestampOfMin", allow_none=True)


class PeakPairingSchema(Schema):
    """Cuánto distó el pico de una métrica del de la métrica de referencia.

    ``separationSec`` es una distancia, siempre positiva: no dice cuál de los
    dos picos fue antes, solo cuánto se separaron. Es nulo, con
    ``isCoincident`` a ``false``, cuando la métrica no tuvo ninguna muestra en
    el periodo y por tanto no tiene pico que comparar.
    """
    metric = fields.String()
    peak_instant = UTCDateTime(data_key="peakAt", allow_none=True)
    separation_seconds = fields.Float(data_key="separationSec", allow_none=True)
    is_coincident = fields.Boolean(data_key="isCoincident")


class PeakCoincidenceSchema(Schema):
    """Si los picos de varias métricas del activo cayeron a la vez.

    **No es una correlación estadística**, y no debe leerse como tal: no se
    comparan las series, solo los instantes de sus máximos. Es una señal para
    llamar la atención sobre dos cifras que quizá convenga mirar juntas — por
    ejemplo, un proceso que satura la CPU procesando el tráfico que le entra
    por la red dejaría los dos picos pegados en el tiempo.

    Por eso la respuesta publica siempre los dos instantes y su separación en
    segundos, y no solo el booleano: cuanto más largo es el periodo, más
    ocasiones tienen dos picos independientes de rozarse por casualidad, y
    quien lee la señal necesita poder ponderarlo por sí mismo.

    ``reason`` dice por qué no hay señal cuando no la hay:
    ``metrics_not_compared`` si la petición no incluyó las métricas necesarias,
    ``no_peak`` si la de referencia no tuvo ninguna muestra en el periodo. Es
    nulo cuando la comparación se pudo hacer, saliera coincidencia o no.
    """
    reference_metric = fields.String(data_key="referenceMetric")
    reference_instant = UTCDateTime(data_key="referencePeakAt", allow_none=True)
    tolerance_seconds = fields.Integer(data_key="toleranceSec")
    pairings = fields.List(fields.Nested(PeakPairingSchema))
    is_any_coincident = fields.Boolean(data_key="isAnyCoincident")
    reason = fields.String(allow_none=True)


class AssetStatsSummaryResponseSchema(Schema):
    """Resumen estadístico de las métricas de un activo.

    ``metrics`` va indexado por el nombre público de cada métrica pedida.
    ``peakCoincidence`` cruza los instantes de esos máximos entre sí para
    señalar si la CPU y la red hicieron pico a la vez.
    ``periodCoveredFrom``/``periodCoveredTo`` son la ventana que se cubrió de
    verdad, e ``isPeriodClipped`` avisa de que es más corta que la pedida
    (el periodo superaba el límite de estadísticas o la retención).
    """
    metrics = fields.Dict(keys=fields.String(), values=fields.Nested(MetricSummarySchema))
    peakCoincidence = fields.Nested(PeakCoincidenceSchema)
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class DiskStatsQuerySchema(Schema):
    """Query de ``GET /hygeia/assets/<id>/stats/disks``.

    ``mount`` limita la respuesta a un punto de montaje (``/var``); sin él
    salen todos los que el activo reportó en el periodo. Tras cargar,
    ``period`` queda como ``requested_duration``.
    """
    mount = fields.String(load_default=None, validate=validate.Length(min=1, max=256))
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class MountStatsSchema(Schema):
    """Resumen del uso de un punto de montaje sobre el periodo cubierto."""
    mount = fields.String()
    usagePct = fields.Nested(MetricSummarySchema)


class DiskStatsResponseSchema(Schema):
    """Estadísticas de disco de un activo, un resumen por punto de montaje.

    ``mounts`` va ordenado por nombre de montaje. La ventana cubierta se
    recorta a ``maxEntityStatsPeriodDays``, y ``isPeriodClipped`` lo avisa.
    """
    mounts = fields.List(fields.Nested(MountStatsSchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class DiskTrendQuerySchema(Schema):
    """Query de ``GET /hygeia/assets/<id>/stats/disk-trend``.

    Sin ``mount`` la tendencia se ajusta sobre ``diskMaxPct``, el montaje más
    lleno de cada latido, y cubre la ventana larga de estadísticas. Con
    ``mount`` se ajusta sobre ese montaje concreto, leyendo el detalle del
    JSONB, y la ventana se recorta a la de las estadísticas por entidad.
    Tras cargar, ``period`` queda como ``requested_duration``.
    """
    mount = fields.String(load_default=None, validate=validate.Length(min=1, max=256))
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class DiskTrendResponseSchema(Schema):
    """Tendencia del uso de disco de un activo y estimación de cuándo se llenará.

    ``slopePctPerDay`` es cuántos puntos porcentuales gana (o pierde, si es
    negativa) el disco cada día según la recta ajustada, y ``rSquared`` dice
    cuánto se fía uno de esa recta: cerca de ``1`` la serie es casi una línea,
    cerca de ``0`` la recta atraviesa una nube de puntos. Los dos son nulos
    cuando no hubo recta que ajustar.

    ``daysUntilFull`` solo trae una cifra cuando la tendencia la sostiene. En
    cuanto la pendiente es plana o negativa, el ajuste es malo o no hay
    muestras suficientes, viene a ``null`` y ``reason`` dice cuál de las tres
    cosas pasó (``insufficient_samples``, ``insufficient_trend``). Un disco
    que ya está al 100 % devuelve ``0.0`` con ``reason`` ``already_full``.
    Cuando la estimación es normal, ``reason`` es nulo.

    Una estimación equivocada es peor que ninguna: "se llena en cuatro días"
    invita a actuar, y si sale de una pendiente trazada sobre ruido, invita a
    actuar sobre nada.
    """
    mount = fields.String(allow_none=True)
    currentPct = fields.Float(allow_none=True)
    slopePctPerDay = fields.Float(allow_none=True)
    rSquared = fields.Float(allow_none=True)
    sampleCount = fields.Integer()
    daysUntilFull = fields.Float(allow_none=True)
    reason = fields.String(allow_none=True)
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class NetworkStatsQuerySchema(Schema):
    """Query de ``GET /hygeia/assets/<id>/stats/network``.

    ``interface`` limita la respuesta a una interfaz (``eth0``); sin ella
    salen todas las que el activo reportó en el periodo, salvo las loopback.
    Tras cargar, ``period`` queda como ``requested_duration``.
    """
    interface = fields.String(load_default=None, validate=validate.Length(min=1, max=64))
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class InterfaceStatsSchema(Schema):
    """Resumen del tráfico de una interfaz sobre el periodo cubierto, en bytes/s."""
    interface = fields.String()
    rxBytesPerSec = fields.Nested(MetricSummarySchema)
    txBytesPerSec = fields.Nested(MetricSummarySchema)


class NetworkStatsResponseSchema(Schema):
    """Estadísticas de red de un activo, un resumen por interfaz.

    ``interfaces`` va ordenado por nombre de interfaz. La ventana cubierta
    se recorta a ``maxEntityStatsPeriodDays``, y ``isPeriodClipped`` lo avisa.
    """
    interfaces = fields.List(fields.Nested(InterfaceStatsSchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class CpuCoreStatsQuerySchema(Schema):
    """Query de ``GET /hygeia/assets/<id>/stats/cpu-cores``.

    Tras cargar, ``period`` queda como ``requested_duration``.
    """
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class CpuCoreStatsResponseSchema(Schema):
    """Desequilibrio de carga entre los núcleos de CPU de un activo.

    ``coreSpreadPct`` resume, sobre el periodo, la distancia en puntos
    porcentuales entre el núcleo más cargado y el menos cargado de cada
    heartbeat; los heartbeats con menos de dos núcleos no cuentan.
    ``latestPerCorePct`` es el uso de cada núcleo en ``latestAt``, el último
    heartbeat del periodo que lo trae. La ventana se recorta a
    ``maxEntityStatsPeriodDays``, y ``isPeriodClipped`` lo avisa.
    """
    coreSpreadPct = fields.Nested(MetricSummarySchema)
    latestPerCorePct = fields.List(fields.Float())
    latestAt = UTCDateTime(allow_none=True)
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class TagStatsQuerySchema(AssetStatsSummaryQuerySchema):
    """Query de ``GET /hygeia/stats/by-tag/<tagId>``: la del resumen de un activo más ``agg``.

    ``agg`` dice cómo se combinan entre activos las medias de cada uno:
    ``avg`` (por defecto, válido para cualquier métrica), ``max`` o ``sum``.
    ``sum`` solo tiene sentido en métricas aditivas (tráfico, potencia); con
    un porcentaje, el manager responde un 400 con las que sí se pueden sumar.
    """
    agg = fields.String(load_default="avg", validate=validate.OneOf(["sum", "avg", "max"]))


class AssetMetricAggregateSchema(Schema):
    """Lo que aporta un activo al agregado de una métrica de su etiqueta.

    ``average`` y ``maximum`` son nulos, y ``sampleCount`` es ``0``, si el
    activo no reportó la métrica en el periodo: cuenta en la etiqueta pero
    no en la cifra combinada.
    """
    assetId = fields.Integer()
    hostname = fields.String()
    average = fields.Float(allow_none=True)
    maximum = fields.Float(allow_none=True)
    sampleCount = fields.Integer()


class TagMetricStatsSchema(Schema):
    """Una métrica agregada sobre los activos de una etiqueta.

    ``unit`` (``percent``, ``loadAverage``, ``bytesPerSecond`` o ``watts``)
    dice en qué se expresa ``value``: la memoria, por ejemplo, solo se guarda
    como porcentaje, y la respuesta lo declara en vez de fingir bytes.
    ``value`` es nulo si ningún activo tuvo datos en el periodo.
    """
    unit = fields.String()
    value = fields.Float(allow_none=True)
    assetsWithData = fields.Integer()
    assets = fields.List(fields.Nested(AssetMetricAggregateSchema))


class TagStatsResponseSchema(Schema):
    """Estadísticas de los activos del usuario que llevan una etiqueta.

    ``assetCount`` cuenta los activos del usuario con la etiqueta, tengan o no
    datos; ``agg`` ecoa cómo se combinaron. La ventana cubierta viaja igual
    que en el resumen de un activo.
    """
    tag = fields.Nested(TagSchema)
    assetCount = fields.Integer()
    agg = fields.String()
    metrics = fields.Dict(keys=fields.String(), values=fields.Nested(TagMetricStatsSchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class TagRankingQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/by-tag`` (sin ``tagId``): el ranking de todas las etiquetas.

    Una sola métrica (``metric``, obligatoria): un ranking ordena por un
    criterio. ``agg`` y ``period`` significan lo mismo que en las
    estadísticas de una etiqueta. Tras cargar, ``period`` queda como
    ``requested_duration``.
    """
    metric = fields.String(required=True)
    agg = fields.String(load_default="avg", validate=validate.OneOf(["sum", "avg", "max"]))
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class TagRankingEntrySchema(Schema):
    """Una etiqueta en el ranking: su cifra combinada y cuántos activos la sostienen.

    ``value`` es nulo si ninguno de sus activos tuvo datos en el periodo; esas
    etiquetas van al final del ranking, no en la posición de un cero.
    """
    tag = fields.Nested(TagSchema)
    assetCount = fields.Integer()
    assetsWithData = fields.Integer()
    value = fields.Float(allow_none=True)


class TagRankingResponseSchema(Schema):
    """Ranking de las etiquetas visibles para el usuario por una métrica.

    ``tags`` va de mayor a menor ``value``, con las etiquetas sin datos al
    final. ``unit`` dice en qué se expresan los valores.
    """
    metric = fields.String()
    unit = fields.String()
    agg = fields.String()
    tags = fields.List(fields.Nested(TagRankingEntrySchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class AssetRankingQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/ranking``: los activos extremos del usuario por una métrica.

    ``agg`` elige qué valor de cada activo se compara: su media (``avg``, por
    defecto) o su máximo (``max``) del periodo. ``order=desc`` (por defecto)
    da los de mayor valor, ``asc`` los de menor. ``limit`` va de 1 a 100.
    Tras cargar, ``period`` queda como ``requested_duration``.
    """
    metric = fields.String(required=True)
    agg = fields.String(load_default="avg", validate=validate.OneOf(["avg", "max"]))
    order = fields.String(load_default="desc", validate=validate.OneOf(["desc", "asc"]))
    limit = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))
    period = _build_period_field()
    format = _build_format_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class AssetRankingEntrySchema(Schema):
    """Un activo en el ranking: su valor para la métrica y cuántas muestras lo sostienen."""
    assetId = fields.Integer()
    hostname = fields.String()
    value = fields.Float()
    sampleCount = fields.Integer()


class AssetRankingResponseSchema(Schema):
    """Los activos extremos del usuario por una métrica.

    ``assets`` está ordenado según ``order`` y recortado a ``limit``. Solo
    entran los activos con datos en el periodo: ``assetCount`` cuenta todos
    los del usuario y ``assetsWithData`` los que se pudieron ordenar.
    """
    metric = fields.String()
    unit = fields.String()
    agg = fields.String()
    order = fields.String()
    assetCount = fields.Integer()
    assetsWithData = fields.Integer()
    assets = fields.List(fields.Nested(AssetRankingEntrySchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class FleetDiskQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/disks/fleet``: cuántos activos devolver, de 1 a 100."""
    limit = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))


class FleetMountEntrySchema(Schema):
    """El montaje más lleno de un activo según su último heartbeat.

    ``receivedAt`` es el instante de ese heartbeat: el de un activo apagado
    puede ser de hace días, y así se ve.
    """
    assetId = fields.Integer()
    hostname = fields.String()
    mount = fields.String(allow_none=True)
    usagePct = fields.Float()
    receivedAt = UTCDateTime()


class FleetDiskResponseSchema(Schema):
    """Los activos del usuario con el montaje más lleno, de mayor a menor uso.

    ``assetCount`` cuenta todos los activos del usuario y ``assetsWithData``
    los que tienen dato de disco en su último heartbeat; ``mounts`` está
    recortado a ``limit``.
    """
    assetCount = fields.Integer()
    assetsWithData = fields.Integer()
    mounts = fields.List(fields.Nested(FleetMountEntrySchema))


class BreachRankingQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/breach-ranking``.

    ``limit`` va de 1 a 100 y recorta el ranking devuelto, no el recuento:
    ``totalBreaches`` y ``mostConflictiveMetric`` siguen mirando el parque
    entero. Tras cargar, ``period`` queda como ``requested_duration``.
    """
    limit = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class BreachRankingEntrySchema(Schema):
    """Un activo en el ranking de incumplimientos de umbral.

    ``breachCount`` son las veces que el activo cruzó alguno de sus umbrales
    dentro del periodo. ``currentBreachStreak`` es otra cosa y por eso viaja
    aparte: cuántos latidos consecutivos lleva en rojo **ahora mismo**, sumados
    sobre todas sus métricas. Un activo puede tener un ``breachCount`` alto con
    la racha a cero (cruzó muchas veces y se recuperó) o al revés.
    """
    assetId = fields.Integer()
    hostname = fields.String()
    breachCount = fields.Integer()
    currentBreachStreak = fields.Integer()


class ConflictiveMetricSchema(Schema):
    """La métrica que más incumplimientos acumuló en el parque durante el periodo.

    ``metric`` es el nombre tal como lo guarda la anomalía que lo disparó
    (``cpu.usagePct``, ``memory.usagePct``, ``disk./var``…), que identifica la
    entidad concreta y no solo la familia de la métrica.
    """
    metric = fields.String()
    breachCount = fields.Integer()


class BreachRankingResponseSchema(Schema):
    """Los activos del usuario ordenados por incumplimientos de umbral.

    Cada incumplimiento es una anomalía abierta por el detector dentro del
    periodo, contando también las que ya se resolvieron: ocurrieron igual, y
    descontarlas haría encoger el recuento del periodo según los activos se
    recuperan.

    A diferencia del ranking por métrica, aquí entran **todos** los activos del
    usuario, incluidos los de cero incumplimientos: cero es un dato conocido
    ("no cruzó ningún umbral"), no una ausencia de dato. ``mostConflictiveMetric``
    es nulo cuando no hubo ninguna apertura con métrica en el periodo.
    """
    assetCount = fields.Integer()
    totalBreaches = fields.Integer()
    assets = fields.List(fields.Nested(BreachRankingEntrySchema))
    mostConflictiveMetric = fields.Nested(ConflictiveMetricSchema, allow_none=True)
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class FleetOverviewQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/overview``: solo el formato de salida.

    El panorama no acepta periodo —es una foto del ahora, no de un tramo— así
    que ``format`` es su único parámetro.
    """
    format = _build_format_field()


class FleetOverviewResponseSchema(Schema):
    """Estado actual del parque del usuario: la pantalla de aterrizaje de las estadísticas.

    ``assetsByStatus`` trae siempre ``pending``/``online``/``stale``/``offline``
    y ``openAnomaliesBySeverity`` siempre ``info``/``warning``/``critical``, a
    cero si no hay ninguno. Las anomalías reconocidas (``acknowledged``)
    siguen activas pero ya tienen quien las mire, así que se cuentan aparte.
    ``averageUptimeSec`` promedia solo los activos en línea y es nulo si no
    hay ninguno; ``lastActivityAt`` es nulo si ningún activo ha reportado.
    """
    assetCount = fields.Integer()
    assetsByStatus = fields.Dict(keys=fields.String(), values=fields.Integer())
    openAnomaliesBySeverity = fields.Dict(keys=fields.String(), values=fields.Integer())
    acknowledgedAnomalyCount = fields.Integer()
    averageUptimeSec = fields.Float(allow_none=True)
    lastActivityAt = UTCDateTime(allow_none=True)


class MetricHistogramQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/histogram``: cómo se reparten los activos en una métrica.

    ``agg`` elige el valor de cada activo que se reparte: su media (``avg``,
    por defecto) o su máximo (``max``) del periodo. ``bins`` es el número de
    franjas, de 1 a 20 (por defecto 4: 0–25, 25–50, 50–75 y 75–100 % en un
    porcentaje). Tras cargar, ``period`` queda como ``requested_duration``.
    """
    metric = fields.String(required=True)
    agg = fields.String(load_default="avg", validate=validate.OneOf(["avg", "max"]))
    bins = fields.Integer(load_default=4, validate=validate.Range(min=1, max=20))
    period = _build_period_field()

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class HistogramBinSchema(Schema):
    """Una franja del histograma, volcada desde un ``HistogramBin`` (``services/stats.py``).

    ``from`` está incluido y ``to`` excluido, salvo en la última franja, que
    incluye su ``to``.
    """
    lower_bound = fields.Float(data_key="from")
    upper_bound = fields.Float(data_key="to")
    value_count = fields.Integer(data_key="assetCount")


class MetricHistogramResponseSchema(Schema):
    """Histograma de los activos del usuario en una métrica.

    En un porcentaje las franjas van siempre de 0 a 100; en las demás
    unidades, del menor al mayor valor observado. ``bins`` va vacío si la
    métrica no es un porcentaje y ningún activo tuvo datos. Los activos sin
    datos cuentan en ``assetCount`` pero no en ninguna franja.
    """
    metric = fields.String()
    unit = fields.String()
    agg = fields.String()
    assetCount = fields.Integer()
    assetsWithData = fields.Integer()
    bins = fields.List(fields.Nested(HistogramBinSchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class PowerStatsQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/power``: el consumo eléctrico de un conjunto de activos.

    ``scope=fleet`` (por defecto) cubre todos los activos del usuario;
    ``scope=tag`` los de la etiqueta ``tagId``, que entonces es obligatorio.
    Con ``scope=fleet`` no se admite ``tagId``: un parámetro que se ignorase
    en silencio haría creer a quien llama que filtró. Tras cargar, ``period``
    queda como ``requested_duration``.
    """
    scope = fields.String(load_default="fleet", validate=validate.OneOf(["fleet", "tag"]))
    tagId = fields.Integer(load_default=None, validate=validate.Range(min=1))
    period = _build_period_field()

    @validates_schema
    def validate_scope(self, data, **kwargs):
        """Exige ``tagId`` con ``scope=tag`` y lo rechaza con ``scope=fleet``."""
        if data.get("scope") == "tag" and data.get("tagId") is None:
            raise ValidationError("tagId es obligatorio con scope=tag.", field_name="tagId")
        if data.get("scope") == "fleet" and data.get("tagId") is not None:
            raise ValidationError("tagId solo se admite con scope=tag.", field_name="tagId")

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class AssetPowerSchema(Schema):
    """Energía de un activo dentro del agregado, con su procedencia.

    ``averageWatts``/``kwh``/``cost`` son nulos si el activo no tuvo ni un
    intervalo de potencia observado en el periodo. ``isEstimated`` avisa de
    que alguna de sus lecturas fue una estimación por modelo, no una medición.
    """
    assetId = fields.Integer()
    hostname = fields.String()
    averageWatts = fields.Float(allow_none=True)
    kwh = fields.Float(allow_none=True)
    cost = fields.Float(allow_none=True)
    classification = fields.String()
    coverageFraction = fields.Float(allow_none=True)
    isEstimated = fields.Boolean()


class PowerStatsResponseSchema(Schema):
    """Energía y coste agregados de todo el parque o de una etiqueta.

    ``kwh`` y ``cost`` suman solo los activos con datos (``assetsWithData``):
    uno sin potencia no aporta un cero. ``classification`` es la procedencia
    menos fiable de entre esos activos (``observed``, ``observed_partial`` o
    ``projected``), porque un total no es más fiable que su peor parte; es
    nula si ningún activo tuvo datos. ``assetsEstimated`` cuenta los activos
    con alguna lectura estimada por modelo. ``tag`` solo viene con
    ``scope=tag``.
    """
    scope = fields.String()
    tag = fields.Nested(TagSchema, allow_none=True)
    assetCount = fields.Integer()
    assetsWithData = fields.Integer()
    assetsEstimated = fields.Integer()
    kwh = fields.Float(allow_none=True)
    cost = fields.Float(allow_none=True)
    currency = fields.String()
    classification = fields.String(allow_none=True)
    assets = fields.List(fields.Nested(AssetPowerSchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class HourlyPatternQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/hourly-pattern``.

    ``scope`` decide sobre qué se agrega: ``fleet`` (por defecto) todo el
    parque del usuario, ``tag`` los activos de ``tagId``, ``asset`` uno solo
    (``assetId``). El id correspondiente es obligatorio con su ámbito, y los
    que no corresponden se rechazan en vez de ignorarse: un parámetro que se
    tragase en silencio haría creer a quien llama que filtró.

    ``agg`` es cómo se resume cada hora: ``avg`` (por defecto) da la carga
    típica de esa hora, ``max`` el peor momento que se vio en ella. Tras
    cargar, ``period`` queda como ``requested_duration``.
    """
    metric = fields.String(required=True)
    scope = fields.String(
        load_default="fleet", validate=validate.OneOf(["fleet", "tag", "asset"]),
    )
    tagId = fields.Integer(load_default=None, validate=validate.Range(min=1))
    assetId = fields.Integer(load_default=None, validate=validate.Range(min=1))
    agg = fields.String(load_default="avg", validate=validate.OneOf(["min", "avg", "max"]))
    period = _build_period_field()

    @validates_schema
    def validate_scope(self, data, **kwargs):
        """Exige el id del ámbito pedido y rechaza los de los demás."""
        required_by_scope = {"tag": "tagId", "asset": "assetId"}
        scope = data.get("scope")
        for candidate_scope, field_name in required_by_scope.items():
            if scope == candidate_scope and data.get(field_name) is None:
                raise ValidationError(
                    f"{field_name} es obligatorio con scope={candidate_scope}.",
                    field_name=field_name,
                )
            if scope != candidate_scope and data.get(field_name) is not None:
                raise ValidationError(
                    f"{field_name} solo se admite con scope={candidate_scope}.",
                    field_name=field_name,
                )

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``period`` en ``timedelta``."""
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class HourlyPatternEntrySchema(Schema):
    """Una hora del día dentro del patrón horario.

    ``hour`` va de 0 a 23 en el reloj del servidor. ``value`` es nulo, con
    ``sampleCount`` a ``0``, en una hora sin ningún heartbeat en todo el
    periodo: es un hueco, no un cero, y pintarlo como cero convertiría un
    parque apagado de noche en un parque ocioso.
    """
    hour = fields.Integer()
    value = fields.Float(allow_none=True)
    sampleCount = fields.Integer()


class HourlyPatternResponseSchema(Schema):
    """Reparto de una métrica por hora del día sobre un activo, una etiqueta o el parque.

    ``hours`` trae siempre las 24 horas en orden, de la 0 a la 23, para que
    quien pinta el heatmap no tenga que rellenar los huecos. ``peakHour`` es
    la hora de mayor valor, y es nula si ninguna tuvo muestras. ``tag`` solo
    viene informado con ``scope=tag``.

    Las horas son las del reloj del **servidor** (``receivedAt``): el del
    agente puede estar mal puesto o en otra zona, y mezclar husos daría un
    patrón que no es el de ninguna máquina.
    """
    metric = fields.String()
    unit = fields.String()
    agg = fields.String()
    scope = fields.String()
    tag = fields.Dict(allow_none=True)
    assetCount = fields.Integer()
    hours = fields.List(fields.Nested(HourlyPatternEntrySchema))
    peakHour = fields.Integer(allow_none=True)
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


class MetricSeriesQuerySchema(Schema):
    """Query de ``GET /hygeia/stats/series``: la serie temporal de una métrica sobre varios activos.

    El alcance es exactamente uno de ``tagId`` (los activos del usuario con
    esa etiqueta) o ``assetIds`` (hasta 50 ids separados por comas). Sin
    ``agg`` se devuelve una serie por activo; con ``agg`` (``sum``, ``avg`` o
    ``max``), una sola serie que los combina. ``bucketAgg`` (``min``, ``avg``
    por defecto, ``max``) dice cómo se resume cada cubo dentro de un activo.
    ``bucket`` es el tamaño del cubo en segundos; sin él se usa el más fino
    que cabe en ``maxSeriesPoints``. Tras cargar, ``assetIds`` queda como
    ``asset_ids`` (lista de enteros, o ``None``) y ``period`` como
    ``requested_duration``.
    """
    metric = fields.String(required=True)
    tagId = fields.Integer(load_default=None, validate=validate.Range(min=1))
    assetIds = fields.String(
        load_default=None,
        validate=validate.Regexp(
            r"^[1-9][0-9]*(,[1-9][0-9]*){0,49}$",
            error="assetIds debe ser una lista de hasta 50 ids separados por comas.",
        ),
    )
    agg = fields.String(load_default=None, validate=validate.OneOf(["sum", "avg", "max"]))
    bucketAgg = fields.String(load_default="avg", validate=validate.OneOf(["min", "avg", "max"]))
    bucket = fields.Integer(load_default=None, validate=validate.Range(min=1))
    period = _build_period_field()
    # Segunda fuente con la que comparar: ``asset:<id>`` o ``tag:<id>``. Una
    # etiqueta se compara combinada con el mismo ``agg``, así que entonces
    # ``agg`` es obligatorio.
    compareTo = fields.String(
        load_default=None,
        validate=validate.Regexp(
            r"^(asset|tag):[1-9][0-9]*$",
            error="compareTo debe tener la forma asset:<id> o tag:<id>.",
        ),
    )

    @validates_schema
    def validate_scope(self, data, **kwargs):
        """Exige uno de ``tagId`` o ``assetIds``, y ``agg`` si se compara con una etiqueta."""
        if (data.get("tagId") is None) == (data.get("assetIds") is None):
            raise ValidationError("Indica exactamente uno de tagId o assetIds.", field_name="tagId")
        compare_to = data.get("compareTo")
        if compare_to and compare_to.startswith("tag:") and data.get("agg") is None:
            raise ValidationError(
                "Comparar con una etiqueta exige agg: es la forma de combinar sus activos.",
                field_name="agg",
            )

    @post_load
    def parse_query(self, data, **kwargs):
        """Convierte ``assetIds``, ``compareTo`` y ``period`` en sus tipos de trabajo."""
        raw_asset_ids = data.pop("assetIds")
        data["asset_ids"] = (
            list(dict.fromkeys(int(asset_id) for asset_id in raw_asset_ids.split(",")))
            if raw_asset_ids else None
        )
        raw_compare_to = data.pop("compareTo")
        if raw_compare_to:
            compare_kind, compare_id = raw_compare_to.split(":")
            data["compare_to"] = (compare_kind, int(compare_id))
        else:
            data["compare_to"] = None
        data["requested_duration"] = _parse_period(data.pop("period"))
        return data


class SeriesPointSchema(Schema):
    """Un punto de una serie: el inicio de su cubo y el valor.

    ``assetCount`` solo viene en una serie combinada: cuántos activos
    aportaron a ese cubo. Una suma sobre dos activos no es comparable con una
    sobre tres, y quien la pinta tiene que poder decirlo.
    """
    at = UTCDateTime()
    value = fields.Float()
    assetCount = fields.Integer()


class MetricSeriesSchema(Schema):
    """Una serie de la respuesta, con de dónde sale.

    ``kind`` es ``asset`` (la serie de un activo: ``assetId`` y su hostname
    como ``label``), ``tag`` (la combinación de los activos de una etiqueta:
    ``tagId`` y su nombre como ``label``) o ``assets`` (la combinación de una
    lista explícita de activos, sin ``label``). Los cubos sin datos no
    aparecen: la ausencia de señal es un hueco, no un cero.

    ``isComparison`` marca la serie pedida con ``compareTo``, que va al final
    y comparte los cubos de las demás: sus puntos caen en los mismos
    instantes, así que se pueden superponer sin reconciliar nada.
    """
    kind = fields.String()
    assetId = fields.Integer(allow_none=True)
    tagId = fields.Integer(allow_none=True)
    label = fields.String(allow_none=True)
    isComparison = fields.Boolean(dump_default=False)
    points = fields.List(fields.Nested(SeriesPointSchema))


class MetricSeriesResponseSchema(Schema):
    """Serie temporal de una métrica sobre varios activos.

    ``bucket`` es el cubo que se usó de verdad: si el pedido daba más puntos
    que ``maxSeriesPoints`` se ensancha al mínimo que cabe e
    ``isBucketWidened`` lo avisa. ``agg`` es nulo cuando se devuelve una serie
    por activo.
    """
    metric = fields.String()
    unit = fields.String()
    bucket = fields.Integer()
    isBucketWidened = fields.Boolean()
    bucketAgg = fields.String()
    agg = fields.String(allow_none=True)
    series = fields.List(fields.Nested(MetricSeriesSchema))
    periodCoveredFrom = UTCDateTime()
    periodCoveredTo = UTCDateTime()
    isPeriodClipped = fields.Boolean()


# =============================================================================
# INVENTARIO DE SOFTWARE — reemplaza por completo en cada escaneo, sin delta
# =============================================================================

class SoftwareViewSchema(Schema):
    """Vista de una aplicación instalada (respuesta, no ingesta)."""
    name = fields.String()
    type = fields.String(allow_none=True)
    vendor = fields.String(allow_none=True)
    version = fields.String(allow_none=True)
    guid = fields.String(allow_none=True)
    installedAt = fields.String(allow_none=True)
    installPath = fields.String(allow_none=True)
    architecture = fields.String(allow_none=True)
    sizeBytes = fields.Integer(allow_none=True)
    status = fields.String(allow_none=True)
    source = fields.String(allow_none=True)


class AssetInventoryResponseSchema(Schema):
    """Último inventario de software conocido de un activo.

    ``collectedAt`` y ``software`` son nulos/vacíos si el activo nunca ha
    mandado un escaneo de inventario (agente antiguo, o aún no le tocó el
    primer escaneo) — no es un error, es un estado legítimo.
    """
    collectedAt = UTCDateTime(allow_none=True)
    software = fields.List(fields.Nested(SoftwareViewSchema))


# =============================================================================
# ANÁLISIS DEL INVENTARIO CON LYBRA — el resumen; el desglose vive
# en Themis, que ya tiene la interfaz para presentarlo
# =============================================================================

class AnalyzeInventoryResponseSchema(Schema):
    """Confirmación de que el análisis se ha encolado."""
    scanId = fields.Integer()


class InventoryAnalysisSummarySchema(Schema):
    """Resumen del último análisis de inventario de un activo.

    ``scanId`` nulo significa "nunca se ha analizado" — estado inicial de
    todo activo, no un error. Con un escaneo en curso (``status`` a
    ``pending``/``running``) los recuentos llegan a cero hasta que termina.
    """
    scanId          = fields.Integer(allow_none=True)
    status          = fields.String(allow_none=True)
    startedAt       = fields.String(allow_none=True)
    finishedAt      = fields.String(allow_none=True)
    totalFindings   = fields.Integer(load_default=0)
    # {"CRITICAL": 2, "HIGH": 5, ...} — solo los niveles con al menos un
    # hallazgo, para no obligar al cliente a filtrar ceros.
    byPriority      = fields.Dict(keys=fields.String(), values=fields.Integer())
    confirmedCount  = fields.Integer(load_default=0)
    vulnerableCount = fields.Integer(load_default=0)
    # Paquetes inventariados analizados (uno por entrada del inventario, se le
    # haya resuelto un CPE o no). Con `vulnerableCount` a cero permite avisar
    # de que "sin detecciones" no equivale a "verificado limpio".
    packageCount    = fields.Integer(load_default=0)
    # De esos, cuántos el matcher no pudo ni identificar
    # (`Finding.cpe_resolved=False`) — el número real detrás del aviso, en vez
    # de "puede que alguno no se haya reconocido".
    unresolvedCount = fields.Integer(load_default=0)
