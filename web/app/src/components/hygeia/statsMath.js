/**
 * Lógica pura de la vista de estadísticas de Hygeia — sin Vue ni DOM, para
 * poder testearla en Node igual que `format.js` y `chartMath.js`.
 *
 * El principio de diseño del roadmap de estadísticas es que **el cliente
 * formatea, no agrega**: todos los mínimos, máximos, medias, percentiles y
 * rankings los calcula el servidor, y aquí solo se decide cómo se leen. Por
 * eso este módulo no tiene una sola suma: traduce unidades a texto, ordena
 * catálogos y compone las filas de las tablas.
 *
 * Aquí viven cuatro cosas:
 *   - El catálogo de métricas consultables (`STATS_METRICS`), que refleja el
 *     registro cerrado del servidor: una entrada por métrica, con su unidad y
 *     cómo se formatea.
 *   - Los presets de alcance y periodo, que son los tres ejes del selector.
 *   - El formateo por unidad (`formatStatValue`), que es lo que permite que la
 *     misma tabla sirva para un porcentaje, una tasa en bytes por segundo y
 *     unos vatios.
 *   - La composición de las filas de las tablas de resumen y de ranking.
 *   - La geometría de la gráfica comparativa (`alignComparisonSeries`,
 *     `comparisonPath`, `inactivityRanges`), que superpone varias métricas de
 *     unidades distintas sobre el mismo eje temporal sin reconciliar nada: el
 *     servidor ya las devuelve alineadas por cubo.
 */

import { fmtBytes, fmtLoad1, fmtPct, fmtRate, fmtWatts } from './format.js'

/** Ausencia de dato, en la forma que esperan las plantillas. */
const NO_DATA = { text: '—', unit: '' }

function isMissing(value) {
  return value === null || value === undefined || Number.isNaN(value)
}

/**
 * Métricas sobre las que se pueden pedir estadísticas.
 *
 * Es el reflejo del registro cerrado del servidor
 * (`hygeia/services/metric_registry.py`): las mismas ocho claves, en el mismo
 * orden en que se leen de arriba abajo en una ficha. `additive` marca las que
 * se pueden sumar entre activos — el servidor rechaza `agg=sum` en las demás,
 * y el selector no debe ofrecer una combinación que va a volver como un 400.
 *
 * `unit` no es decorativa: es lo que elige el formateador, y por tanto lo que
 * decide si un 9.400.000 se lee como "9,4 MB/s" o como un número crudo.
 */
export const STATS_METRICS = [
  { key: 'cpuPct', labelKey: 'hygeia.metrics.cpuPct', unit: 'percent', additive: false },
  { key: 'memPct', labelKey: 'hygeia.metrics.memPct', unit: 'percent', additive: false },
  { key: 'swapPct', labelKey: 'hygeia.metrics.swapPct', unit: 'percent', additive: false },
  { key: 'diskMaxPct', labelKey: 'hygeia.metrics.diskMaxPct', unit: 'percent', additive: false },
  { key: 'load1', labelKey: 'hygeia.metrics.load1', unit: 'loadAverage', additive: false },
  { key: 'netRxBps', labelKey: 'hygeia.metrics.netRxBps', unit: 'bytesPerSecond', additive: true },
  { key: 'netTxBps', labelKey: 'hygeia.metrics.netTxBps', unit: 'bytesPerSecond', additive: true },
  { key: 'powerWatts', labelKey: 'hygeia.metrics.powerWatts', unit: 'watts', additive: true },
]

/**
 * La métrica del catálogo con esa clave.
 *
 * @param {string} key - Clave pública de la métrica (`cpuPct`…).
 * @returns {object|null} La entrada del catálogo, o `null` si no existe.
 */
export function metricOf(key) {
  return STATS_METRICS.find((metric) => metric.key === key) ?? null
}

/**
 * Alcances del selector: sobre qué se calculan las estadísticas.
 *
 * `needs` dice qué hace falta elegir además del alcance, para que la vista
 * sepa cuándo pintar el desplegable de activos o el de etiquetas sin
 * ramificar por el valor a mano.
 */
