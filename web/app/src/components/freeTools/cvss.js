/**
 * Lógica sin Vue de la calculadora CVSS gratuita
 * (`views/tools/aegis/CvssCalculatorView.vue`), para poder probarla con `node`
 * a secas. Implementa la puntuación BASE de CVSS 3.1 tal como la define la
 * especificación de FIRST; no calcula las métricas temporales ni de entorno.
 */

/** Métricas base, en el orden del vector, con sus valores en el orden en que se ofrecen. */
export const METRICS = Object.freeze([
  Object.freeze({ key: 'AV', values: Object.freeze(['N', 'A', 'L', 'P']) }),
  Object.freeze({ key: 'AC', values: Object.freeze(['L', 'H']) }),
  Object.freeze({ key: 'PR', values: Object.freeze(['N', 'L', 'H']) }),
  Object.freeze({ key: 'UI', values: Object.freeze(['N', 'R']) }),
  Object.freeze({ key: 'S', values: Object.freeze(['U', 'C']) }),
  Object.freeze({ key: 'C', values: Object.freeze(['N', 'L', 'H']) }),
  Object.freeze({ key: 'I', values: Object.freeze(['N', 'L', 'H']) }),
  Object.freeze({ key: 'A', values: Object.freeze(['N', 'L', 'H']) }),
])

/** Valores con los que arranca la calculadora: un fallo remoto y total, el caso de 9,8. */
export const DEFAULT_METRICS = Object.freeze({ AV: 'N', AC: 'L', PR: 'N', UI: 'N', S: 'U', C: 'H', I: 'H', A: 'H' })

/** Gravedades, de menor a mayor, con su rótulo en `freeTools.items.cvssCalculator.severity`. */
export const SEVERITIES = Object.freeze(['none', 'low', 'medium', 'high', 'critical'])

/** Pesos de la especificación. `PR` tiene dos juegos según cambie el alcance. */
const WEIGHTS = Object.freeze({
  AV: { N: 0.85, A: 0.62, L: 0.55, P: 0.2 },
  AC: { L: 0.77, H: 0.44 },
  PR: { unchanged: { N: 0.85, L: 0.62, H: 0.27 }, changed: { N: 0.85, L: 0.68, H: 0.5 } },
  UI: { N: 0.85, R: 0.62 },
  CIA: { H: 0.56, L: 0.22, N: 0 },
})

/**
 * Redondea hacia arriba a un decimal como manda CVSS 3.1.
 *
 * Es la función `Roundup` de la especificación: trabaja con enteros para que los
 * errores de coma flotante (`4.000000000000001`) no suban una décima de más.
 *
 * @param {number} value - Número a redondear.
 * @returns {number} El menor múltiplo de 0,1 que no es menor que `value`.
 */
export function roundUp(value) {
  const integer = Math.round(value * 100000)
  if (integer % 10000 === 0) return integer / 100000
  return (Math.floor(integer / 10000) + 1) / 10
}

/**
 * Gravedad cualitativa de una puntuación.
 *
 * @param {number} score - Puntuación de 0 a 10.
 * @returns {string} Uno de `SEVERITIES`: `none` (0), `low` (0,1-3,9), `medium` (4-6,9),
 *   `high` (7-8,9) o `critical` (9-10).
 */
export function severityOf(score) {
  if (score === 0) return 'none'
  if (score < 4) return 'low'
  if (score < 7) return 'medium'
  if (score < 9) return 'high'
  return 'critical'
}

/**
 * Calcula la puntuación base de CVSS 3.1.
 *
 * @param {Record<string, string>} metrics - Un valor por cada métrica de `METRICS`.
 * @returns {{score: number, impact: number, exploitability: number, severity: string}}
 *   `score` de 0 a 10 con un decimal. `impact` y `exploitability` son los dos
 *   subtotales de la especificación (el de impacto puede ser 0 o negativo si no hay
 *   impacto, y entonces `score` es 0) redondeados a un decimal para enseñarlos.
 * @throws {Error} Si falta una métrica o su valor no es uno de los permitidos.
 */
export function calculateBaseScore(metrics) {
  for (const { key, values } of METRICS) {
    if (!values.includes(metrics?.[key])) throw new Error(`Métrica CVSS inválida: ${key}=${metrics?.[key]}`)
  }
  const isChanged = metrics.S === 'C'
  const privileges = WEIGHTS.PR[isChanged ? 'changed' : 'unchanged'][metrics.PR]
  const exploitability = 8.22 * WEIGHTS.AV[metrics.AV] * WEIGHTS.AC[metrics.AC] * privileges * WEIGHTS.UI[metrics.UI]
  const iss = 1 - (1 - WEIGHTS.CIA[metrics.C]) * (1 - WEIGHTS.CIA[metrics.I]) * (1 - WEIGHTS.CIA[metrics.A])
  const impact = isChanged ? 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 : 6.42 * iss

  let score = 0
  if (impact > 0) score = roundUp(Math.min((isChanged ? 1.08 : 1) * (impact + exploitability), 10))
  return {
    score,
    impact: Math.round(impact * 10) / 10,
    exploitability: Math.round(exploitability * 10) / 10,
    severity: severityOf(score),
  }
}

/**
 * Escribe las métricas como vector CVSS.
 *
 * @param {Record<string, string>} metrics - Un valor por cada métrica de `METRICS`.
 * @returns {string} Por ejemplo `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`.
 */
export function buildVector(metrics) {
  return `CVSS:3.1/${METRICS.map(({ key }) => `${key}:${metrics[key]}`).join('/')}`
}

/**
 * Lee un vector CVSS 3.1.
 *
 * @param {unknown} text - El vector, con el prefijo `CVSS:3.1/` y las ocho métricas base
 *   en cualquier orden. Se ignoran los espacios y las mayúsculas.
 * @returns {{ok: true, metrics: Record<string, string>}|{ok: false, reason: 'format'|'version'|'metric'}}
 *   `version` si el prefijo es de otra versión de CVSS; `metric` si falta una métrica,
 *   sobra o repite alguna, o trae un valor no permitido; `format` en cualquier otro caso.
 */
export function parseVector(text) {
  const clean = typeof text === 'string' ? text.replace(/\s+/g, '') : ''
  const [prefix, ...parts] = clean.split('/')
  if (!/^CVSS:\d+\.\d+$/i.test(prefix ?? '')) return { ok: false, reason: 'format' }
  if (prefix.toUpperCase() !== 'CVSS:3.1') return { ok: false, reason: 'version' }

  const metrics = {}
  for (const part of parts) {
    const [key, value] = part.toUpperCase().split(':')
    const metric = METRICS.find((candidate) => candidate.key === key)
    if (!metric || !metric.values.includes(value) || key in metrics) return { ok: false, reason: 'metric' }
    metrics[key] = value
  }
  return METRICS.every(({ key }) => key in metrics) ? { ok: true, metrics } : { ok: false, reason: 'metric' }
}
