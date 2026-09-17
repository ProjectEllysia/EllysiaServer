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
  MAX_COMPARISON_METRICS, STATS_METRICS, STATS_PERIODS, STATS_SCOPES, STATS_AGGREGATIONS,
  alignComparisonSeries, bucketForPeriod, comparisonPath, describeCoverage, describeLaneRange,
  buildStatsDocumentRequest, formatStatValue, inactivityRanges, isAggregationAllowed, metricOf,
  oldestInstant, rankingRows, summaryRows, tagMetricRows,
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
  describeCoverage(day) === 'Periodo analizado: 1 día.', describeCoverage(day))
check('una ventana corta se describe en horas',
  describeCoverage({ ...day, periodCoveredTo: '2026-09-01T06:00:00Z' })
    === 'Periodo analizado: 6 horas.')
// Un "máximo de los últimos 365 días" calculado sobre 30 tiene que decirlo.
check('una ventana recortada lo dice',
  describeCoverage({ ...day, isPeriodClipped: true })
    === 'Solo se guarda 1 día de historial: el resultado cubre ese tiempo.')
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

console.log('\ncubo de la gráfica comparativa')

// El cubo se fija explícitamente porque es lo que alinea las series: los cubos
// del servidor son múltiplos del reloj, así que el mismo tamaño da los mismos
// instantes en dos peticiones distintas.
eq('cada periodo tiene su cubo', STATS_PERIODS.map((p) => bucketForPeriod(p.value)),
  [300, 1800, 7200])
check('un periodo mayor lleva un cubo mayor',
  bucketForPeriod('30d') > bucketForPeriod('7d') && bucketForPeriod('7d') > bucketForPeriod('24h'))
eq('un periodo desconocido cae en un cubo válido, no en nada', bucketForPeriod('99d'), 300)

console.log('\nalineación de las series superpuestas')

const T0 = Date.parse('2026-09-01T00:00:00Z')
const HOUR = 3600e3

/** Una fuente de serie como la que deja el store tras pedir /stats/series. */
function source(key, name, points) {
  return { key, name, points: points.map(([offset, value]) => ({
    at: new Date(T0 + offset * HOUR).toISOString(), value,
  })) }
}

const aligned = alignComparisonSeries([
  source('cpuPct', 'CPU', [[0, 10], [1, 50], [2, 30]]),
  // A propósito le falta el cubo de la hora 1: las series no tienen por qué
  // traer los mismos cubos, porque los que no tuvieron datos no aparecen.
  source('netRxBps', 'Red · entrada', [[0, 1024], [2, 4096]]),
])

eq('el eje es la unión ordenada de los instantes de todas las series',
  aligned.instants, [T0, T0 + HOUR, T0 + 2 * HOUR])
eq('cada métrica tiene una calle', aligned.lanes.map((l) => l.key), ['cpuPct', 'netRxBps'])
// Sin este null, la línea de red uniría la hora 0 con la hora 2 dibujando una
// continuidad que no se midió.
eq('un instante sin dato de esa métrica queda a null, no interpolado',
  aligned.lanes[1].values, [1024, null, 4096])
eq('los valores presentes conservan su posición', aligned.lanes[0].values, [10, 50, 30])

// Cada métrica conserva su propio rango: superponer un porcentaje y una tasa
// en bytes por segundo sobre el mismo eje Y aplastaría el porcentaje.
eq('cada calle guarda su propio mínimo y máximo',
  [aligned.lanes[0].min, aligned.lanes[0].max, aligned.lanes[1].min, aligned.lanes[1].max],
  [10, 50, 1024, 4096])
eq('y cuántos puntos con dato tiene', aligned.lanes.map((l) => l.sampleCount), [3, 2])
check('las calles llevan colores distintos', aligned.lanes[0].color !== aligned.lanes[1].color)

eq('una serie sin puntos no genera calle',
  alignComparisonSeries([source('cpuPct', 'CPU', []), source('memPct', 'Memoria', [[0, 5]])])
    .lanes.map((l) => l.key), ['memPct'])
