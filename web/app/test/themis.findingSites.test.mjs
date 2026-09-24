/**
 * Tests de `findingSites` — a qué web pertenece cada hallazgo de Lybra.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Un servidor con varias webs en la misma dirección da el mismo aviso una vez
 * por web. Si la pantalla no dice de cuál es cada fila, el usuario ve dos
 * filas idénticas y las toma por un duplicado.
 */

import assert from 'node:assert/strict'

const { hasSeveralSites, siteLabel } =
  await import('../src/components/themis/lybra/findingSites.js')

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('findingSites')

test('el mismo aviso en la IP y en una web con nombre se etiqueta', () => {
  assert.equal(hasSeveralSites({ findings: [{ vhost: null }, { vhost: 'web.ejemplo.test' }] }), true)
})

test('un grupo de una sola web no se etiqueta', () => {
  assert.equal(hasSeveralSites({ findings: [{ vhost: null }, { vhost: null }] }), false)
  assert.equal(hasSeveralSites({ findings: [{ vhost: 'a.test' }, { vhost: 'a.test' }] }), false)
})

test('el sitio por defecto cuenta como la IP, no como otra web', () => {
  assert.equal(hasSeveralSites({ findings: [{ vhost: null }, { vhost: '(sitio por defecto)' }] }), false)
})

test('el grupo de sitios detectados no se etiqueta: su título ya es el sitio', () => {
  assert.equal(hasSeveralSites({ findings: [
    { vhost: 'a.test', category: 'virtual_host' },
    { vhost: 'b.test', category: 'virtual_host' },
  ] }), false)
})

test('la etiqueta habla en lenguaje de usuario', () => {
  assert.equal(siteLabel({ vhost: 'web.ejemplo.test' }), 'En web.ejemplo.test')
  assert.equal(siteLabel({ vhost: null }), 'Al entrar por la IP')
  assert.equal(siteLabel({}), 'Al entrar por la IP')
  assert.equal(siteLabel({ vhost: '(sitio por defecto)' }), 'Al entrar por la IP')
})

if (failures) {
  console.error(`\n${failures} test(s) fallaron`)
  process.exit(1)
}
console.log('\ntodo en verde')
