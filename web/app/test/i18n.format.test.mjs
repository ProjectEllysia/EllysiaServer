/**
 * Tests de `src/i18n/format.js` — fechas, números y orden alfabético según el
 * idioma activo.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Fijan dos cosas:
 *   - que en castellano la salida es exactamente la de antes, cuando cada
 *     llamada llevaba `'es-ES'` escrito a mano (pasar a leer el idioma activo
 *     no puede cambiar nada de lo que el usuario ve hoy);
 *   - que cambiar el idioma activo cambia la salida, que es para lo que existe.
 */

import assert from 'node:assert/strict'

const { activeLocale, DEFAULT_LOCALE } = await import('../src/i18n/locale.js')
const { formatDate, formatDateTime, formatNumber, getCollator } = await import('../src/i18n/format.js')

let failures = 0
function test(name, fn) {
  activeLocale.value = DEFAULT_LOCALE
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

const INSTANT = '2026-03-05T09:07:00Z'

// Las combinaciones de opciones que usa hoy el SPA.
const DATE_OPTIONS = [
  undefined,
  { year: 'numeric', month: '2-digit', day: '2-digit' },
  { day: '2-digit', month: '2-digit' },
  { day: 'numeric', month: 'long', year: 'numeric' },
  { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' },
  { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' },
]
const DATE_TIME_OPTIONS = [
  undefined,
  { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' },
  { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' },
]

console.log('i18n/format')

test('el idioma por defecto es el castellano', () => {
  assert.equal(DEFAULT_LOCALE, 'es')
})

test('formatDate en castellano da lo mismo que el antiguo es-ES', () => {
  for (const options of DATE_OPTIONS) {
    assert.equal(formatDate(INSTANT, options), new Date(INSTANT).toLocaleDateString('es-ES', options), JSON.stringify(options))
  }
})

test('formatDateTime en castellano da lo mismo que el antiguo es-ES', () => {
  for (const options of DATE_TIME_OPTIONS) {
    assert.equal(formatDateTime(INSTANT, options), new Date(INSTANT).toLocaleString('es-ES', options), JSON.stringify(options))
  }
})

test('formatNumber en castellano da lo mismo que el antiguo es-ES', () => {
  for (const value of [0, 3.25, 1234, 12345, 1234567]) {
    for (const options of [{ maximumFractionDigits: 0 }, { maximumFractionDigits: 1 }]) {
      assert.equal(formatNumber(value, options), value.toLocaleString('es-ES', options))
    }
  }
})

test('cambiar el idioma activo cambia el formato', () => {
  const options = { day: 'numeric', month: 'long' }
  const spanish = formatDate(INSTANT, options)
  activeLocale.value = 'en'
  const english = formatDate(INSTANT, options)
  assert.notEqual(english, spanish)
  assert.match(english, /March/)
  assert.equal(formatNumber(12345.5, { maximumFractionDigits: 1 }), '12,345.5')
})

test('el orden alfabético en castellano pone la ñ tras la n', () => {
  const words = ['ñandú', 'oso', 'nube']
  assert.deepEqual([...words].sort(getCollator().compare), ['nube', 'ñandú', 'oso'])
})

test('getCollator con numeric ordena host2 antes que host10', () => {
  const hosts = ['host10', 'host2', 'host1']
  assert.deepEqual([...hosts].sort(getCollator({ numeric: true }).compare), ['host1', 'host2', 'host10'])
})

test('getCollator reutiliza el comparador y lo renueva al cambiar de idioma', () => {
  const first = getCollator({ numeric: true })
  assert.equal(getCollator({ numeric: true }), first, 'construyó otro para las mismas opciones')
  activeLocale.value = 'en'
  const english = getCollator({ numeric: true })
  assert.notEqual(english, first, 'reutilizó el del castellano tras cambiar de idioma')
  assert.equal(english.resolvedOptions().locale.startsWith('en'), true)
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