export const STATS_SCOPES = [
  { value: 'asset', labelKey: 'hygeia.stats.scopes.asset', needs: 'asset' },
  { value: 'tag', labelKey: 'hygeia.stats.scopes.tag', needs: 'tag' },
  { value: 'fleet', labelKey: 'hygeia.stats.scopes.fleet', needs: null },
]

/**
 * Periodos del selector, en la forma `<n>h`/`<n>d` que espera la API.
 *
 * Se quedan en 30 días porque es la retención por defecto de los snapshots:
 * pedir más no añade histórico, solo hace que la respuesta venga recortada y
 * marcada como tal. Un despliegue con más retención lo notará en que la
 * respuesta deja de venir recortada, no en este selector.
 */
export const STATS_PERIODS = [
  { value: '24h', labelKey: 'hygeia.stats.periods.24h' },
  { value: '7d', labelKey: 'hygeia.stats.periods.7d' },
  { value: '30d', labelKey: 'hygeia.stats.periods.30d' },
]

/** Cómo se combinan entre activos los valores de cada uno, en los alcances agregados. */
export const STATS_AGGREGATIONS = [
  { value: 'avg', labelKey: 'hygeia.stats.aggregations.avg', needsAdditive: false },
  { value: 'max', labelKey: 'hygeia.stats.aggregations.max', needsAdditive: false },
  { value: 'sum', labelKey: 'hygeia.stats.aggregations.sum', needsAdditive: true },
]

const UNIT_FORMATTERS = {
  percent: (value) => ({ text: fmtPct(value), unit: '%' }),
  loadAverage: (value) => ({ text: fmtLoad1(value), unit: '' }),
  bytesPerSecond: fmtRate,
  watts: fmtWatts,
  bytes: fmtBytes,
}

/**
 * Formatea un valor en la unidad de su métrica.
 *
 * Devuelve el número y la unidad por separado, no una cadena montada, por la
 * misma razón que `format.js`: la tabla los rotula con estilos distintos, y en
 * las tasas la unidad depende de la magnitud del valor, así que no puede venir
 * fija desde el catálogo.
 *
 * @param {object|string|null} metric - Entrada del catálogo, o su clave.
 * @param {number|null} value - Valor a formatear.
 * @returns {{text: string, unit: string}} Texto y unidad, o `—` sin dato. Una
 *   unidad que este módulo no conozca —una que el servidor añada antes que el
 *   SPA— cae en el número crudo, nunca en un `undefined` pintado en pantalla.
 */
export function formatStatValue(metric, value) {
  if (isMissing(value)) return NO_DATA
  const definition = typeof metric === 'string' ? metricOf(metric) : metric
  const formatter = UNIT_FORMATTERS[definition?.unit]
  if (!formatter) return { text: String(value), unit: '' }
  const formatted = formatter(value)
  return typeof formatted === 'string' ? { text: formatted, unit: '' } : formatted
}

/**
 * Compone las filas de la tabla de resumen de un activo.
 *
 * Una métrica que el servidor resumió sin ninguna muestra viene con todos sus
 * valores nulos y `sampleCount` a cero. Esa fila **no se oculta**: se marca con
 * `hasData: false` para que la vista pueda decir "sin datos en el periodo", que
 * es información —el agente no reporta esa métrica en esta máquina— y no un
 * hueco que convenga esconder.
 *
 * @param {object|null} metricsByName - El bloque `metrics` de
 *   `GET /hygeia/assets/<id>/stats/summary`, indexado por nombre de métrica.
 * @returns {Array<object>} Una fila por métrica **del catálogo** presente en la
 *   respuesta, en el orden del catálogo y no en el que llegara el JSON, con
 *   `min`/`avg`/`p95`/`max`/`current` ya formateados.
 */
export function summaryRows(metricsByName) {
  if (!metricsByName) return []
  return STATS_METRICS.filter((metric) => metric.key in metricsByName).map((metric) => {
    const summary = metricsByName[metric.key] ?? {}
    return {
      key: metric.key,
      labelKey: metric.labelKey,
      hasData: (summary.sampleCount ?? 0) > 0,
      sampleCount: summary.sampleCount ?? 0,
      min: formatStatValue(metric, summary.min),
      avg: formatStatValue(metric, summary.avg),
      p95: formatStatValue(metric, summary.p95),
      max: formatStatValue(metric, summary.max),
      current: formatStatValue(metric, summary.current),
      timestampOfMax: summary.timestampOfMax ?? null,
      timestampOfMin: summary.timestampOfMin ?? null,
    }
  })
}

