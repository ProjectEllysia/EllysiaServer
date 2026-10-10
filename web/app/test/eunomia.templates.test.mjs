/**
 * Tests de la lógica pura del formulario de plantillas de Eunomia: qué se guarda de lo que el
 * usuario toca y a dónde lleva el origen de un campo precargado.
 */

import assert from 'node:assert/strict'

const { valuesToSave, missingRequired, sourceRoute, hasActiveDocuments } = await import('../src/components/eunomia/templates.js')

let failures = 0
async function test(name, fn) {
  try { await fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('eunomia.templates')

const fields = [
  { key: 'company_name', value: 'Acme', origin: 'company', isRequired: true },
  { key: 'csirt', value: '', origin: 'empty', isRequired: true },
  { key: 'approver', value: 'Ana', origin: 'saved', isRequired: false },
]

await test('un campo precargado que no se toca no se guarda', () => {
  assert.deepEqual(valuesToSave(fields, { company_name: 'Acme', csirt: '', approver: 'Ana' }), { approver: 'Ana' })
})

await test('un campo precargado que se corrige se guarda', () => {
  const values = valuesToSave(fields, { company_name: 'Acme S.A.', csirt: 'INCIBE-CERT', approver: 'Ana' })
  assert.deepEqual(values, { company_name: 'Acme S.A.', csirt: 'INCIBE-CERT', approver: 'Ana' })
})

await test('vaciar un campo guardado lo quita del borrador', () => {
  assert.deepEqual(valuesToSave(fields, { company_name: 'Acme', csirt: '', approver: '  ' }), {})
})

await test('los obligatorios sin valor se listan en el orden de la plantilla', () => {
  assert.deepEqual(missingRequired(fields, { company_name: '', csirt: 'x' }), ['company_name'])
})

await test('el origen lleva al perfil o a la evaluación, y lo escrito no lleva a ningún sitio', () => {
  assert.equal(sourceRoute({ origin: 'company' }, 'nis2'), '/profile')
  assert.equal(sourceRoute({ origin: 'assessment' }, 'nis2'), '/eunomia/marcos/nis2')
  assert.equal(sourceRoute({ origin: 'saved' }, 'nis2'), null)
})

await test('el sondeo de documentos sigue mientras alguno esté en cola o generándose', () => {
  assert.equal(hasActiveDocuments([{ status: 'done' }, { status: 'running' }]), true)
  assert.equal(hasActiveDocuments([{ status: 'done' }, { status: 'error' }]), false)
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
console.log('\nTodos los tests pasaron')
