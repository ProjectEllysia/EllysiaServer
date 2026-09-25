/**
 * Tests de los ficheros de idioma de `src/i18n/locales/`.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * `es.json` es el idioma por defecto y el único completo: cualquier otro puede
 * estar a medias (lo que le falte se enseña en castellano), pero no puede
 * inventarse nada. Por cada fichero se comprueba que:
 *   - todas sus claves existen en `es.json` (una clave que solo existe en otro
 *     idioma es una errata o un texto que ya nadie pide);
 *   - no usa huecos `{…}` que el castellano no tenga (el código solo rellena
 *     los que pide el castellano: un hueco inventado saldría literal);
 *   - vue-i18n compila todos sus mensajes (una `@` o una `|` sueltas tienen
 *     significado propio y romperían el texto).
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { createI18n } from 'vue-i18n'

const { translateApiError } = await import('../src/i18n/apiErrors.js')

const localesDirectory = new URL('../src/i18n/locales/', import.meta.url)
const messagesByLocale = Object.fromEntries(
  readdirSync(localesDirectory)
    .filter((fileName) => fileName.endsWith('.json'))
    .map((fileName) => [fileName.replace(/\.json$/, ''), JSON.parse(readFileSync(new URL(fileName, localesDirectory), 'utf-8'))]),
)

/**
 * Aplana un árbol de mensajes a `{ 'a.b.c': texto }`.
 *
 * @param {object} tree - Árbol de mensajes de un idioma.
 * @param {string} [prefix=''] - Prefijo de la rama actual (uso recursivo).
 * @returns {Record<string, string>} Texto por clave completa.
 */
function flattenMessages(tree, prefix = '') {
  return Object.entries(tree).reduce((flat, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'object' ? { ...flat, ...flattenMessages(value, path) } : { ...flat, [path]: value }
  }, {})
}

/**
 * Devuelve los huecos `{nombre}` de un mensaje.
 *
 * @param {string} message - Texto de un mensaje.
 * @returns {Set<string>} Nombres de los huecos.
 */
function placeholdersOf(message) {
  return new Set([...message.matchAll(/\{(\w+)\}/g)].map((match) => match[1]))
}

const spanish = flattenMessages(messagesByLocale.es)

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('i18n/locales')

test('existe el idioma por defecto', () => {
  assert.ok(messagesByLocale.es, 'falta locales/es.json')
})

for (const [localeCode, tree] of Object.entries(messagesByLocale)) {
  const messages = flattenMessages(tree)

  test(`${localeCode}: declara su propio nombre en language.name`, () => {
    assert.equal(typeof tree.language?.name, 'string')
  })

  test(`${localeCode}: no tiene claves que el castellano no tenga`, () => {
    const unknownKeys = Object.keys(messages).filter((key) => !(key in spanish))
    assert.deepEqual(unknownKeys, [])
  })

  test(`${localeCode}: no usa huecos que el castellano no tenga`, () => {
    const inventedPlaceholders = Object.entries(messages)
      .filter(([key]) => key in spanish)
      .flatMap(([key, message]) => [...placeholdersOf(message)]
        .filter((name) => !placeholdersOf(spanish[key]).has(name))
        .map((name) => `${key}: {${name}}`))
    assert.deepEqual(inventedPlaceholders, [])
  })

  test(`${localeCode}: vue-i18n compila todos sus mensajes`, () => {
    const compileErrors = []
    const i18n = createI18n({
      legacy: false, locale: localeCode, messages: { [localeCode]: tree },
      missingWarn: false, fallbackWarn: false,
    })
    const originalWarn = console.warn
    console.warn = (...args) => compileErrors.push(args.join(' '))
    try {
      for (const key of Object.keys(messages)) {
        const params = Object.fromEntries([...placeholdersOf(messages[key])].map((name) => [name, `<${name}>`]))
        const rendered = i18n.global.t(key, params)
        if (rendered === key) compileErrors.push(`${key}: no se resolvió`)
      }
    } finally {
      console.warn = originalWarn
    }
    assert.deepEqual(compileErrors, [])
  })
}

test('un error de la API sale en inglés cuando el inglés es el idioma activo', () => {
  const i18n = createI18n({ legacy: false, locale: 'en', fallbackLocale: 'es', messages: messagesByLocale, missingWarn: false, fallbackWarn: false })
  const body = { messageKey: 'missingParameter', params: { parameter: 'port' }, error_description: 'El parámetro «port» es obligatorio.' }
  assert.equal(translateApiError(body, i18n.global), 'The “port” parameter is required.')
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
