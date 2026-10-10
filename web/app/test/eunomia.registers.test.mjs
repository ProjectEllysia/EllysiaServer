/**
 * Tests de la lógica pura de los registros de Eunomia.
 */

import assert from 'node:assert/strict'

const { recordValues, missingFields, toDatetimeLocal, deadlineCounts } = await import('../src/components/eunomia/registers.js')

let failures = 0
async function test(name, fn) {
  try { await fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('eunomia.registers')

const fields = [{ key: 'name', isRequired: true }, { key: 'note', isRequired: false }]

await test('solo se mandan los campos con texto', () => {
  assert.deepEqual(recordValues(fields, { name: 'Nóminas', note: '  ' }), { name: 'Nóminas' })
})

await test('los obligatorios vacíos se listan', () => {
  assert.deepEqual(missingFields(fields, { name: ' ' }), ['name'])
  assert.deepEqual(missingFields(fields, { name: 'x' }), [])
})

await test('un instante ISO se recorta al formato del campo datetime-local', () => {
  assert.equal(toDatetimeLocal('2026-10-10T08:30:00'), '2026-10-10T08:30')
  assert.equal(toDatetimeLocal(''), '')
})

await test('se cuentan los plazos vencidos y los que están por venir; los cumplidos no', () => {
  const records = [
    { deadlines: [{ status: 'overdue' }, { status: 'done' }] },
    { deadlines: [{ status: 'upcoming' }, { status: 'pending_input' }] },
    {},
  ]
  assert.deepEqual(deadlineCounts(records), { overdue: 1, upcoming: 1 })
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
console.log('\nTodos los tests pasaron')
