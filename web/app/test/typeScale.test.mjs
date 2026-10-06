/**
 * Tests de la escala tipográfica de `src/assets/css/shared.css`.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`. Lee el
 * CSS como texto.
 *
 * La escala se degrada sin que nada avise: alguien baja un token «un poco»
 * para que quepa una etiqueta, o escribe `font-size: 11px` en un componente,
 * y la letra pequeña vuelve a ser ilegible o a separarse demasiado de la de
 * al lado. Estas tres reglas lo impiden:
 *   - ningún token de texto baja de 12px, ni en móvil;
 *   - entre dos escalones de texto consecutivos el salto queda entre 1,05 y
 *     1,25, en móvil y en escritorio: ni dos tamaños indistinguibles ni un
 *     abismo entre una etiqueta y su texto;
 *   - ningún componente escribe un tamaño en `rem` o `px`: usa un token. Los
 *     tamaños en `em` sí valen, porque son relativos al texto que los rodea
 *     (el código en línea dentro de un párrafo, por ejemplo).
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const sharedCss = readFileSync(join(sourceRoot, 'assets/css/shared.css'), 'utf-8')

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

/** Píxeles por rem del navegador. */
const ROOT_PX = 16

/**
 * Los escalones de texto, en orden. Los de titular (`2xl` en adelante y la
 * cifra grande de Iris) quedan fuera de la regla de saltos a propósito: un
 * titular tiene que saltar.
 */
const TEXT_STEPS = ['xs', 'sm', 'body', 'md', 'lg', 'xl']

/** Tamaño mínimo legible de cualquier escalón de texto, en píxeles. */
const MIN_PX = 12

/** Salto permitido entre dos escalones de texto consecutivos. */
const MIN_RATIO = 1.05
const MAX_RATIO = 1.25

/**
 * Lee un token `--fs-<nombre>` y devuelve sus extremos.
 *
 * @param {string} name - Nombre del escalón (`'sm'`).
 * @returns {{ min: number, max: number }} Tamaño en móvil y en escritorio, en píxeles.
 */
function readStep(name) {
  const match = sharedCss.match(new RegExp(`--fs-${name}:\\s*calc\\(var\\(--fs-scale\\) \\* clamp\\(([0-9.]+)rem,[^,]+,\\s*([0-9.]+)rem\\)\\)`))
  assert.ok(match, `no se encuentra --fs-${name} con la forma calc(var(--fs-scale) * clamp(…rem, …, …rem))`)
  return { min: Number(match[1]) * ROOT_PX, max: Number(match[2]) * ROOT_PX }
}

/**
 * Recorre `src/` y devuelve los `.vue` y `.css`.
 *
 * @param {string} directory - Directorio desde el que empezar.
 * @returns {string[]} Rutas absolutas.
 */
function listStyleFiles(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) return listStyleFiles(path)
    return /\.(vue|css)$/.test(name) ? [path] : []
  })
}

const steps = Object.fromEntries(TEXT_STEPS.map((name) => [name, readStep(name)]))

console.log('typeScale')

test(`ningún escalón de texto baja de ${MIN_PX}px`, () => {
  const tooSmall = TEXT_STEPS.filter((name) => steps[name].min < MIN_PX).map((name) => `${name} (${steps[name].min}px)`)
  assert.deepEqual(tooSmall, [])
})

for (const edge of ['min', 'max']) {
  test(`los saltos entre escalones quedan entre ${MIN_RATIO} y ${MAX_RATIO} (${edge === 'min' ? 'móvil' : 'escritorio'})`, () => {
    const outOfRange = TEXT_STEPS.slice(1)
      .map((name, index) => [TEXT_STEPS[index], name, steps[name][edge] / steps[TEXT_STEPS[index]][edge]])
      .filter(([, , ratio]) => ratio < MIN_RATIO || ratio > MAX_RATIO)
      .map(([from, to, ratio]) => `${from}→${to}: ${ratio.toFixed(2)}`)
    assert.deepEqual(outOfRange, [])
  })
}

test('ningún componente escribe un tamaño de letra en rem o px', () => {
  const offenders = listStyleFiles(sourceRoot)
    .filter((path) => !path.endsWith('shared.css'))
    .flatMap((path) => readFileSync(path, 'utf-8').split('\n')
      .map((line, index) => [line, index + 1])
      .filter(([line]) => /font-size:\s*[0-9.]+(rem|px)\b/.test(line))
      .map(([line, number]) => `${relative(sourceRoot, path)}:${number}: ${line.trim()}`))
  assert.deepEqual(offenders, [], 'usa un token --fs-* de shared.css')
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
