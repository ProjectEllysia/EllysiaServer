/**
 * Test de la lógica pura de la vista de estadísticas de Hygeia
 * (`components/hygeia/statsMath.js`).
 *
 * El principio del roadmap es que el servidor agrega y el cliente formatea,
 * así que lo que se prueba aquí no es ninguna cuenta: es que las unidades se
 * lean bien, que el orden de las tablas sea el del catálogo y no el del JSON,
 * que una métrica sin datos siga apareciendo en su fila, y que el selector no
 * ofrezca combinaciones que el servidor va a rechazar.
 *
 *   node web/app/test/hygeia.statsMath.test.mjs
 */

import {
  STATS_METRICS, STATS_PERIODS, STATS_SCOPES, STATS_AGGREGATIONS,
  describeCoverage, formatStatValue, isAggregationAllowed, metricOf,
  rankingRows, summaryRows, tagMetricRows,
} from '../src/components/hygeia/statsMath.js'

let passed = 0
let failed = 0
function check(name, cond, detail = '') {
  if (cond) { passed++; console.log(`  ✓ ${name}`) }
  else { failed++; console.error(`  ✗ ${name}${detail ? ' — ' + detail : ''}`) }
}

function eq(name, actual, expected) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  check(name, a === e, `esperado ${e}, obtenido ${a}`)
}

/** Un resumen de métrica como el que sirve la API, con lo que haga falta. */
function summary(fields = {}) {
  return {
    min: null, avg: null, p95: null, max: null, current: null,
    sampleCount: 0, timestampOfMax: null, timestampOfMin: null,
    ...fields,
  }
}

console.log('\ncatálogo de métricas')

check('tiene las ocho métricas del registro del servidor', STATS_METRICS.length === 8)
check(
  'solo la red y la potencia son aditivas',
  STATS_METRICS.filter((m) => m.additive).map((m) => m.key).join(',')
    === 'netRxBps,netTxBps,powerWatts',
)
check('toda métrica declara unidad', STATS_METRICS.every((m) => Boolean(m.unit)))
check('toda métrica declara nombre en castellano', STATS_METRICS.every((m) => Boolean(m.name)))
eq('metricOf devuelve la entrada por su clave', metricOf('cpuPct')?.name, 'CPU')
eq('metricOf de una clave desconocida es null', metricOf('inventada'), null)

console.log('\nalcances y periodos')

eq('los alcances son activo, etiqueta y parque',
  STATS_SCOPES.map((s) => s.value), ['asset', 'tag', 'fleet'])
check('solo el parque no necesita un id',
  STATS_SCOPES.filter((s) => s.needs === null).map((s) => s.value).join(',') === 'fleet')
check('los periodos usan la forma <n>h/<n>d de la API',
  STATS_PERIODS.every((p) => /^[1-9][0-9]*[hd]$/.test(p.value)))
eq('las agregaciones son media, máximo y total',
  STATS_AGGREGATIONS.map((a) => a.value), ['avg', 'max', 'sum'])

console.log('\nformateo por unidad')

eq('un porcentaje pequeño conserva el decimal',
  formatStatValue('cpuPct', 0.7), { text: '0.7', unit: '%' })
eq('un porcentaje grande va entero', formatStatValue('cpuPct', 87.4), { text: '87', unit: '%' })
eq('una tasa escala a la unidad legible',
  formatStatValue('netRxBps', 9.4 * 1024 * 1024), { text: '9.4', unit: 'MB/s' })
eq('la carga media no lleva unidad', formatStatValue('load1', 1.53), { text: '1.5', unit: '' })
eq('la potencia se rotula en vatios', formatStatValue('powerWatts', 187), { text: '187', unit: 'W' })
eq('la potencia salta a kW cuando el valor lo pide',
  formatStatValue('powerWatts', 2400), { text: '2.4', unit: 'kW' })

eq('un valor ausente es una raya, no un cero',
  formatStatValue('cpuPct', null), { text: '—', unit: '' })
eq('un valor indefinido también', formatStatValue('cpuPct', undefined), { text: '—', unit: '' })
eq('un cero real se pinta como cero', formatStatValue('cpuPct', 0), { text: '0.0', unit: '%' })

// Una unidad que el servidor añada antes que el SPA no debe pintar "undefined"
// en la pantalla: cae en el número crudo.
eq('una unidad desconocida cae en el número crudo',
  formatStatValue({ unit: 'furlongs' }, 42), { text: '42', unit: '' })
eq('una métrica desconocida también',
  formatStatValue('inventada', 42), { text: '42', unit: '' })

console.log('\nfilas del resumen de un activo')

const summaryResponse = {
  // A propósito en un orden distinto al del catálogo: la tabla no debe
  // depender del orden en que el JSON traiga las claves.
  powerWatts: summary({ min: 40, avg: 60, p95: 95, max: 100, current: 55, sampleCount: 12 }),
  cpuPct: summary({ min: 4, avg: 22.5, p95: 80, max: 97, current: 18, sampleCount: 240,
    timestampOfMax: '2026-09-01T09:30:00Z' }),
  memPct: summary(),
}
const rows = summaryRows(summaryResponse)

eq('las filas salen en el orden del catálogo',
  rows.map((r) => r.key), ['cpuPct', 'memPct', 'powerWatts'])
