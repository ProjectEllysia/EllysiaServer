/**
 * Tests de lo que da vida a las páginas públicas: la matemática de las animaciones
 * (`composables/motionMath.js`), la geometría de las escenas mitológicas
 * (`components/decor/sceneGeometry.js`) y el registro de módulos que comparten el hub
 * y las herramientas gratuitas (`components/shared/moduleIdentity.js`).
 *
 * Node puro, sin framework. Lo importante del registro es que nada de lo que el pie de
 * una herramienta presenta —lema, capacidades, escena, grabado— puede faltar sin que
 * esto falle.
 */

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  SCRAMBLE_ALPHABET,
  clamp01,
  countUpValue,
  easeOutCubic,
  lerp,
  roundTo,
  scrambleFrame,
  seededRandom,
  staggerDelay,
} from '../src/composables/motionMath.js'
import { leavesAlongArc, polarPoint, snakePath, wavePath } from '../src/components/decor/sceneGeometry.js'
import { HUB_COPY_KEYS, HUB_FEATURE_IDS, MODULE_IDENTITY, MODULE_IDS } from '../src/components/shared/moduleIdentity.js'
import { FREE_TOOLS } from '../src/freeTools/catalog.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const read = (path) => readFileSync(appRoot + path, 'utf-8').replace(/\r\n/g, '\n')
const locales = ['es', 'en'].map((code) => [code, JSON.parse(read(`src/i18n/locales/${code}.json`))])
const resolveKey = (dictionary, key) => key.split('.').reduce((node, part) => node?.[part], dictionary)

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

console.log('movimiento')

test('el avance se lleva siempre a [0, 1]', () => {
  assert.equal(clamp01(-3), 0)
  assert.equal(clamp01(0.4), 0.4)
  assert.equal(clamp01(7), 1)
  assert.equal(clamp01(Number.NaN), 0)
  assert.equal(clamp01(undefined), 0)
})

test('la curva de frenado va de 0 a 1, sube siempre y empieza rápido', () => {
  assert.equal(easeOutCubic(0), 0)
  assert.equal(easeOutCubic(1), 1)
  assert.ok(easeOutCubic(0.5) > 0.5, 'a mitad de tiempo ya pasó de la mitad')
  let previous = 0
  for (let step = 1; step <= 20; step += 1) {
    const value = easeOutCubic(step / 20)
    assert.ok(value >= previous)
    previous = value
  }
})

test('interpolar y redondear', () => {
  assert.equal(lerp(10, 20, 0), 10)
  assert.equal(lerp(10, 20, 1), 20)
  assert.equal(lerp(10, 20, 0.25), 12.5)
  assert.equal(roundTo(3.14159, 2), 3.14)
  assert.equal(roundTo(2.5, 0), 3)
})

test('el contador termina exactamente en su valor, sube y baja, y respeta los decimales', () => {
  assert.equal(countUpValue(0, 9.8, 1, 1), 9.8)
  assert.equal(countUpValue(0, 9.8, 2, 1), 9.8)
  assert.equal(countUpValue(0, 100, 0), 0)
  assert.ok(countUpValue(0, 100, 0.3) > 30 && countUpValue(0, 100, 0.3) < 100)
  assert.ok(countUpValue(100, 0, 0.5) < 100 && countUpValue(100, 0, 0.5) > 0)
  assert.equal(countUpValue(0, 1, 0.5, 1) * 10 % 1, 0)
})

test('el texto se descifra de izquierda a derecha', () => {
  const target = 'Ab3$kQ9!'
  const alwaysFirst = () => 0
  assert.equal(scrambleFrame(target, 1), target)
  assert.equal(scrambleFrame(target, 0, alwaysFirst), SCRAMBLE_ALPHABET[0].repeat(target.length))
  const middle = scrambleFrame(target, 0.6, alwaysFirst)
  assert.equal(middle.length, target.length)
  assert.equal(middle[0], target[0], 'el primer carácter se fija pronto')
  assert.notEqual(middle[target.length - 1], target[target.length - 1], 'el último tarda más')
  let settled = 0
  for (let step = 0; step <= 10; step += 1) {
    const frame = scrambleFrame(target, step / 10, alwaysFirst)
    const count = [...frame].filter((character, index) => character === target[index]).length
    assert.ok(count >= settled, 'nunca se «desfija» un carácter')
    settled = count
  }
})

test('los espacios no se barajan y el alfabeto no tiene caracteres confusos', () => {
  assert.equal(scrambleFrame('a b', 0.1, () => 0.5)[1], ' ')
  assert.doesNotMatch(SCRAMBLE_ALPHABET, /[0O1lI]/)
})

test('la entrada escalonada crece con la posición y tiene tope', () => {
  assert.equal(staggerDelay(0), 0)
  assert.equal(staggerDelay(3, 100), 300)
  assert.equal(staggerDelay(50, 100, 640), 640)
  assert.equal(staggerDelay(-2), 0)
})

test('el azar con semilla es siempre el mismo y queda en [0, 1)', () => {
  const first = seededRandom(404)
  const second = seededRandom(404)
  const values = Array.from({ length: 50 }, () => first())
  assert.deepEqual(values, Array.from({ length: 50 }, () => second()))
  assert.ok(values.every((value) => value >= 0 && value < 1))
  assert.notDeepEqual(values, Array.from({ length: 50 }, ((generator) => () => generator())(seededRandom(405))))
  assert.ok(new Set(values).size > 45)
})