eq('sin fuentes no hay eje ni calles', alignComparisonSeries([]), { instants: [], lanes: [] })
eq('unas fuentes nulas tampoco revientan', alignComparisonSeries(null), { instants: [], lanes: [] })
// Un punto sin valor es ausencia de dato, igual que en el resto del módulo.
eq('los puntos con valor nulo no cuentan como muestra',
  alignComparisonSeries([source('cpuPct', 'CPU', [[0, 10], [1, null], [2, 30]])])
    .lanes[0].sampleCount, 2)

check('el tope de métricas superpuestas es tres', MAX_COMPARISON_METRICS === 3)

console.log('\ngeometría de las líneas')

const box = { width: 100, height: 40 }
const straight = alignComparisonSeries([source('cpuPct', 'CPU', [[0, 0], [1, 50], [2, 100]])])
const path = comparisonPath(straight.lanes[0], straight.instants, box)

eq('una línea continua es un solo tramo', path.length, 1)
// El eje X es tiempo real y el Y va invertido (0 arriba en SVG): el mínimo cae
// en el borde inferior y el máximo en el superior.
eq('el primer punto está abajo a la izquierda y el último arriba a la derecha',
  path[0], '0.00,40.00 50.00,20.00 100.00,0.00')

const broken = alignComparisonSeries([
  source('cpuPct', 'CPU', [[0, 10], [1, 20]]),
  source('memPct', 'Memoria', [[0, 40], [3, 60]]),
])
const brokenPath = comparisonPath(broken.lanes[1], broken.instants, box)
check('un hueco corta la línea en vez de cruzarlo', brokenPath.length === 0,
  `tramos: ${JSON.stringify(brokenPath)}`)

// Un host estable en el 45 % no debe leerse como uno al 100 %.
const flat = alignComparisonSeries([source('cpuPct', 'CPU', [[0, 45], [1, 45], [2, 45]])])
eq('una serie plana se dibuja en el centro y no en un borde',
  comparisonPath(flat.lanes[0], flat.instants, box)[0],
  '0.00,20.00 50.00,20.00 100.00,20.00')

eq('una sola muestra no da línea', comparisonPath(straight.lanes[0], [T0], box), [])
eq('una calle inexistente tampoco', comparisonPath(null, straight.instants, box), [])

console.log('\nrejilla completa del periodo (huecos totales)')

// Cubre de la hora 0 a la 5, con dos horas (2 y 3) en las que ninguna
// métrica reporta nada: el caso de un activo apagado.
const gridRange = {
  from: new Date(T0).toISOString(),
  to: new Date(T0 + 5 * HOUR).toISOString(),
  bucketMs: HOUR,
}
const totalGap = alignComparisonSeries([
  source('cpuPct', 'CPU', [[0, 10], [1, 20], [4, 40], [5, 50]]),
], gridRange)

eq('con la cobertura del periodo, el eje es la rejilla completa y no solo los instantes con dato',
  totalGap.instants,
  [T0, T0 + HOUR, T0 + 2 * HOUR, T0 + 3 * HOUR, T0 + 4 * HOUR, T0 + 5 * HOUR])
eq('el tramo sin ningún dato queda a null, no desaparece del eje',
  totalGap.lanes[0].values, [10, 20, null, null, 40, 50])

eq('sin range se cae al comportamiento previo (solo instantes con dato)',
  alignComparisonSeries([source('cpuPct', 'CPU', [[0, 10], [1, 20], [4, 40], [5, 50]])]).instants,
  [T0, T0 + HOUR, T0 + 4 * HOUR, T0 + 5 * HOUR])
eq('un range incompleto también se ignora',
  alignComparisonSeries(
    [source('cpuPct', 'CPU', [[0, 10], [1, 20], [4, 40], [5, 50]])], { from: gridRange.from },
  ).instants,
  [T0, T0 + HOUR, T0 + 4 * HOUR, T0 + 5 * HOUR])

const totalGapPath = comparisonPath(totalGap.lanes[0], totalGap.instants, box)
eq('el tramo sin ningún dato corta la línea de verdad, no la une con una recta',
  totalGapPath.length, 2)

