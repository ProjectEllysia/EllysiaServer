/**
 * Tests del estimador del medidor de contraseñas gratuito
 * (`src/components/freeTools/passwordStrength.js`).
 *
 * Node puro, sin framework. Se fija que el estimador castiga lo que un atacante
 * prueba primero y no lo que parece complicado, y que la consulta de filtraciones
 * no manda nunca más que cinco caracteres del hash.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  CRACK_UNITS,
  WEAKNESS_CODES,
  alphabetOf,
  countInBreaches,
  crackScalePosition,
  crackSeconds,
  crackTimeParts,
  estimateStrength,
  pwnedCount,
  sha1Hex,
  splitHashForRange,
} from '../src/components/freeTools/passwordStrength.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const locales = ['es', 'en'].map((code) => [code, JSON.parse(readFileSync(`${appRoot}src/i18n/locales/${code}.json`, 'utf-8'))])

let failures = 0
function test(name, fn) {
  const finish = (error) => {
    if (!error) return console.log(`  ✓ ${name}`)
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
  try {
    const result = fn()
    if (result?.then) return result.then(() => finish(), finish)
    finish()
  } catch (error) {
    finish(error)
  }
}

console.log('medidor de contraseñas')

test('una cadena vacía no tiene fuerza ni hallazgos', () => {
  assert.deepEqual(estimateStrength(''), { length: 0, bits: 0, level: 0, weaknesses: [] })
  assert.deepEqual(estimateStrength(undefined), { length: 0, bits: 0, level: 0, weaknesses: [] })
})

test('el alfabeto suma los tipos de carácter que aparecen', () => {
  assert.deepEqual(alphabetOf('abc'), { size: 26, kinds: 1 })
  assert.deepEqual(alphabetOf('aB3'), { size: 62, kinds: 3 })
  assert.deepEqual(alphabetOf('aB3!'), { size: 95, kinds: 4 })
  assert.deepEqual(alphabetOf('añ'), { size: 126, kinds: 2 })
})

test('las contraseñas de siempre salen muy débiles aunque parezcan largas o variadas', () => {
  for (const weak of ['password', 'P@ssw0rd', 'Password123!', 'qwertyuiop', '12345678', 'abcdefgh', 'aaaaaaaaaaaa', 'Madrid2024']) {
    assert.ok(estimateStrength(weak).level <= 1, `${weak}: ${JSON.stringify(estimateStrength(weak))}`)
  }
})

test('una contraseña larga y al azar sale fuerte', () => {
  assert.equal(estimateStrength('k7#Qm2vX9$tLw4Rz!Nb8').level, 4)
  assert.ok(estimateStrength('k7#Qm2vX9$tLw4Rz!Nb8').bits >= 100)
})

test('más longitud y más variedad nunca bajan la estimación', () => {
  const ladder = ['k7', 'k7#Q', 'k7#Qm2vX', 'k7#Qm2vX9$tL', 'k7#Qm2vX9$tLw4Rz']
  const bits = ladder.map((password) => estimateStrength(password).bits)
  assert.deepEqual([...bits].sort((a, b) => a - b), bits)
})

test('cada patrón se señala con su código', () => {
  const cases = { password: 'commonWord', 'xK3abcdef9': 'sequence', 'xK3vvvvvv9': 'repeat', 'xK3asdfgh9': 'keyboard', 'xK3mnb2024': 'year', abcdefghijkl: 'oneKind' }
  for (const [password, code] of Object.entries(cases)) {
    assert.ok(estimateStrength(password).weaknesses.includes(code), `${password} → ${code}: ${estimateStrength(password).weaknesses}`)
  }
  assert.ok(estimateStrength('k7#Qm2').weaknesses.includes('short'))
  assert.deepEqual(estimateStrength('k7#Qm2vX9$tLw4Rz!Nb8').weaknesses, [])
})

test('una repetición de bloque cuesta casi lo que el bloque', () => {
  assert.ok(estimateStrength('xK3mQ9xK3mQ9').bits < estimateStrength('xK3mQ9yT5nR2').bits - 15)
})

test('el tiempo para dar con la contraseña crece con los bits', () => {
  assert.equal(crackSeconds(0), 0)
  assert.ok(crackSeconds(40) < crackSeconds(60))
  assert.ok(crackSeconds(30) < 1)
  assert.ok(crackSeconds(120) > 3.15e9 * 100)
})

test('el tiempo se expresa en una unidad redonda, y lo muy largo sin número', () => {
  assert.deepEqual(crackTimeParts(0.2), { unit: 'instant', value: null })
  assert.deepEqual(crackTimeParts(30), { unit: 'seconds', value: 30 })
  assert.deepEqual(crackTimeParts(600), { unit: 'minutes', value: 10 })
  assert.deepEqual(crackTimeParts(7200), { unit: 'hours', value: 2 })
  assert.deepEqual(crackTimeParts(86400 * 3), { unit: 'days', value: 3 })
  assert.deepEqual(crackTimeParts(86400 * 90), { unit: 'months', value: 3 })
  assert.deepEqual(crackTimeParts(86400 * 365 * 5), { unit: 'years', value: 5 })
  assert.deepEqual(crackTimeParts(86400 * 365 * 500), { unit: 'centuries', value: null })
  assert.deepEqual(crackTimeParts(Infinity), { unit: 'centuries', value: null })
})

test('la posición en la escala va de 0 a 1 y no se sale', () => {
  assert.equal(crackScalePosition(0), 0)
  assert.equal(crackScalePosition(1), 0)
  assert.ok(crackScalePosition(1e6) > crackScalePosition(1e3))
  assert.equal(crackScalePosition(1e15), 1)
})

test('cada hallazgo y cada unidad de tiempo tienen texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.passwordStrength
    for (const weakness of WEAKNESS_CODES) assert.ok(item.weaknesses[weakness], `${code}: hallazgo ${weakness}`)
    for (const unit of CRACK_UNITS) assert.ok(item.units[unit], `${code}: unidad ${unit}`)
    for (const level of [0, 1, 2, 3, 4]) assert.ok(item.levels[level], `${code}: nivel ${level}`)
  }
})

console.log('filtraciones')

test('el hash se parte en el prefijo que sale y el sufijo que se queda', () => {
  const { prefix, suffix } = splitHashForRange('5baa61e4c9b93f3f0682250b6cf8331b7ee68fd8')
  assert.equal(prefix, '5BAA6')
  assert.equal(suffix, '1E4C9B93F3F0682250B6CF8331B7EE68FD8')
  assert.equal(prefix.length + suffix.length, 40)
})

test('la respuesta se lee línea a línea y se busca solo el sufijo', () => {
  const body = 'AAA:3\r\n1E4C9B93F3F0682250B6CF8331B7EE68FD8:9545824\r\nZZZ:0'
  assert.equal(pwnedCount(body, '1E4C9B93F3F0682250B6CF8331B7EE68FD8'), 9545824)
  assert.equal(pwnedCount(body, 'NOESTA'), 0)
  assert.equal(pwnedCount('', 'X'), 0)
})

await test('SHA-1 coincide con el valor conocido de «password»', async () => {
  assert.equal(await sha1Hex('password'), '5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8')
})

await test('la consulta manda solo el prefijo, nunca la contraseña, y devuelve las veces', async () => {
  const requested = []
  const fakeFetch = async (url, options) => {
    requested.push({ url, options })
    return { ok: true, text: async () => '1E4C9B93F3F0682250B6CF8331B7EE68FD8:42\n0000000000000000000000000000000000A:1' }
  }
  const count = await countInBreaches('password', fakeFetch)
  assert.equal(count, 42)
  assert.equal(requested.length, 1)
  assert.equal(requested[0].url, 'https://api.pwnedpasswords.com/range/5BAA6')
  assert.ok(!new URL(requested[0].url).pathname.toLowerCase().includes('password'))
  assert.equal(requested[0].options.headers['Add-Padding'], 'true')
})

await test('si el servicio falla, se lanza y no se da por «no aparece»', async () => {
  await assert.rejects(() => countInBreaches('password', async () => ({ ok: false, status: 503, text: async () => '' })), /503/)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