/**
 * Compone las filas del ranking de activos por una métrica.
 *
 * El orden lo decide el servidor —es lo que significa "ranking"— y aquí se
 * conserva tal cual; lo único que se añade es la posición y el valor
 * formateado. Reordenar en el cliente sería justamente agregar, que es lo que
 * esta capa no hace.
 *
 * @param {Array<object>|null} assets - El array `assets` de
 *   `GET /hygeia/stats/ranking`.
 * @param {object|string|null} metric - Métrica por la que se ordenó, para
 *   formatear su valor en la unidad correcta.
 * @returns {Array<object>} Filas con `position` (empezando en 1), `assetId`,
 *   `hostname`, `value` formateado y `sampleCount`.
 */
export function rankingRows(assets, metric) {
  return (assets ?? []).map((entry, index) => ({
    position: index + 1,
    assetId: entry.assetId,
    hostname: entry.hostname,
    value: formatStatValue(metric, entry.value),
    sampleCount: entry.sampleCount ?? 0,
  }))
}

/**
 * Compone las filas de las métricas agregadas de una etiqueta.
 *
 * Cada métrica trae su propio `value` ya combinado por el servidor y su
 * `unit`; la unidad de la respuesta manda sobre la del catálogo, porque hay
 * agregados que cambian de magnitud (la memoria se agrega en porcentaje aunque
 * los bytes usados existan dentro de cada latido).
 *
 * @param {object|null} metricsByName - El bloque `metrics` de
 *   `GET /hygeia/stats/by-tag/<tagId>`.
 * @returns {Array<object>} Una fila por métrica del catálogo presente en la
 *   respuesta, en el orden del catálogo.
 */
export function tagMetricRows(metricsByName) {
  if (!metricsByName) return []
  return STATS_METRICS.filter((metric) => metric.key in metricsByName).map((metric) => {
    const aggregate = metricsByName[metric.key] ?? {}
    return {
      key: metric.key,
      labelKey: metric.labelKey,
      hasData: (aggregate.assetsWithData ?? 0) > 0,
      assetsWithData: aggregate.assetsWithData ?? 0,
      value: formatStatValue({ unit: aggregate.unit ?? metric.unit }, aggregate.value),
    }
  })
}

/**
 * Describe en una frase, para quien lee la tabla, el tiempo que cubren los
 * números.
 *
 * Todos los endpoints de estadísticas recortan el periodo a lo que pueden
 * cubrir y lo avisan con `isPeriodClipped`. Un "máximo de los últimos 365
 * días" calculado sobre 30 tiene que decirlo, y este es el texto que lo dice,
 * en términos de historial guardado y no de cómo se calcula.
 *
 * @param {object|null} body - Cualquier respuesta de estadísticas con
 *   `periodCoveredFrom`/`periodCoveredTo`/`isPeriodClipped`.
 * @param {Function} t - Función de traducción de vue-i18n (`useI18n().t` o
 *   `i18n.global.t`).
 * @returns {string} «Periodo analizado: 7 días.» si se cubrió lo pedido;
 *   «Solo se guardan 30 días de historial: el resultado cubre ese tiempo.» si
 *   se recortó; o cadena vacía si la respuesta no trae ventana (los endpoints
 *   que son una foto del ahora, como el panorama del parque) o trae fechas
 *   ilegibles.
 */
export function describeCoverage(body, t) {
  if (!body?.periodCoveredFrom || !body?.periodCoveredTo) return ''
  const from = new Date(body.periodCoveredFrom)
  const to = new Date(body.periodCoveredTo)
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return ''

  const days = Math.round((to.getTime() - from.getTime()) / 86400e3)
  const hours = Math.round((to.getTime() - from.getTime()) / 3600e3)
  const amount = days >= 1 ? days : hours
  const span = t(days >= 1 ? 'hygeia.stats.spanDays' : 'hygeia.stats.spanHours', { count: amount }, amount)
  return body.isPeriodClipped
    ? t('hygeia.stats.coverageClipped', { span }, amount)
    : t('hygeia.stats.coverage', { span })
}

