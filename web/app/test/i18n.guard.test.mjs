/**
 * Guardas del mecanismo de idiomas sobre el código del SPA.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`. Lee los
 * ficheros de `src/` como texto; no los ejecuta.
 *
 * Dos reglas de `CONVENCIONES.md` § 12.5 que, sin nada que las compruebe, se
 * degradan en cuanto alguien copia un trozo de código viejo:
 *   - fechas, números y orden alfabético no llevan el idioma escrito a mano
 *     ni usan el del navegador: pasan por `src/i18n/format.js`;
 *   - un fichero ya migrado no vuelve a tener texto escrito en su plantilla.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

/**
 * Ficheros cuyos textos ya viven entero en el diccionario. Al migrar otro, se
 * añade aquí: a partir de entonces la guarda lo vigila.
 */
const MIGRATED_FILES = [
  'components/shared/AccountMenu.vue',
  'components/shared/AppPagination.vue',
  'components/shared/ConfirmModal.vue',
  'components/shared/LanguageSelect.vue',
  'components/shared/SiteFooter.vue',
  'components/shared/SiteHeader.vue',
  'components/shared/Topbar.vue',
]

/**
 * Palabras que se escriben igual en todos los idiomas y pueden quedar en una
 * plantilla migrada: nombres propios del producto y su dominio.
 */
const LANGUAGE_NEUTRAL_WORDS = new Set(['Ellysia', 'Themis', 'Aegis', 'Iris', 'Acheron', 'Hygeia', 'ellysia', 'es', 'v'])

/** Una etiqueta HTML entera, aunque sus atributos lleven `>` entre comillas. */
const TAG_RE = /<(?:[^>"']|"[^"]*"|'[^']*')*>/g

/**
 * Llamadas que formatean con un idioma fijo o con el del navegador.
 *
 * - `toLocaleDateString('es-ES')`, `Intl.Collator('es')`,
 *   `localeCompare(x, 'es')`: idioma escrito a mano.
 * - `toLocaleString()` sin argumentos: idioma del navegador, que no tiene por
 *   qué ser el de la interfaz.
 */
const HARDCODED_LOCALE_PATTERNS = [
  /\.toLocale(?:Date|Time)?String\(\s*['"`]/,
  /\.toLocale(?:Date|Time)?String\(\s*\)/,
  /new\s+Intl\.\w+\(\s*['"`]/,
  /\.localeCompare\([^)]*,\s*['"`][a-z]{2}/,
]

/**
 * Recorre `src/` y devuelve las rutas de los ficheros `.js` y `.vue`.
 *
 * @param {string} directory - Directorio desde el que empezar.
 * @returns {string[]} Rutas absolutas.
 */
function listSourceFiles(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) return listSourceFiles(path)
    return /\.(js|vue)$/.test(name) ? [path] : []
  })
}

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('i18n/guard')

test('ningún formato de fecha, número u orden lleva el idioma fijo', () => {
  const offenders = []
  for (const path of listSourceFiles(sourceRoot)) {
    const relativePath = relative(sourceRoot, path).replaceAll('\\', '/')
    if (relativePath.startsWith('i18n/')) continue
    readFileSync(path, 'utf-8').split('\n').forEach((line, index) => {
      if (HARDCODED_LOCALE_PATTERNS.some((pattern) => pattern.test(line))) {
        offenders.push(`${relativePath}:${index + 1}: ${line.trim()}`)
      }
    })
  }
  assert.deepEqual(offenders, [], 'usa formatDate/formatDateTime/formatNumber/getCollator de src/i18n/format.js')
})

/**
 * Devuelve las palabras escritas a mano que quedan en la plantilla de un `.vue`.
 *
 * Quita comentarios, interpolaciones `{{ }}`, iconos SVG, etiquetas y entidades
 * HTML; lo que queda con letras es texto que el usuario lee y que no sale del
 * diccionario. Los nombres propios de `LANGUAGE_NEUTRAL_WORDS` no cuentan.
 *
 * @param {string} source - Contenido completo del fichero `.vue`.
 * @returns {string[]} Palabras sin repetir, más los atributos de texto
 *   (`title`, `aria-label`, `placeholder`, `alt`) escritos con un literal.
 */
function findHandwrittenText(source) {
  const template = source.match(/<template>([\s\S]*)<\/template>/)?.[1] ?? ''
  const withoutMarkup = template
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/\{\{[\s\S]*?\}\}/g, ' ')
    .replace(/<svg[\s\S]*?<\/svg>/g, ' ')
    .replace(TAG_RE, ' ')
    .replace(/&\w+;/g, ' ')
  const words = (withoutMarkup.match(/\p{L}[\p{L}'’-]*/gu) ?? [])
    .filter((word) => !LANGUAGE_NEUTRAL_WORDS.has(word))
  const literalAttributes = [...template.matchAll(/\s(title|aria-label|placeholder|alt)="([^"]*\p{L}[^"]*)"/gu)]
    .map((match) => `${match[1]}="${match[2]}"`)
  return [...new Set(words), ...literalAttributes]
}

test('los ficheros migrados no tienen texto escrito en su plantilla', () => {
  const offenders = MIGRATED_FILES
    .map((relativePath) => [relativePath, findHandwrittenText(readFileSync(join(sourceRoot, relativePath), 'utf-8'))])
    .filter(([, handwritten]) => handwritten.length)
    .map(([relativePath, handwritten]) => `${relativePath}: ${handwritten.join(', ')}`)
  assert.deepEqual(offenders, [], 'los textos de un fichero migrado van en locales/es.json y se piden con t()')
})

test('la guarda de texto detecta una plantilla sin migrar', () => {
  // Protege a la propia guarda: un fichero sin migrar tiene que dar positivo.
  const handwritten = findHandwrittenText(readFileSync(join(sourceRoot, 'views/public/NotAvailableView.vue'), 'utf-8'))
  assert.ok(handwritten.length > 0, 'NotAvailableView ya no tiene texto: elige otro fichero sin migrar para esta prueba')
})

test('la guarda de formato detecta un idioma escrito a mano', () => {
  const samples = ["d.toLocaleDateString('es-ES')", 'n.toLocaleString()', "new Intl.Collator('es')", "a.localeCompare(b, 'es')"]
  const undetected = samples.filter((line) => !HARDCODED_LOCALE_PATTERNS.some((pattern) => pattern.test(line)))
  assert.deepEqual(undetected, [])
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
