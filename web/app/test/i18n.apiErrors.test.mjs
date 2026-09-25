/**
 * Tests de `src/i18n/apiErrors.js` — traducir un error de la API por su
 * plantilla.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`. Usa
 * vue-i18n de verdad y el `locales/es.json` real: así también se comprueba que
 * el compilador de mensajes acepta las plantillas tal como están escritas (una
 * `@` o una `|` sueltas tienen significado propio en vue-i18n).
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createI18n } from 'vue-i18n'

const { translateApiError } = await import('../src/i18n/apiErrors.js')

const spanish = JSON.parse(readFileSync(new URL('../src/i18n/locales/es.json', import.meta.url), 'utf-8'))
const i18n = createI18n({ legacy: false, locale: 'es', fallbackLocale: 'es', messages: { es: spanish }, missingWarn: false, fallbackWarn: false })

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('i18n/apiErrors')

test('traduce una plantilla con huecos', () => {
  const body = { messageKey: 'missingParameter', params: { parameter: 'port' }, error_description: 'x' }
  assert.equal(translateApiError(body, i18n.global), "El parámetro 'port' es obligatorio.")
})

test('traduce una plantilla anidada sin huecos', () => {
  assert.equal(translateApiError({ messageKey: 'entityNotFound.scan', params: {} }, i18n.global), 'Escaneo no encontrado.')
})

test('sin messageKey devuelve null para que se use el texto del servidor', () => {
  assert.equal(translateApiError({ error_description: 'Texto libre' }, i18n.global), null)
  assert.equal(translateApiError(null, i18n.global), null)
})

test('una clave que el diccionario no conoce devuelve null', () => {
  assert.equal(translateApiError({ messageKey: 'somethingNew', params: {} }, i18n.global), null)
})

test('sin params rellena igual lo que no tiene huecos', () => {
  assert.equal(translateApiError({ messageKey: 'surfaceDisabled' }, i18n.global), 'Esta función todavía no está disponible.')
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
