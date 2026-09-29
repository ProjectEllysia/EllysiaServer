/**
 * Tests de `beyondHost` — lo que Lybra ve más allá de un único equipo.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * La pantalla decide con estas funciones qué escaneo lleva el capítulo de
 * riesgo lateral, qué veredicto recibe cada recurso cloud declarado y si un
 * dominio o un bucket ya está autorizado. Un error aquí enseñaría un recurso
 * abierto como cerrado, o dejaría lanzar algo que el servidor va a rechazar.
 */

import assert from 'node:assert/strict'

const { isNetworkScan, lateralRuleKey, reachMarks, cloudProviderKey, cloudVerdicts, isCoveredByRegister } =
  await import('../src/components/themis/lybra/beyondHost.js')

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('beyondHost')

test('un rango sin padre es un escaneo de red', () => {
  assert.equal(isNetworkScan({ target: '10.0.0.0/24' }), true)
  assert.equal(isNetworkScan({ target: '192.168.1.1-10' }), true)
  assert.equal(isNetworkScan({ target: '2001:db8::/64' }), true)
})

test('un equipo suelto, un hijo o un /32 no son de red', () => {
  assert.equal(isNetworkScan({ target: '10.0.0.5' }), false)
  assert.equal(isNetworkScan({ target: '10.0.0.5/32' }), false)
  assert.equal(isNetworkScan({ target: '10.0.0.5', parentScanId: 7 }), false)
  assert.equal(isNetworkScan({ target: 'web-01.example.com' }), false)
  assert.equal(isNetworkScan(null), false)
})

test('una regla desconocida cae en el rótulo genérico', () => {
  assert.equal(lateralRuleKey('multi-homed'), 'multiHomed')
  assert.equal(lateralRuleKey('shared-credentials'), 'sharedCredentials')
  assert.equal(lateralRuleKey('una-regla-nueva'), 'unknown')
})

test('el alcance marca un rombo por equipo implicado', () => {
  const risk = { hosts: [{ name: 'a' }, { name: 'b' }] }
  assert.deepEqual(reachMarks(risk, 4), { marks: [true, true, false, false], hidden: 0, involved: 2 })
})

test('una red grande se corta y cuenta lo que no cabe', () => {
  const risk = { hosts: Array.from({ length: 30 }, (_, i) => ({ name: `h${i}` })) }
  const { marks, hidden, involved } = reachMarks(risk, 200, 24)
  assert.equal(marks.length, 24)
  assert.equal(marks.every(Boolean), true)
  assert.equal(hidden, 176)
  assert.equal(involved, 30)
})

test('el proveedor sale del prefijo del recurso', () => {
  assert.equal(cloudProviderKey('s3:datos'), 's3')
  assert.equal(cloudProviderKey('Azure:cuenta/cont'), 'azure')
  assert.equal(cloudProviderKey('ftp:x'), 'unknown')
})

test('cada recurso declarado recibe su veredicto, también los cerrados', () => {
  const open = { service: 's3:datos', title: 'Bucket S3 público' }
  const takeover = { service: 'blog.example.com', title: 'Subdominio secuestrable' }
  const verdicts = cloudVerdicts({ cloudResources: ['s3:datos', 'firebase:app'], findings: [open, takeover] })
  assert.deepEqual(verdicts.resources, [{ subject: 's3:datos', finding: open }, { subject: 'firebase:app', finding: null }])
  assert.deepEqual(verdicts.subdomains, [takeover])
})

test('un escaneo sin recursos declarados solo tiene subdominios', () => {
  const verdicts = cloudVerdicts({ findings: [] })
  assert.deepEqual(verdicts, { resources: [], subdomains: [] })
})

test('un dominio registrado cubre sus subdominios y no a un parecido', () => {
  const entries = [{ target: 'example.com' }, { target: 's3:datos' }, { target: '10.0.0.0/24' }]
  assert.equal(isCoveredByRegister('example.com', entries), true)
  assert.equal(isCoveredByRegister('Dev.Example.com.', entries), true)
  assert.equal(isCoveredByRegister('evil-example.com', entries), false)
})

test('un recurso cloud solo se cubre a sí mismo', () => {
  const entries = [{ target: 's3:datos' }]
  assert.equal(isCoveredByRegister('S3:Datos', entries), true)
  assert.equal(isCoveredByRegister('s3:otros', entries), false)
  assert.equal(isCoveredByRegister('10.0.0.5', [{ target: '10.0.0.0/24' }]), false)
})

if (failures) {
  console.error(`\n${failures} test(s) fallaron`)
  process.exit(1)
}
console.log('\ntodo en verde')
