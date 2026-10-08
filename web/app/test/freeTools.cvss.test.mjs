/**
 * Tests de la calculadora CVSS 3.1 gratuita (`src/components/freeTools/cvss.js`).
 *
 * Node puro, sin framework. Los vectores y sus puntuaciones son los que publica
 * NVD para vulnerabilidades conocidas: si la fórmula o el redondeo se desvían
 * una décima, falla aquí.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  DEFAULT_METRICS,
  METRICS,
  SEVERITIES,
  buildVector,
  calculateBaseScore,
  parseVector,
  roundUp,
  severityOf,
} from '../src/components/freeTools/cvss.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const locales = ['es', 'en'].map((code) => [code, JSON.parse(readFileSync(`${appRoot}src/i18n/locales/${code}.json`, 'utf-8'))])

let failures = 0
function test(name, fn) {
  try {
    fn()
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
}

const scoreOf = (vector) => {
  const parsed = parseVector(vector)
  assert.ok(parsed.ok, `${vector}: ${parsed.reason}`)
  return calculateBaseScore(parsed.metrics)
}

console.log('puntuación')

test('vectores con la puntuación que publica NVD', () => {
  const published = {
    'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H': 9.8,
    'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H': 10,
    'CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H': 8.1,
    'CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N': 6.1,
    'CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H': 7.8,
    'CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H': 7.8,
    'CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H': 8.8,
    'CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H': 9.9,
    'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N': 7.5,
    'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H': 7.5,
    'CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N': 1.6,
  }
  for (const [vector, score] of Object.entries(published)) assert.equal(scoreOf(vector).score, score, vector)
})

test('sin impacto la puntuación es 0 y no «ninguna» décima', () => {
  const none = scoreOf('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N')
  assert.equal(none.score, 0)
  assert.equal(none.severity, 'none')
  assert.equal(scoreOf('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:N/I:N/A:N').score, 0)
})

test('los subtotales de la especificación salen con un decimal', () => {
  const full = scoreOf('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H')
  assert.equal(full.exploitability, 3.9)
  assert.equal(full.impact, 5.9)
})

test('el redondeo sube a la décima siguiente y no se deja engañar por la coma flotante', () => {
  assert.equal(roundUp(4), 4)
  assert.equal(roundUp(4.02), 4.1)
  assert.equal(roundUp(4.000000000000001), 4)
  assert.equal(roundUp(5.9), 5.9)
  assert.equal(roundUp(9.89), 9.9)
  assert.equal(roundUp(0), 0)
})

test('la gravedad cambia en los umbrales de la especificación', () => {
  const expected = [[0, 'none'], [0.1, 'low'], [3.9, 'low'], [4, 'medium'], [6.9, 'medium'], [7, 'high'], [8.9, 'high'], [9, 'critical'], [10, 'critical']]
  for (const [score, severity] of expected) assert.equal(severityOf(score), severity, String(score))
})

test('cambiar el alcance cambia los pesos de los privilegios', () => {
  const base = { ...DEFAULT_METRICS, PR: 'L' }
  assert.ok(calculateBaseScore({ ...base, S: 'C' }).score > calculateBaseScore({ ...base, S: 'U' }).score)
})

test('una métrica que falta o un valor inválido se rechaza', () => {
  assert.throws(() => calculateBaseScore({ ...DEFAULT_METRICS, AV: 'X' }), /AV/)
  const { AC, ...incomplete } = DEFAULT_METRICS
  assert.throws(() => calculateBaseScore(incomplete), /AC/)
  assert.throws(() => calculateBaseScore(undefined), /AV/)
})

console.log('vector')

test('el vector se escribe en el orden de la especificación y se lee de vuelta', () => {
  assert.equal(buildVector(DEFAULT_METRICS), 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H')
  const parsed = parseVector('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H')
  assert.deepEqual(parsed, { ok: true, metrics: DEFAULT_METRICS })
})

test('se lee con mayúsculas, espacios y las métricas en otro orden', () => {
  const parsed = parseVector(' cvss:3.1 / a:h/i:h/c:h/s:u/ui:n/pr:n/ac:l/av:n ')
  assert.deepEqual(parsed, { ok: true, metrics: DEFAULT_METRICS })
})

test('cada vector inválido da su motivo', () => {
  assert.deepEqual(parseVector(''), { ok: false, reason: 'format' })
  assert.deepEqual(parseVector(undefined), { ok: false, reason: 'format' })
  assert.deepEqual(parseVector('AV:N/AC:L'), { ok: false, reason: 'format' })
  assert.deepEqual(parseVector('CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'), { ok: false, reason: 'version' })
  assert.deepEqual(parseVector('CVSS:2.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'), { ok: false, reason: 'version' })
  assert.deepEqual(parseVector('CVSS:3.1/AV:N/AC:L'), { ok: false, reason: 'metric' })
  assert.deepEqual(parseVector('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:Z'), { ok: false, reason: 'metric' })
  assert.deepEqual(parseVector('CVSS:3.1/AV:N/AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'), { ok: false, reason: 'metric' })
  assert.deepEqual(parseVector('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:P'), { ok: false, reason: 'metric' })
})

test('todo vector posible se calcula y se lee de vuelta sin perder nada', () => {
  const cartesian = METRICS.reduce((all, { key, values }) => all.flatMap((partial) => values.map((value) => ({ ...partial, [key]: value }))), [{}])
  assert.equal(cartesian.length, 2592)
  for (const metrics of cartesian) {
    const { score } = calculateBaseScore(metrics)
    assert.ok(score >= 0 && score <= 10 && Math.round(score * 10) === score * 10, buildVector(metrics))
    assert.deepEqual(parseVector(buildVector(metrics)).metrics, metrics)
  }
})

test('cada métrica, cada valor, cada gravedad y cada error tienen texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.cvssCalculator
    for (const { key, values } of METRICS) {
      assert.ok(item.metrics[key]?.name && item.metrics[key]?.hint, `${code}: ${key}`)
      for (const value of values) assert.ok(item.metrics[key].values[value], `${code}: ${key}:${value}`)
    }
    for (const severity of SEVERITIES) assert.ok(item.severity[severity], `${code}: ${severity}`)
    for (const reason of ['format', 'version', 'metric']) assert.ok(item.errors[reason], `${code}: error ${reason}`)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