eq('una métrica ausente de la respuesta no inventa fila', rows.length, 3)
eq('los valores vienen ya formateados con su unidad', rows[0].max, { text: '97', unit: '%' })
eq('el instante del máximo viaja tal cual para la vista',
  rows[0].timestampOfMax, '2026-09-01T09:30:00Z')

const emptyRow = rows.find((r) => r.key === 'memPct')
check('una métrica sin muestras sigue teniendo su fila', Boolean(emptyRow))
eq('y se marca como sin datos en vez de esconderse', emptyRow.hasData, false)
eq('con todos sus valores a raya', emptyRow.avg, { text: '—', unit: '' })
eq('una métrica con muestras se marca con datos', rows[0].hasData, true)

eq('un resumen ausente no revienta', summaryRows(null), [])
eq('un resumen vacío no da filas', summaryRows({}), [])

console.log('\nfilas del ranking del parque')

const rankingResponse = [
  { assetId: 7, hostname: 'host-b', value: 91.2, sampleCount: 240 },
  { assetId: 3, hostname: 'host-a', value: 45.0, sampleCount: 240 },
]
const ranked = rankingRows(rankingResponse, 'cpuPct')

eq('la posición empieza en 1', ranked.map((r) => r.position), [1, 2])
// Reordenar aquí sería agregar en el cliente, que es justo lo que esta capa no
// hace: el orden lo decidió el servidor y es lo que significa "ranking".
eq('el orden del servidor se conserva', ranked.map((r) => r.hostname), ['host-b', 'host-a'])
eq('el valor va formateado en la unidad de la métrica',
  ranked[0].value, { text: '91', unit: '%' })
eq('un ranking vacío no da filas', rankingRows([], 'cpuPct'), [])
eq('un ranking ausente tampoco', rankingRows(null, 'cpuPct'), [])

console.log('\nfilas de una etiqueta')

const tagResponse = {
  netRxBps: { unit: 'bytesPerSecond', value: 3 * 1024 * 1024, assetsWithData: 3, assets: [] },
  cpuPct: { unit: 'percent', value: 31.5, assetsWithData: 4, assets: [] },
  swapPct: { unit: 'percent', value: null, assetsWithData: 0, assets: [] },
}
const tagRows = tagMetricRows(tagResponse)

eq('también salen en el orden del catálogo',
  tagRows.map((r) => r.key), ['cpuPct', 'swapPct', 'netRxBps'])
// La unidad de la respuesta manda: hay agregados que cambian de magnitud
// respecto a la métrica cruda.
eq('la unidad de la respuesta manda sobre la del catálogo',
  tagMetricRows({ memPct: { unit: 'percent', value: 50, assetsWithData: 2 } })[0].value,
  { text: '50', unit: '%' })
eq('una tasa agregada escala igual', tagRows[2].value, { text: '3.0', unit: 'MB/s' })
eq('una métrica que ningún activo reportó se marca sin datos',
  tagRows.find((r) => r.key === 'swapPct').hasData, false)
eq('una etiqueta sin bloque de métricas no revienta', tagMetricRows(null), [])

console.log('\ncobertura de la ventana')

const day = {
  periodCoveredFrom: '2026-09-01T00:00:00Z',
  periodCoveredTo: '2026-09-02T00:00:00Z',
  isPeriodClipped: false,
}
check('una ventana de un día se describe en días',
  describeCoverage(day) === 'Calculado sobre 1 d.', describeCoverage(day))
check('una ventana corta se describe en horas',
  describeCoverage({ ...day, periodCoveredTo: '2026-09-01T06:00:00Z' })
    === 'Calculado sobre 6 h.')
// Un "máximo de los últimos 365 días" calculado sobre 30 tiene que decirlo.
check('una ventana recortada lo dice',
  describeCoverage({ ...day, isPeriodClipped: true }).includes('excedía'))
eq('una respuesta sin ventana no describe nada', describeCoverage({}), '')
eq('una respuesta nula tampoco', describeCoverage(null), '')
eq('unas fechas ilegibles no producen texto basura',
  describeCoverage({ periodCoveredFrom: 'ayer', periodCoveredTo: 'hoy' }), '')

console.log('\ncombinaciones válidas de métrica y agregación')

check('la media vale en cualquier métrica', isAggregationAllowed('cpuPct', 'avg'))
check('el máximo también', isAggregationAllowed('cpuPct', 'max'))
// Sumar el porcentaje de CPU de tres equipos da una cifra que no mide nada, y
// el servidor la rechaza con un 400: el selector no debe ofrecerla.
check('el total NO vale en un porcentaje', !isAggregationAllowed('cpuPct', 'sum'))
check('el total NO vale en una carga media', !isAggregationAllowed('load1', 'sum'))
check('el total sí vale en el tráfico de red', isAggregationAllowed('netRxBps', 'sum'))
check('el total sí vale en la potencia', isAggregationAllowed('powerWatts', 'sum'))
check('una métrica desconocida no admite nada', !isAggregationAllowed('inventada', 'avg'))
check('una agregación desconocida tampoco', !isAggregationAllowed('cpuPct', 'mediana'))

console.log(`\n${passed} pasados, ${failed} fallidos`)
process.exit(failed ? 1 : 0)
