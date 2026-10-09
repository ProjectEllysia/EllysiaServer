/**
 * Tests de lo que da vida a las páginas públicas: la matemática de las animaciones
 * (`composables/motionMath.js`); los cálculos de los grabados de cada módulo, que salen
 * de fórmulas y datos reales —el sello (`sceneGeometry.js`, `sealPatterns.js`), el
 * cielo de los atlas (`celestial.js`), la luz de Iris (`spectrum.js`) y la carta de
 * Acheron (`cartography.js`), todos en `components/decor/`—; y el registro de módulos
 * que comparten el hub y las herramientas gratuitas (`components/shared/moduleIdentity.js`).
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
  devicePixelInUnits,
  revealScrollDelta,
  seededRandom,
  staggerDelay,
} from '../src/composables/motionMath.js'
import { guillochePath, polarPoint } from '../src/components/decor/sceneGeometry.js'
import { OBLIQUITY, constellationEdges, eclipticPoint, formatDeclination, gappedSegment, graticule, projectCatalog, starRadius, stereographic } from '../src/components/decor/celestial.js'
import { FRAUNHOFER_LINES, rainbowAngle, waterIndex, wavelengthToRgb } from '../src/components/decor/spectrum.js'
import { hachures, lakePoints, meanderPoints, offsetPoints, smoothPath } from '../src/components/decor/cartography.js'
import { SEAL_PATTERNS } from '../src/components/decor/sealPatterns.js'
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

test('un píxel físico se mide en unidades del dibujo según su escala y la densidad de la pantalla', () => {
  assert.equal(devicePixelInUnits(1, 1), 1)
  assert.equal(devicePixelInUnits(2, 1), 0.5, 'un dibujo al doble: medio punto por píxel')
  assert.equal(devicePixelInUnits(1, 2), 0.5, 'una pantalla retina: medio punto por píxel físico')
  assert.equal(devicePixelInUnits(0.5, 0.5), 2, 'una densidad por debajo de 1 cuenta como 1')
  assert.equal(devicePixelInUnits(0), 0, 'sin tamaño todavía, no hay medida')
})

test('lo que ya se ve en una zona cómoda no mueve la página', () => {
  assert.equal(revealScrollDelta({ targetTop: 300, viewportHeight: 800, headerHeight: 72 }), 0)
  assert.equal(revealScrollDelta({ targetTop: 560, viewportHeight: 800, headerHeight: 72 }), 0)
})

test('un resultado que queda abajo sube hasta el 30 % de la ventana', () => {
  assert.equal(revealScrollDelta({ targetTop: 1000, viewportHeight: 800, headerHeight: 72 }), 760)
  assert.equal(revealScrollDelta({ targetTop: 700, viewportHeight: 800, headerHeight: 72 }), 460)
})

test('lo que queda tapado por arriba baja hasta quedar justo bajo la cabecera', () => {
  assert.equal(revealScrollDelta({ targetTop: -400, viewportHeight: 800, headerHeight: 72 }), -488)
  assert.equal(revealScrollDelta({ targetTop: 50, viewportHeight: 800, headerHeight: 72 }), -38)
})

test('en una ventana muy baja, nunca deja el resultado bajo la cabecera', () => {
  assert.equal(revealScrollDelta({ targetTop: 400, viewportHeight: 200, headerHeight: 72 }), 312)
})

console.log('geometría de las escenas')

test('un punto sobre la circunferencia, medido como una esfera de reloj', () => {
  assert.deepEqual(polarPoint(100, 100, 50, 0), { x: 100, y: 50 })
  assert.deepEqual(polarPoint(100, 100, 50, 90), { x: 150, y: 100 })
  assert.deepEqual(polarPoint(100, 100, 50, 180), { x: 100, y: 150 })
  assert.deepEqual(polarPoint(100, 100, 50, 270), { x: 50, y: 100 })
})

test('una curva de guilloché se cierra, da sus ondas y no sale de su banda', () => {
  const path = guillochePath({ centerX: 150, centerY: 150, radius: 100, amplitude: 6, lobes: 12 })
  assert.ok(path.startsWith('M') && path.endsWith('Z'))
  const points = [...path.matchAll(/[ML]([\d.-]+) ([\d.-]+)/g)].map(([, x, y]) => Math.hypot(Number(x) - 150, Number(y) - 150))
  assert.equal(points.length, 12 * 14)
  assert.ok(points.every((distance) => distance >= 93.9 && distance <= 106.1), 'el radio ondula ±6 alrededor de 100')
  assert.notEqual(path, guillochePath({ centerX: 150, centerY: 150, radius: 100, amplitude: 6, lobes: 12, phase: 1 }), 'la fase desplaza la onda')
})

console.log('cielo')

test('la proyección pone el centro de la lámina en su sitio, el norte arriba y el este a la izquierda', () => {
  const project = stereographic({ ra: 230, dec: -20, scale: 1000, x: 600, y: 300 })
  assert.deepEqual(project(230, -20), { x: 600, y: 300 })
  assert.ok(project(230, -10).y < 300, 'más al norte, más arriba')
  assert.ok(project(240, -20).x < 600, 'más ascensión recta, más a la izquierda')
  assert.equal(project(50, 20), null, 'el punto opuesto no se pinta')
})

test('la proyección conserva las distancias cortas: 1° son unos 17,45 px a 1000 px por radián', () => {
  const project = stereographic({ ra: 0, dec: 0, scale: 1000, x: 0, y: 0 })
  assert.ok(Math.abs(project(0, 1).y + 17.45) < 0.05)
})

test('la eclíptica pasa por los equinoccios y baja hasta la inclinación del eje en el solsticio de invierno', () => {
  assert.deepEqual(eclipticPoint(0), { ra: 0, dec: 0 })
  const autumn = eclipticPoint(180)
  assert.ok(Math.abs(autumn.ra - 180) < 1e-9 && Math.abs(autumn.dec) < 1e-9)
  const winter = eclipticPoint(270)
  assert.ok(Math.abs(winter.ra - 270) < 1e-9 && Math.abs(winter.dec + OBLIQUITY) < 1e-9)
})

test('la retícula da un meridiano por media hora y un círculo cada 5°, y marca los mayores', () => {
  const project = stereographic({ ra: 230, dec: -20, scale: 1000, x: 600, y: 300 })
  const lines = graticule(project, { raRange: [210, 255], decRange: [-40, 0] })
  assert.deepEqual(lines.filter((line) => line.kind === 'ra').map((line) => line.value), [210, 217.5, 225, 232.5, 240, 247.5, 255])
  assert.deepEqual(lines.filter((line) => line.kind === 'dec').map((line) => line.value), [-40, -35, -30, -25, -20, -15, -10, -5, 0])
  assert.deepEqual(lines.filter((line) => line.isMajor && line.kind === 'ra').map((line) => line.value), [210, 225, 240, 255])
})

test('las estrellas brillantes se pintan más grandes, y la figura no las toca', () => {
  assert.ok(starRadius(1) > starRadius(3) && starRadius(3) > starRadius(5))
  assert.equal(starRadius(9), 0.7)
  assert.equal(gappedSegment({ x: 0, y: 0 }, { x: 100, y: 0 }, 5, 10), 'M5 0 L90 0')
  assert.equal(gappedSegment({ x: 0, y: 0 }, { x: 10, y: 0 }, 5, 6), '')
})

test('una estrella del otro hemisferio no se pinta, y una figura sin una de sus estrellas pierde solo ese tramo', () => {
  const project = stereographic({ ra: 0, dec: 40, scale: 1000, x: 600, y: 300 })
  const stars = projectCatalog(project, [
    { letter: 'α', ra: 0, dec: 40, magnitude: 2 },
    { letter: 'β', ra: 5, dec: 42, magnitude: 3 },
    { letter: 'γ', ra: 180, dec: -60, magnitude: 1 },
  ])
  assert.deepEqual(stars.map((star) => star.letter), ['α', 'β'])
  assert.equal(stars[0].radius, starRadius(2))
  assert.equal(constellationEdges(stars, [['α', 'β'], ['β', 'γ']]).length, 1)
})

test('las declinaciones se escriben con su signo y el menos tipográfico', () => {
  assert.equal(formatDeclination(40), '+40°')
  assert.equal(formatDeclination(0), '0°')
  assert.equal(formatDeclination(-20), '−20°')
})

console.log('luz')

test('cada longitud de onda tiene su color, y fuera de lo visible no hay luz', () => {
  const [red, green, blue] = wavelengthToRgb(700)
  assert.ok(red > 200 && green === 0 && blue === 0, 'el rojo es rojo')
  assert.equal(wavelengthToRgb(530)[1], 255, 'el verde es verde')
  assert.equal(wavelengthToRgb(460)[2], 255, 'el azul es azul')
  assert.ok(wavelengthToRgb(385)[2] < 255, 'el violeta se apaga en el borde')
  assert.deepEqual(wavelengthToRgb(300), [0, 0, 0])
  assert.deepEqual(wavelengthToRgb(900), [0, 0, 0])
})

test('las líneas de Fraunhofer van del rojo al violeta, todas en lo visible y con su letra', () => {
  const wavelengths = FRAUNHOFER_LINES.map((line) => line.nm)
  assert.deepEqual(wavelengths, [...wavelengths].sort((a, b) => b - a))
  assert.ok(wavelengths.every((nm) => nm > 380 && nm < 780))
  assert.equal(new Set(FRAUNHOFER_LINES.map((line) => line.letter)).size, FRAUNHOFER_LINES.length)
  assert.equal(FRAUNHOFER_LINES.find((line) => line.letter === 'C').nm, 656.28, 'C es la línea roja del hidrógeno')
})

test('el agua desvía más el violeta que el rojo, con sus valores de referencia', () => {
  assert.ok(Math.abs(waterIndex(589.3) - 1.333) < 0.0005, 'en la línea D del sodio, 1,333')
  assert.ok(waterIndex(400) > waterIndex(589.3) && waterIndex(589.3) > waterIndex(700))
})

test('el arco primario está hacia los 42° con el rojo fuera; el secundario, hacia los 51° y al revés', () => {
  const primary = { red: rainbowAngle(700), violet: rainbowAngle(400) }
  const secondary = { red: rainbowAngle(700, 2), violet: rainbowAngle(400, 2) }
  assert.ok(primary.red > 42 && primary.red < 42.6 && primary.violet > 40.4 && primary.violet < 40.8)
  assert.ok(primary.red > primary.violet, 'en el primario, el rojo va por fuera')
  assert.ok(secondary.red > 50 && secondary.red < 50.5 && secondary.violet > 53.3 && secondary.violet < 53.8)
  assert.ok(secondary.violet > secondary.red, 'en el secundario, el orden se invierte')
  assert.ok(Math.abs(rainbowAngle(589.3) - 42.08) < 0.05)
})

console.log('cartografía')

test('un trazo suave empieza y acaba en sus extremos; uno cerrado vuelve al principio', () => {
  const points = [{ x: 0, y: 0 }, { x: 50, y: 20 }, { x: 100, y: 0 }]
  const open = smoothPath(points)
  assert.ok(open.startsWith('M0 0') && open.endsWith('100 0'))
  assert.equal((open.match(/C/g) ?? []).length, 2)
  const closed = smoothPath(points, true)
  assert.ok(closed.endsWith('Z'))
  assert.equal((closed.match(/C/g) ?? []).length, 3)
})

test('un río nace y desemboca donde se le dice, serpentea y es siempre el mismo', () => {
  const options = { amplitude: 20, bends: 4, samples: 30 }
  const first = meanderPoints({ x: 0, y: 0 }, { x: 300, y: 0 }, { ...options, random: seededRandom(7) })
  const second = meanderPoints({ x: 0, y: 0 }, { x: 300, y: 0 }, { ...options, random: seededRandom(7) })
  assert.deepEqual(first, second)
  assert.deepEqual(first[0], { x: 0, y: 0 })
  assert.ok(Math.abs(first.at(-1).x - 300) < 1e-9 && Math.abs(first.at(-1).y) < 1e-9)
  assert.ok(first.some((point) => point.y > 5) && first.some((point) => point.y < -5), 'se aparta a los dos lados')
})

test('las líneas de agua guardan su distancia a la costa, hacia el lado que se pide', () => {
  const coast = [{ x: 0, y: 0 }, { x: 0, y: 50 }, { x: 0, y: 100 }]
  assert.deepEqual(offsetPoints(coast, 10).map((point) => point.x), [10, 10, 10], 'yendo hacia abajo, la izquierda es el este')
  assert.deepEqual(offsetPoints(coast, -10).map((point) => point.x), [-10, -10, -10])
})

test('un lago se encoge hacia dentro para sus líneas de agua', () => {
  const shape = { centerX: 0, centerY: 0, radius: 50, harmonics: [[3, 5, 0]] }
  const shore = lakePoints(shape)
  const inner = lakePoints({ ...shape, inset: 10 })
  shore.forEach((point, index) => assert.ok(Math.abs(Math.hypot(point.x, point.y) - Math.hypot(inner[index].x, inner[index].y) - 10) < 1e-9))
})

test('el relieve se sombrea a las dos vertientes, más largo en la umbría y más corto en los extremos', () => {
  const ridge = [{ x: 0, y: 0 }, { x: 100, y: 0 }]
  const strokes = hachures(ridge, { spacing: 10, length: 20, random: () => 1 })
  assert.equal(strokes.length, 20)
  const drops = strokes.map((stroke) => {
    const [, , fromY, , toY] = stroke.match(/M([\d.-]+) ([\d.-]+) L([\d.-]+) ([\d.-]+)/).map(Number)
    return toY - fromY
  })
  const shade = drops.filter((_, index) => index % 2 === 0)
  const light = drops.filter((_, index) => index % 2 === 1)
  assert.ok(shade.every((value) => value >= 0) && light.every((value) => value <= 0), 'umbría hacia abajo, solana hacia arriba')
  assert.ok(Math.max(...shade) > -Math.min(...light))
  assert.ok(shade[5] > shade[0], 'el centro de la sierra es más alto que sus extremos')
  assert.equal(hachures(ridge, { spacing: 10, length: 20, random: () => 1, backSlope: 0 }).length, 10)
})

test('cada módulo tiene su sello, con ondas enteras y un dibujo distinto al de los demás', () => {
  assert.deepEqual(Object.keys(SEAL_PATTERNS).sort(), [...MODULE_IDS].sort())
  const signatures = Object.values(SEAL_PATTERNS).map((pattern) => {
    assert.ok(Object.values(pattern).every(Number.isInteger))
    return JSON.stringify(pattern)
  })
  assert.equal(new Set(signatures).size, signatures.length)
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

/**
 * Reglas CSS de un componente de la decoración, una por bloque `selector { ... }`.
 *
 * @param {string} path - Ruta del componente, relativa a la raíz del SPA.
 * @returns {string[]} El texto de cada regla de su bloque `<style>`.
 */