console.log('\ntramos de inactividad')

eq('el hueco total del ejemplo anterior se marca como un tramo de inactividad',
  inactivityRanges(totalGap.lanes, totalGap.instants, box),
  [{ x: 40, width: 40 }])

// La memoria sí tiene dato en la hora 3: solo la hora 2 queda sin ninguna
// métrica, así que el tramo de inactividad es más corto.
const partialAllMissing = alignComparisonSeries([
  source('cpuPct', 'CPU', [[0, 10], [1, 20], [4, 40], [5, 50]]),
  source('memPct', 'Memoria', [[0, 60], [1, 65], [3, 75], [4, 80], [5, 85]]),
], gridRange)
eq('un hueco de una sola métrica no cuenta como inactividad si otra sí tiene dato',
  inactivityRanges(partialAllMissing.lanes, partialAllMissing.instants, box),
  [{ x: 40, width: 20 }])

eq('sin calles no hay tramos de inactividad', inactivityRanges([], totalGap.instants, box), [])
eq('con menos de dos instantes tampoco', inactivityRanges(totalGap.lanes, [T0], box), [])

console.log('\nrótulo del rango de cada línea')

check('el rango se rotula en la unidad de la métrica',
  describeLaneRange(aligned.lanes[0]) === '10 – 50 %', describeLaneRange(aligned.lanes[0]))
check('una tasa se rotula escalada',
  describeLaneRange(aligned.lanes[1]).includes('KB/s'), describeLaneRange(aligned.lanes[1]))
eq('una calle sin datos no se rotula', describeLaneRange({ sampleCount: 0 }), '')
eq('una calle inexistente tampoco', describeLaneRange(null), '')

console.log('\n' + 'petición de exportación')

eq('un activo exporta su resumen con todas las métricas',
  buildStatsDocumentRequest({ scope: 'asset', assetId: 3, period: '7d', metric: 'cpuPct', aggregation: 'max' }),
  { kind: 'stats-csv', dataset: 'summary', assetId: 3, metrics: [], period: '7d' })
eq('una etiqueta exporta sus métricas con su combinación',
  buildStatsDocumentRequest({ scope: 'tag', tagId: 4, period: '24h', aggregation: 'sum' }),
  { kind: 'stats-csv', dataset: 'tag-stats', tagId: 4, metrics: [], agg: 'sum', period: '24h' })
eq('el parque exporta su ranking',
  buildStatsDocumentRequest({ scope: 'fleet', metric: 'memPct', aggregation: 'max', period: '30d' }),
  { kind: 'stats-csv', dataset: 'ranking', metric: 'memPct', agg: 'max', order: 'desc', limit: 10, period: '30d' })
// El ranking no se suma: «Total» se pide como media, igual que la tabla.
eq('el ranking con «Total» se pide como media',
  buildStatsDocumentRequest({ scope: 'fleet', metric: 'netRxBps', aggregation: 'sum', period: '24h' }).agg,
  'avg')
eq('un activo sin elegir no se exporta',
  buildStatsDocumentRequest({ scope: 'asset', assetId: null, period: '24h' }), null)
eq('una etiqueta sin elegir tampoco',
  buildStatsDocumentRequest({ scope: 'tag', tagId: null, period: '24h' }), null)

console.log('\n' + 'antigüedad de la gráfica')

// Si una métrica salió de la caché y otra no, la gráfica es tan vieja como la más vieja.
eq('elige el instante más antiguo',
  oldestInstant(['2026-09-16T10:05:00Z', '2026-09-16T09:50:00Z', '2026-09-16T10:00:00Z']),
  '2026-09-16T09:50:00Z')
eq('ignora nulos e instantes ilegibles',
  oldestInstant([null, 'ayer', '2026-09-16T10:00:00Z', undefined]), '2026-09-16T10:00:00Z')
eq('sin instantes válidos no hay antigüedad', oldestInstant([null, 'ayer']), null)
eq('una lista ausente tampoco', oldestInstant(undefined), null)

console.log(`\n${passed} pasados, ${failed} fallidos`)
process.exit(failed ? 1 : 0)
