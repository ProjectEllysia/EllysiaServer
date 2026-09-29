/**
 * Tests de `targetShapes` — qué forma tiene lo que se quiere autorizar.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * El registro de objetivos autorizados admite una red, un dominio o un recurso
 * cloud, y el formulario lo dice antes de enviar. Si el navegador reconociera
 * mal la forma, el formulario prometería registrar una cosa y el servidor
 * guardaría otra, o dejaría enviar algo que el servidor va a rechazar.
 */

import assert from 'node:assert/strict'

const { classifyTarget, TARGET_SHAPES } =
  await import('../src/components/themis/lybra/targetShapes.js')

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('targetShapes')

test('las direcciones y los rangos son una red', () => {
  for (const text of ['203.0.113.10', '203.0.113.0/24', '10.0.0.0/8', '2001:db8::1', '2001:db8::/32', ' 192.168.1.5 ']) {
    assert.equal(classifyTarget(text), 'network', text)
  }
})

test('un rango con prefijo imposible no es una red', () => {
  assert.equal(classifyTarget('203.0.113.0/33'), null)
  assert.equal(classifyTarget('256.1.1.1'), null)
})

test('los dominios se reconocen con o sin punto final y en mayúsculas', () => {
  for (const text of ['example.com', 'dev.example.com', 'Example.COM.', 'münchen.de', 'a-b.example.co.uk']) {
    assert.equal(classifyTarget(text), 'domain', text)
  }
})

test('una sola palabra o una IP a medias no son un dominio', () => {
  assert.equal(classifyTarget('localhost'), null)
  assert.equal(classifyTarget('10.0.0'), null)
  assert.equal(classifyTarget('-bad.example.com'), null)
})

test('un dominio de más de 253 caracteres se rechaza', () => {
  const label = 'a'.repeat(63)
  assert.equal(classifyTarget([label, label, label, label, 'com'].join('.')), null)
  assert.equal(classifyTarget([label, label, label, 'example.com'].join('.')), 'domain')
})

test('los cuatro proveedores cloud se reconocen con las reglas de cada uno', () => {
  for (const text of ['s3:mi-bucket', 'S3:Mi-Bucket', 'gcs:datos_2026', 'azure:cuenta1/contenedor', 'firebase:mi-proyecto']) {
    assert.equal(classifyTarget(text), 'cloud', text)
  }
})

test('un recurso cloud que el proveedor no aceptaría se rechaza', () => {
  for (const text of ['s3:', 's3:ab', 'ftp:algo', 'azure:cuenta1', 'azure:c/contenedor', 'firebase:abc']) {
    assert.equal(classifyTarget(text), null, text)
  }
})

test('vacío no es nada', () => {
  assert.equal(classifyTarget(''), null)
  assert.equal(classifyTarget('   '), null)
  assert.equal(classifyTarget(undefined), null)
})

test('solo hay tres formas', () => {
  assert.deepEqual([...TARGET_SHAPES], ['network', 'domain', 'cloud'])
})

if (failures) {
  console.error(`\n${failures} test(s) fallaron`)
  process.exit(1)
}
console.log('\ntodo en verde')
