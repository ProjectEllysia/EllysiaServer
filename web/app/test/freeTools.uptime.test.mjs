/**
 * Tests de la calculadora de disponibilidad gratuita
 * (`src/components/freeTools/uptime.js`).
 *
 * Node puro, sin framework. Las cuentas se comprueban a mano: un 99,9 % deja caer
 * un 0,1 % de un año de 365,25 días, 31.557,6 segundos.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  PERIOD_SECONDS,
  SLA_PRESETS,
  allowedDowntime,
  availabilityFor,
  durationParts,
  parseSla,
} from '../src/components/freeTools/uptime.js'

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

const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} ≠ ${expected}`)

console.log('lectura')

test('la disponibilidad se lee con coma, con punto y con el signo de porcentaje', () => {
  assert.equal(parseSla('99,9'), 99.9)
  assert.equal(parseSla('99.95 %'), 99.95)
  assert.equal(parseSla('100'), 100)
  assert.equal(parseSla('0'), 0)
  for (const wrong of ['', 'mucho', '100.1', '-1', undefined, null]) assert.equal(parseSla(wrong), null, String(wrong))
})

console.log('de disponibilidad a caída')

test('un 99,9 % deja 86,4 s al día y 31.557,6 s (8 h 45 min 58 s) al año', () => {
  const downtime = allowedDowntime(99.9)
  close(downtime.day, 86.4, 'día')
  close(downtime.week, 604.8, 'semana')
  close(downtime.year, 31557.6, 'año')
  close(downtime.month, 31557.6 / 12, 'mes')
  close(downtime.quarter, 31557.6 / 4, 'trimestre')
  assert.deepEqual(durationParts(downtime.year), [{ unit: 'hour', value: 8 }, { unit: 'minute', value: 45 }, { unit: 'second', value: 58 }])
})

test('el 100 % no permite ninguna caída, y el 0 %, el periodo entero', () => {
  for (const seconds of Object.values(allowedDowntime(100))) assert.equal(seconds, 0)
  assert.deepEqual(allowedDowntime(0), { ...PERIOD_SECONDS })
})

test('cada disponibilidad habitual es válida y permite menos caída que la anterior', () => {
  let previous = Infinity
  for (const sla of SLA_PRESETS) {
    assert.equal(parseSla(String(sla)), sla)
    assert.ok(allowedDowntime(sla).year < previous, String(sla))
    previous = allowedDowntime(sla).year
  }
})

console.log('de caída a disponibilidad')

test('43 minutos y medio en un mes dejan casi un 99,9 %', () => {
  close(availabilityFor('43,83', 'month'), 100 * (1 - (43.83 * 60) / PERIOD_SECONDS.month), 'mes')
  assert.ok(Math.abs(availabilityFor('43.83', 'month') - 99.9) < 0.001)
  assert.equal(availabilityFor('0', 'day'), 100)
  assert.equal(availabilityFor('1440', 'day'), 0)
})

test('una caída negativa, más larga que el periodo o en un periodo desconocido no da resultado', () => {
  assert.equal(availabilityFor('-1', 'day'), null)
  assert.equal(availabilityFor('1441', 'day'), null)
  assert.equal(availabilityFor('abc', 'day'), null)
  assert.equal(availabilityFor('10', 'decade'), null)
})

console.log('duraciones')

test('una duración se parte en sus unidades y se saltan las que son cero', () => {
  assert.deepEqual(durationParts(90061), [{ unit: 'day', value: 1 }, { unit: 'hour', value: 1 }, { unit: 'minute', value: 1 }, { unit: 'second', value: 1 }])
  assert.deepEqual(durationParts(3600), [{ unit: 'hour', value: 1 }])
  assert.deepEqual(durationParts(604.8), [{ unit: 'minute', value: 10 }, { unit: 'second', value: 5 }])
})

test('por debajo de diez segundos quedan los decimales, y sin caída sale «0 s»', () => {
  assert.deepEqual(durationParts(0.864), [{ unit: 'second', value: 0.86 }])
  assert.deepEqual(durationParts(0), [{ unit: 'second', value: 0 }])
  assert.deepEqual(durationParts(-1), [])
  assert.deepEqual(durationParts(NaN), [])
})

test('cada periodo y unidad tiene texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.uptimeCalculator
    for (const period of Object.keys(PERIOD_SECONDS)) assert.ok(item.periods[period], `${code}: ${period}`)
    for (const unit of ['day', 'hour', 'minute', 'second']) assert.ok(item.units[unit], `${code}: ${unit}`)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
