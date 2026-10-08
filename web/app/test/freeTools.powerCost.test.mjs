/**
 * Tests de la calculadora de consumo eléctrico gratuita
 * (`src/components/freeTools/powerCost.js`).
 *
 * Node puro, sin framework. Las cuentas se comprueban a mano: 150 W durante
 * 24 horas son 3,6 kWh al día.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  DEFAULT_INPUTS,
  FIELD_LIMITS,
  POWER_PRESETS,
  calculatePowerCost,
  inputsToQuery,
  parseDecimal,
  parseInputs,
  queryToInputs,
} from '../src/components/freeTools/powerCost.js'

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

const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-9, `${message}: ${actual} ≠ ${expected}`)
const defaults = () => parseInputs(DEFAULT_INPUTS).values

console.log('lectura')

test('los números se leen con coma o con punto y sin espacios', () => {
  assert.equal(parseDecimal('0,15'), 0.15)
  assert.equal(parseDecimal(' 1 200 '), 1200)
  assert.equal(parseDecimal('3.5'), 3.5)
  assert.equal(parseDecimal(7), 7)
  for (const wrong of ['', '  ', 'abc', '1,2,3', undefined, null, NaN, Infinity]) assert.equal(parseDecimal(wrong), null, String(wrong))
})

test('los valores de partida son válidos', () => {
  const { values, invalid } = parseInputs(DEFAULT_INPUTS)
  assert.deepEqual(invalid, [])
  assert.deepEqual(values, { watts: 150, hoursPerDay: 24, devices: 1, pricePerKwh: 0.15, emissionFactor: 0.15, pue: 1 })
})

test('cada campo fuera de rango, vacío o no entero se señala', () => {
  const invalidFields = (changes) => parseInputs({ ...DEFAULT_INPUTS, ...changes }).invalid
  assert.deepEqual(invalidFields({ watts: '-1' }), ['watts'])
  assert.deepEqual(invalidFields({ watts: '100001' }), ['watts'])
  assert.deepEqual(invalidFields({ hoursPerDay: '25' }), ['hoursPerDay'])
  assert.deepEqual(invalidFields({ devices: '0' }), ['devices'])
  assert.deepEqual(invalidFields({ devices: '2,5' }), ['devices'])
  assert.deepEqual(invalidFields({ pue: '0.9' }), ['pue'])
  assert.deepEqual(invalidFields({ pricePerKwh: '' }), ['pricePerKwh'])
  assert.deepEqual(invalidFields({ emissionFactor: 'mucho' }), ['emissionFactor'])
  assert.deepEqual(invalidFields({ watts: 'x', devices: '-3' }), ['watts', 'devices'])
  assert.equal(parseInputs({ ...DEFAULT_INPUTS, watts: 'x' }).values, null)
})

test('los límites se pueden alcanzar exactamente', () => {
  assert.deepEqual(parseInputs({ ...DEFAULT_INPUTS, watts: '0', hoursPerDay: '0', devices: '1', pue: '1' }).invalid, [])
  assert.deepEqual(parseInputs({ watts: '100000', hoursPerDay: '24', devices: '100000', pricePerKwh: '10', emissionFactor: '2', pue: '3' }).invalid, [])
})

console.log('cálculo')

test('150 W durante 24 h son 3,6 kWh al día, 1.314 al año y 197,10 € al año', () => {
  const result = calculatePowerCost(defaults())
  close(result.kwh.day, 3.6, 'kWh/día')
  close(result.kwh.year, 1314, 'kWh/año')
  close(result.kwh.month, 1314 / 12, 'kWh/mes')
  close(result.cost.day, 0.54, '€/día')
  close(result.cost.year, 197.1, '€/año')
  close(result.co2Year, 197.1, 'kg CO₂/año')
})

test('los equipos y el PUE multiplican, y las horas escalan', () => {
  const base = calculatePowerCost(defaults())
  close(calculatePowerCost({ ...defaults(), devices: 10 }).kwh.year, base.kwh.year * 10, 'diez equipos')
  close(calculatePowerCost({ ...defaults(), pue: 1.5 }).cost.year, base.cost.year * 1.5, 'PUE 1,5')
  close(calculatePowerCost({ ...defaults(), hoursPerDay: 12 }).kwh.day, base.kwh.day / 2, 'doce horas')
})

test('sin potencia o sin horas no hay consumo ni coste', () => {
  for (const changes of [{ watts: 0 }, { hoursPerDay: 0 }]) {
    const result = calculatePowerCost({ ...defaults(), ...changes })
    assert.deepEqual([result.kwh.year, result.cost.year, result.co2Year], [0, 0, 0])
  }
})

console.log('enlace')

test('solo viaja lo que no vale lo de por defecto', () => {
  assert.deepEqual(inputsToQuery(DEFAULT_INPUTS), {})
  assert.deepEqual(inputsToQuery({ ...DEFAULT_INPUTS, watts: ' 600 ', devices: '4' }), { w: '600', n: '4' })
})

test('la URL se lee campo a campo y lo inválido vuelve al valor por defecto', () => {
  assert.deepEqual(queryToInputs({ w: '600', n: '4', p: '0,2' }), { ...DEFAULT_INPUTS, watts: '600', devices: '4', pricePerKwh: '0,2' })
  assert.deepEqual(queryToInputs({ w: 'abc', h: '99', n: '1.5', u: ['1'] }), { ...DEFAULT_INPUTS })
  assert.deepEqual(queryToInputs(undefined), { ...DEFAULT_INPUTS })
})

test('lo que va a la URL vuelve igual', () => {
  const inputs = { ...DEFAULT_INPUTS, watts: '45', hoursPerDay: '8', pue: '1.5' }
  assert.deepEqual(queryToInputs(inputsToQuery(inputs)), inputs)
})

test('cada potencia típica, campo y error tienen texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.powerCost
    for (const preset of POWER_PRESETS) assert.ok(item.presets[preset.id], `${code}: ${preset.id}`)
    for (const field of Object.keys(FIELD_LIMITS)) assert.ok(item.fields[field]?.label, `${code}: ${field}`)
    assert.ok(item.errors.range && item.errors.integer, `${code}: errores`)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