/**
 * Si una combinación de métrica y agregación es válida para el servidor.
 *
 * Sumar el porcentaje de CPU de tres equipos da una cifra que no mide nada, y
 * el servidor la rechaza con un 400. Preguntarlo aquí permite desactivar la
 * opción en el selector en vez de dejar que el usuario provoque el error.
 *
 * @param {object|string|null} metric - Entrada del catálogo, o su clave.
 * @param {string} aggregation - `avg`, `max` o `sum`.
 * @returns {boolean} `true` si la combinación se puede pedir.
 */
export function isAggregationAllowed(metric, aggregation) {
  const definition = typeof metric === 'string' ? metricOf(metric) : metric
  const option = STATS_AGGREGATIONS.find((candidate) => candidate.value === aggregation)
  if (!definition || !option) return false
  return !option.needsAdditive || definition.additive
}

/* ── Gráfica comparativa ───────────────────────────────────────────────── */

/**
 * Cuántas métricas se pueden superponer a la vez.
 *
 * Tres es el tope de la necesidad, y no es arbitrario: cada métrica
 * superpuesta tiene su propia escala vertical (son unidades distintas), así
 * que la cuarta línea deja de aportar comparación y empieza a aportar ruido.
 */
export const MAX_COMPARISON_METRICS = 3

/**
 * Colores de las líneas superpuestas, por posición de selección.
 *
 * Van por posición y no por métrica para que la primera métrica elegida sea
 * siempre la del color principal, sea la que sea: lo que se compara cambia de
 * una consulta a otra, y el color tiene que identificar la línea dentro de
 * esta gráfica, no la métrica en abstracto.
 */
export const COMPARISON_COLORS = ['var(--accent-bright)', 'var(--info)', 'var(--warn)']

/**
 * Cubo de agregación que corresponde a un periodo de estadísticas.
 *
 * Se fija explícitamente en vez de dejar que el servidor elija el más fino que
 * quepa, y esa es la clave de que la comparación funcione: los cubos del
 * servidor son múltiplos del reloj (`floor(epoch / cubo)`), así que dos
 * peticiones con el mismo cubo caen en los mismos instantes exactos y las
 * series se pueden superponer sin interpolar ni reconciliar nada. Si cada
 * métrica eligiera su propio cubo, las líneas quedarían desfasadas entre sí.
 *
 * @param {string} period - Periodo en la forma `<n>h`/`<n>d` de la API.
 * @returns {number} Segundos del cubo. Un periodo desconocido cae en el de 24 h,
 *   que es el más usado, en vez de quedarse sin cubo.
 */
export function bucketForPeriod(period) {
  const BUCKETS = { '24h': 300, '7d': 1800, '30d': 7200 }
  return BUCKETS[period] ?? 300
}

/**
 * Cubos seguidos sin ningún dato a partir de los cuales el tramo cuenta como
 * inactividad. Un cubo suelto vacío es ruido de muestreo —un agente que
 * reporta cerca del borde del cubo—, no un apagón, y marcarlo partiría las
 * líneas en trozos que no se llegan a dibujar.
 */
const MIN_INACTIVE_BUCKETS = 2

/**
 * Rejilla completa de instantes esperados de un periodo, a pasos regulares
 * del cubo con el que se pidió.
 *
 * Existe para que un tramo en el que **ninguna** métrica tuvo dato —el caso
 * típico de un activo apagado— siga presente en el eje temporal aunque no
 * traiga ningún punto: si el eje solo llevara los instantes que sí trajo
 * alguna métrica, ese tramo entero desaparecería y los dos puntos reales más
 * próximos quedarían adyacentes, dibujando una línea recta a través del
 * apagón como si el dato fuera continuo.
 *
 * Los extremos se redondean hacia abajo a un múltiplo del cubo porque así
 * etiqueta el servidor cada punto (`floor(epoch / cubo) * cubo`), mientras
 * que la cobertura es el instante real en que empieza y acaba la ventana. Sin
 * ese redondeo, ningún instante de la rejilla coincidiría con un dato y cada
 * punto real quedaría aislado entre dos huecos.
 *
 * @param {{from: string|null, to: string|null, bucketMs: number|null}} range
 *   Cobertura del periodo (`periodCoveredFrom`/`periodCoveredTo` de la
 *   respuesta) y el cubo real usado, en milisegundos.
 * @returns {Array<number>|null} Los instantes de la rejilla, en milisegundos,
 *   o `null` si falta algún dato de `range` o el periodo es degenerado (sin
 *   cobertura o al revés), en cuyo caso no se puede construir.
 */