const decorRules = (path) => (read(path).split('<style')[1] ?? '').split('}').map((rule) => rule.trim()).filter(Boolean)
const DECOR_COMPONENTS = [
  'src/components/decor/StarChart.vue',
  'src/components/decor/EmblemSeal.vue',
  'src/components/decor/ToolGlyph.vue',
  'src/components/decor/Frieze.vue',
  'src/components/decor/ModuleAtmosphere.vue',
  ...MODULE_IDS.map((id) => `src/components/decor/scenes/${id.charAt(0).toUpperCase()}${id.slice(1)}Scene.vue`),
  'src/components/shared/StarBackground.vue',
]

test('nada que se anime sin parar lleva un filtro: se recalcularía en cada fotograma', () => {
  for (const path of DECOR_COMPONENTS) {
    for (const rule of decorRules(path)) {
      if (/animation[^;]*infinite/.test(rule)) assert.doesNotMatch(rule, /filter\s*:/, `${path}: ${rule.split('{')[0].trim()}`)
    }
  }
})

test('ninguna animación mueve la posición de un fondo: se mueve una capa con transform', () => {
  const keyframes = /@keyframes\s+[\w-]+\s*\{((?:[^{}]*\{[^{}]*\})*)[^{}]*\}/g
  for (const path of DECOR_COMPONENTS) {
    for (const [, body] of read(path).matchAll(keyframes)) assert.doesNotMatch(body, /background-position/, path)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
