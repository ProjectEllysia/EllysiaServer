/**
 * Tests de `flatten`/`unflatten` — el viaje de ida y vuelta de ConfigView.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * ConfigView aplana la configuración para editarla y la reconstruye al
 * guardar, y `PUT /system` escribe el fichero entero con lo que recibe. Una
 * clave que contenga un punto (las fuentes OVAL: `"ubuntu:20.04"`) se partía
 * en dos niveles al reconstruir, y cualquier guardado dejaba esas fuentes
 * convertidas en `{"ubuntu:20": {"04": url}}`.
 */

import assert from 'node:assert/strict'

const { useUtils } = await import('../src/composables/useUtils.js')
const { flatten, unflatten } = useUtils()

let failures = 0
function test(name, fn) {
  try {
    fn()
    console.log(`  ok   ${name}`)
  } catch (error) {
    failures += 1
    console.error(`  FAIL ${name}\n       ${error.message}`)
  }
}

test('una clave con punto propio sobrevive al viaje de ida y vuelta', () => {
  const config = {
    features: { themis: { kb: { sources: { oval: {
      'debian:12': 'https://example.test/bookworm.xml.bz2',
      'ubuntu:20.04': 'https://example.test/focal.xml.bz2',
    } } } } },
  }
  assert.deepEqual(unflatten(flatten(config)), config)
})

test('la ruta de una clave sin punto no cambia', () => {
  const flat = flatten({ features: { themis: { kb: { syncCron: '0 3 * * *' } } } })
  assert.deepEqual(flat, { 'features.themis.kb.syncCron': '0 3 * * *' })
})

test('el punto propio se escapa en la ruta plana', () => {
  const flat = flatten({ oval: { 'ubuntu:24.04': 'u' } })
  assert.deepEqual(Object.keys(flat), ['oval.ubuntu:24\\.04'])
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
console.log('\nconfigFlatten: todo en verde')