function fullPeriodGrid({ from, to, bucketMs } = {}) {
  if (!from || !to || !bucketMs) return null
  const coveredFrom = new Date(from).getTime()
  const coveredTo = new Date(to).getTime()
  if (Number.isNaN(coveredFrom) || Number.isNaN(coveredTo) || coveredTo <= coveredFrom) return null

  const start = Math.floor(coveredFrom / bucketMs) * bucketMs
  const end = Math.floor(coveredTo / bucketMs) * bucketMs
  const grid = []
  for (let instant = start; instant <= end; instant += bucketMs) grid.push(instant)
  return grid
}

/**
 * Deja en el eje solo los instantes vacíos que forman un tramo de inactividad.
 *
 * @param {Array<number>} candidates - Instantes ordenados: los de la rejilla
 *   y los que trajo alguna métrica.
 * @param {Set<number>} presentInstants - Instantes con dato en alguna métrica.
 * @returns {Array<number>} Los instantes con dato, más los vacíos que van en
 *   rachas de al menos `MIN_INACTIVE_BUCKETS`; los vacíos sueltos se quitan.
 */
function keepInactiveRuns(candidates, presentInstants) {
  const kept = []
  let run = []
  const flushRun = () => {
    if (run.length >= MIN_INACTIVE_BUCKETS) kept.push(...run)
    run = []
  }
  for (const instant of candidates) {
    if (presentInstants.has(instant)) {
      flushRun()
      kept.push(instant)
    } else {
      run.push(instant)
    }
  }
  flushRun()
  return kept
}

/**
 * Alinea varias series de métricas distintas sobre un único eje temporal.
 *
 * Cada serie llega con sus propios puntos y sin los cubos que no tuvieron
 * datos —la ausencia de señal es un hueco, no un cero—, así que dos métricas
 * del mismo periodo pueden traer distinto número de puntos. Esta función
 * construye el eje y coloca cada métrica sobre él, con `null` en los
 * instantes en que esa métrica no tiene dato. No interpola: un hueco sigue
 * siendo un hueco.
 *
 * Con `range` completo, el eje añade a los instantes con dato los de la
 * **rejilla del periodo** (`fullPeriodGrid`) que forman rachas de al menos
 * `MIN_INACTIVE_BUCKETS` cubos sin ningún dato: así un apagón queda
 * representado en el eje en vez de desaparecer. Sin `range` —o incompleto— el
 * eje es la unión ordenada de los instantes con dato.
 *
 * Cada métrica conserva su propio mínimo y máximo, porque **no comparten
 * escala vertical**: superponer un porcentaje y una tasa en bytes por segundo
 * en el mismo eje Y aplastaría el porcentaje contra el suelo. Lo que se compara
 * es la *forma* de las curvas en el tiempo, y cada una se dibuja normalizada a
 * su propio rango.
 *
 * @param {Array<{key: string, name: string, points: Array<{at: string, value: number}>}>} sources
 *   Una entrada por métrica seleccionada, con los puntos tal como los sirve
 *   `GET /hygeia/stats/series`.
 * @param {{from: string|null, to: string|null, bucketMs: number|null}} [range]
 *   Cobertura del periodo y cubo real, para construir la rejilla completa
 *   (ver `fullPeriodGrid`). Opcional; sin ella el eje sale de los datos.
 * @returns {{instants: Array<number>, lanes: Array<object>}} El eje temporal en
 *   milisegundos y una calle por métrica, con sus valores alineados, su rango y
 *   cuántos puntos con dato tiene. Sin ninguna fuente con puntos, las dos
 *   listas vienen vacías.
 */