console.log('geometría de las escenas')

test('un punto sobre la circunferencia, medido como una esfera de reloj', () => {
  assert.deepEqual(polarPoint(100, 100, 50, 0), { x: 100, y: 50 })
  assert.deepEqual(polarPoint(100, 100, 50, 90), { x: 150, y: 100 })
  assert.deepEqual(polarPoint(100, 100, 50, 180), { x: 100, y: 150 })
  assert.deepEqual(polarPoint(100, 100, 50, 270), { x: 50, y: 100 })
})

test('las hojas de una corona van de dos en dos, a medio largo del tallo y bien orientadas', () => {
  const options = { centerX: 0, centerY: 0, radius: 100, from: 20, to: 160, pairs: 5, length: 20 }
  const leaves = leavesAlongArc(options)
  assert.equal(leaves.length, 10)
  assert.deepEqual([...new Set(leaves.map((leaf) => leaf.index))], [0, 1, 2, 3, 4])
  for (const leaf of leaves) {
    const distance = Math.hypot(leaf.x, leaf.y)
    assert.ok(leaf.side === 'out' ? distance > 100 : distance < 100, `${leaf.side}: ${distance}`)
    assert.ok(Math.abs(distance - 100) <= 11, 'la hoja queda pegada al tallo')
  }
  const out = leaves.find((leaf) => leaf.side === 'out' && leaf.index === 0)
  const inside = leaves.find((leaf) => leaf.side === 'in' && leaf.index === 0)
  assert.equal(out.rotation, 20 - 38)
  assert.equal(inside.rotation, 20 + 38)
})

test('una onda empieza donde se le dice, ocupa todo el ancho y ondula', () => {
  const path = wavePath(300, 20, 400, 1200)
  assert.ok(path.startsWith('M0 300 Q100 280 200 300'))
  assert.equal((path.match(/T/g) ?? []).length, 5)
  assert.ok(path.endsWith('T1200 300'))
})

test('una serpiente sube con un tramo por ondulación y acaba a su largo', () => {
  const path = snakePath(90, 10, 3)
  assert.equal((path.match(/C/g) ?? []).length, 3)
  assert.ok(path.endsWith('0 -90'))
  assert.ok(path.includes('10 ') && path.includes('-10 '), 'ondula a los dos lados')
})

console.log('registro de módulos')

test('hay cinco módulos y cada uno tiene identidad, textos y capacidades', () => {
  assert.deepEqual([...MODULE_IDS].sort(), ['acheron', 'aegis', 'hygeia', 'iris', 'themis'])
  for (const id of MODULE_IDS) {
    assert.ok(MODULE_IDENTITY[id].name && MODULE_IDENTITY[id].numeral && MODULE_IDENTITY[id].epigraph, id)
    assert.equal(MODULE_IDENTITY[id].route, `/${id}`)
    assert.ok(HUB_FEATURE_IDS[id].length >= 3, `${id} necesita tres capacidades para el pie de las herramientas`)
    assert.deepEqual(Object.keys(HUB_COPY_KEYS[id]).sort(), ['claim', 'myth', 'tagline'])
  }
})

test('el panteón sigue su orden y los números romanos no se repiten', () => {
  assert.deepEqual(MODULE_IDS.map((id) => MODULE_IDENTITY[id].numeral), ['I', 'II', 'III', 'IV', 'V'])
})

for (const [code, dictionary] of locales) {
  test(`${code}: el lema, la frase mítica, la bajada y cada capacidad de cada hub existen en el diccionario`, () => {
    for (const id of MODULE_IDS) {
      for (const [kind, key] of Object.entries(HUB_COPY_KEYS[id])) assert.equal(typeof resolveKey(dictionary, key), 'string', `${id}.${kind} → ${key}`)
      for (const feature of HUB_FEATURE_IDS[id]) {
        for (const part of ['kicker', 'title', 'desc']) {
          assert.equal(typeof resolveKey(dictionary, `${id}Hub.features.${feature}.${part}`), 'string', `${id}Hub.features.${feature}.${part}`)
        }
      }
    }
  })
}

test('cada módulo tiene su escena mitológica', () => {
  for (const id of MODULE_IDS) {
    const name = id.charAt(0).toUpperCase() + id.slice(1)
    assert.ok(existsSync(`${appRoot}src/components/decor/scenes/${name}Scene.vue`), `falta la escena de ${id}`)
  }
})

test('cada herramienta gratuita tiene su grabado en el medallón', () => {
  const glyph = read('src/components/decor/ToolGlyph.vue')
  for (const tool of FREE_TOOLS) assert.ok(glyph.includes(`toolId === '${tool.id}'`), `falta el grabado de ${tool.id}`)
})

test('los cinco hubs leen su lema y sus capacidades del registro, sin repetirlos', () => {
  for (const id of MODULE_IDS) {
    const hub = read(`src/views/${id}/${id.charAt(0).toUpperCase()}${id.slice(1)}HubView.vue`)
    assert.ok(hub.includes(`HUB_COPY_KEYS.${id}.claim`), `${id}: lema`)
    assert.ok(hub.includes(`HUB_FEATURE_IDS.${id}`), `${id}: capacidades`)
  }
})

test('las animaciones respetan el movimiento reducido', () => {
  const css = read('src/assets/css/motion.css')
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
  for (const selector of ['.mo-rise', '.mo-mask-inner', '.reveal', '.atmosphere', '.tool-glyph']) assert.ok(css.includes(selector), selector)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
