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
  { key: 'cpuPct', name: 'CPU', unit: 'percent', additive: false },
  { key: 'memPct', name: 'Memoria', unit: 'percent', additive: false },
  { key: 'swapPct', name: 'Swap', unit: 'percent', additive: false },
  { key: 'diskMaxPct', name: 'Disco', unit: 'percent', additive: false },
  { key: 'load1', name: 'Carga', unit: 'loadAverage', additive: false },
  { key: 'netRxBps', name: 'Red · entrada', unit: 'bytesPerSecond', additive: true },
  { key: 'netTxBps', name: 'Red · salida', unit: 'bytesPerSecond', additive: true },
  { key: 'powerWatts', name: 'Potencia', unit: 'watts', additive: true },
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
  { value: 'asset', label: 'Un activo', needs: 'asset' },
  { value: 'tag', label: 'Una etiqueta', needs: 'tag' },
  { value: 'fleet', label: 'Todo el parque', needs: null },
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
  { value: '24h', label: '24 h' },
  { value: '7d', label: '7 días' },
  { value: '30d', label: '30 días' },
]

/** Cómo se combinan entre activos los valores de cada uno, en los alcances agregados. */
export const STATS_AGGREGATIONS = [
  { value: 'avg', label: 'Media', needsAdditive: false },
  { value: 'max', label: 'Máximo', needsAdditive: false },
  { value: 'sum', label: 'Total', needsAdditive: true },
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
      name: metric.name,
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
      name: metric.name,
      hasData: (aggregate.assetsWithData ?? 0) > 0,
      assetsWithData: aggregate.assetsWithData ?? 0,
      value: formatStatValue({ unit: aggregate.unit ?? metric.unit }, aggregate.value),
    }
  })
}

/**
 * Describe en una frase la ventana que la respuesta cubrió de verdad.
 *
 * Todos los endpoints de estadísticas recortan el periodo a lo que pueden
 * cubrir y lo avisan con `isPeriodClipped`. Un "máximo de los últimos 365
 * días" calculado sobre 30 tiene que decirlo, y este es el texto que lo dice.
 *
 * @param {object|null} body - Cualquier respuesta de estadísticas con
 *   `periodCoveredFrom`/`periodCoveredTo`/`isPeriodClipped`.
 * @returns {string} La frase, o cadena vacía si la respuesta no trae ventana
 *   (los endpoints que son una foto del ahora, como el panorama del parque).
 */
export function describeCoverage(body) {
  if (!body?.periodCoveredFrom || !body?.periodCoveredTo) return ''
  const from = new Date(body.periodCoveredFrom)
  const to = new Date(body.periodCoveredTo)
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return ''

  const days = Math.round((to.getTime() - from.getTime()) / 86400e3)
  const hours = Math.round((to.getTime() - from.getTime()) / 3600e3)
  const span = days >= 1 ? `${days} d` : `${hours} h`
  return body.isPeriodClipped
    ? `Calculado sobre ${span}: el periodo pedido excedía lo que se conserva.`
    : `Calculado sobre ${span}.`
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