export function alignComparisonSeries(sources, range) {
  const withPoints = (sources ?? []).filter((source) => (source?.points ?? []).length)
  if (!withPoints.length) return { instants: [], lanes: [] }

  const valuesByInstant = withPoints.map((source) => {
    const byInstant = new Map()
    for (const point of source.points) {
      const instant = new Date(point.at).getTime()
      if (!Number.isNaN(instant) && !isMissing(point.value)) byInstant.set(instant, point.value)
    }
    return byInstant
  })

  const presentInstants = new Set(valuesByInstant.flatMap((byInstant) => [...byInstant.keys()]))
  const grid = fullPeriodGrid(range ?? {})
  const candidates = [...new Set(grid ? [...grid, ...presentInstants] : presentInstants)]
    .sort((left, right) => left - right)
  const instants = grid ? keepInactiveRuns(candidates, presentInstants) : candidates

  const lanes = withPoints.map((source, position) => {
    const byInstant = valuesByInstant[position]
    const values = instants.map((instant) => byInstant.get(instant) ?? null)
    const present = [...byInstant.values()]
    return {
      key: source.key,
      name: source.name,
      color: COMPARISON_COLORS[position % COMPARISON_COLORS.length],
      values,
      min: Math.min(...present),
      max: Math.max(...present),
      sampleCount: present.length,
    }
  })

  return { instants, lanes }
}

/**
 * Puntos del `polyline` de una calle, normalizada a su propio rango.
 *
 * El eje X es el tiempo real —la posición de cada punto sale de su instante y
 * no de su índice—, así que un hueco de telemetría se ve como un hueco en la
 * línea y no como un tramo comprimido. Los instantes sin dato de esa métrica
 * cortan la línea en vez de unirse con una recta a través del hueco, que
 * dibujaría una continuidad que no se midió.
 *
 * Una calle plana (mínimo igual al máximo) se dibuja en el centro y no en el
 * borde: un host estable en el 45 % no debe leerse como uno al 100 %.
 *
 * @param {object} lane - Una calle de `alignComparisonSeries`.
 * @param {Array<number>} instants - El eje temporal compartido, en ms.
 * @param {{width: number, height: number}} box - Caja de dibujo en unidades SVG.
 * @returns {Array<string>} Un `points` de `polyline` por tramo continuo de la
 *   línea. Los tramos de un solo punto se descartan: un `polyline` de un punto
 *   no pinta nada.
 */
export function comparisonPath(lane, instants, box) {
  if (!lane || instants.length < 2) return []

  const firstInstant = instants[0]
  const span = instants[instants.length - 1] - firstInstant
  const range = lane.max - lane.min

  const segments = []
  let current = []
  instants.forEach((instant, index) => {
    const value = lane.values[index]
    if (isMissing(value)) {
      if (current.length > 1) segments.push(current)
      current = []
      return
    }
    const x = span === 0 ? 0 : ((instant - firstInstant) / span) * box.width
    const normalized = range === 0 ? 0.5 : (value - lane.min) / range
    const y = box.height - normalized * box.height
    current.push(`${x.toFixed(2)},${y.toFixed(2)}`)
  })
  if (current.length > 1) segments.push(current)

  return segments.map((segment) => segment.join(' '))
}

/**
 * Tramos del eje en los que ninguna calle tiene dato: el activo no reportó
 * nada en absoluto durante ese tramo, a diferencia de un hueco de una sola
 * métrica mientras las demás sí tienen lectura.
 *
 * Se calcula aparte de `comparisonPath` porque el corte de una línea no basta
 * para leerse como «el activo estuvo inactivo»: una línea rota es igual de
 * fácil de leer como ruido puntual. Estos tramos se pintan como una franja de
 * fondo que lo dice explícitamente.
 *
 * @param {Array<object>} lanes - Las calles de `alignComparisonSeries`, ya
 *   alineadas sobre `instants`.
 * @param {Array<number>} instants - El eje temporal compartido, en ms.
 * @param {{width: number, height: number}} box - Caja de dibujo en unidades SVG.
 * @returns {Array<{x: number, width: number}>} Un rectángulo por tramo
 *   contiguo sin ningún dato, en las mismas unidades que `comparisonPath`.
 *   Vacío sin calles, con menos de dos instantes, o si nunca faltan todas a
 *   la vez.
 */
export function inactivityRanges(lanes, instants, box) {
  if (!lanes?.length || instants.length < 2) return []

  const firstInstant = instants[0]
  const span = instants[instants.length - 1] - firstInstant
  if (span === 0) return []

  const toX = (instant) => ((instant - firstInstant) / span) * box.width

  const ranges = []
  let start = null
  instants.forEach((instant, index) => {
    const allMissing = lanes.every((lane) => isMissing(lane.values[index]))
    if (allMissing) {
      if (start === null) start = instant
      return
    }
    if (start !== null) {
      ranges.push({ x: toX(start), width: toX(instant) - toX(start) })
      start = null
    }
  })
  if (start !== null) {
    ranges.push({ x: toX(start), width: toX(instants[instants.length - 1]) - toX(start) })
  }
  return ranges
}

/**
 * Rótulo del rango vertical de una calle, en su propia unidad.
 *
 * Es lo que hace legible una gráfica de escalas mezcladas: cada línea dice
 * entre qué dos valores se mueve, porque su altura en la caja no significa lo
 * mismo que la de la línea de al lado.
 *
 * @param {object} lane - Una calle de `alignComparisonSeries`.
 * @returns {string} p. ej. `"4 – 97 %"`, o cadena vacía si la calle no tiene datos.
 */
export function describeLaneRange(lane) {
  if (!lane || !lane.sampleCount) return ''
  const low = formatStatValue(lane.key, lane.min)
  const high = formatStatValue(lane.key, lane.max)
  return low.unit === high.unit
    ? `${low.text} – ${high.text} ${high.unit}`.trim()
    : `${low.text} ${low.unit} – ${high.text} ${high.unit}`.trim()
}

/* ── Exportación ───────────────────────────────────────────────────────── */

/**
 * Cuerpo de `POST /hygeia/documents` que exporta la tabla que se ve, en CSV o en PDF.
 *
 * El documento se genera en segundo plano con la misma consulta que la tabla:
 * el resumen de un activo con todas las métricas, las métricas de una
 * etiqueta con su combinación, o el ranking del parque por la métrica
 * elegida. El ranking nunca se pide sumado (el servidor no lo admite), así
 * que «Total» viaja como media, igual que al pintar la tabla.
 *
 * @param {object} selection - Selección de la vista: `scope` (`asset`, `tag`
 *   o `fleet`), `assetId`, `tagId`, `metric`, `aggregation` y `period`.
 * @param {'stats-csv'|'stats-pdf'} [kind='stats-csv'] - Formato del documento a pedir.
 * @returns {object|null} El cuerpo de la petición, o `null` si la selección
 *   está incompleta (un activo o una etiqueta sin elegir).
 */
export function buildStatsDocumentRequest(selection, kind = 'stats-csv') {
  const { scope, assetId, tagId, metric, aggregation, period } = selection ?? {}
  if (scope === 'asset') {
    if (!assetId) return null
    return { kind, dataset: 'summary', assetId, metrics: [], period }
  }
  if (scope === 'tag') {
    if (!tagId) return null
    return { kind, dataset: 'tag-stats', tagId, metrics: [], agg: aggregation, period }
  }
  if (scope === 'fleet') {
    return {
      kind, dataset: 'ranking', metric,
      agg: aggregation === 'sum' ? 'avg' : aggregation, order: 'desc', limit: 10, period,
    }
  }
  return null
}

/**
 * El instante más antiguo de una lista de instantes ISO.
 *
 * La gráfica se compone de una petición por métrica, y cada respuesta dice
 * hasta cuándo se calculó (`periodCoveredTo`). Si alguna salió de la caché del
 * servidor y otra no, la gráfica entera es tan antigua como la más antigua, y
 * eso es lo que tiene que decir «Actualizado hace…».
 *
 * @param {Array<string|null|undefined>} instants - Instantes ISO; los nulos y
 *   los ilegibles se ignoran.
 * @returns {string|null} El más antiguo, tal como venía; `null` si no queda
 *   ninguno válido.
 */
export function oldestInstant(instants) {
  let oldest = null
  let oldestTime = Infinity
  for (const instant of instants ?? []) {
    const time = instant ? new Date(instant).getTime() : NaN
    if (!Number.isNaN(time) && time < oldestTime) {
      oldest = instant
      oldestTime = time
    }
  }
  return oldest
}
