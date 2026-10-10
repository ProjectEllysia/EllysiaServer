/**
 * Tests de la lógica pura de la pantalla de marcos de Eunomia: el reparto del catálogo entre
 * disponibles, adoptados y archivados, y las cantidades que enseña el aviso de quitar un marco.
 */

import assert from 'node:assert/strict'

const { splitFrameworks, removalFacts, hasLoss } = await import('../src/components/eunomia/frameworks.js')

let failures = 0
async function test(name, fn) {
  try { await fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('eunomia.frameworks')

const catalog = [{ key: 'iso27001' }, { key: 'ens' }, { key: 'nis2' }]

await test('un marco adoptado o archivado deja de estar disponible', () => {
  const { available } = splitFrameworks(catalog, [
    { frameworkKey: 'nis2', status: 'active' }, { frameworkKey: 'ens', status: 'archived' },
  ])
  assert.deepEqual(available.map((framework) => framework.key), ['iso27001'])
})

await test('las adopciones se reparten por estado sin perder el orden', () => {
  const { active, archived } = splitFrameworks(catalog, [
    { frameworkKey: 'b', status: 'active' }, { frameworkKey: 'x', status: 'archived' },
    { frameworkKey: 'a', status: 'active' },
  ])
  assert.deepEqual(active.map((adoption) => adoption.frameworkKey), ['b', 'a'])
  assert.deepEqual(archived.map((adoption) => adoption.frameworkKey), ['x'])
})

await test('sin adopciones, todo el catálogo está disponible', () => {
  assert.equal(splitFrameworks(catalog, []).available.length, 3)
})

await test('el aviso no enumera ceros', () => {
  const facts = removalFacts({ assessments: 12, evidenceDeleted: 0, evidenceKept: 3 })
  assert.deepEqual(facts, [{ key: 'assessments', count: 12 }, { key: 'evidenceKept', count: 3 }])
})

await test('una vista previa sin nada que perder da una lista vacía', () => {
  assert.deepEqual(removalFacts({ assessments: 0, evidenceDeleted: 0, evidenceKept: 0 }), [])
  assert.equal(hasLoss({ assessments: 0, evidenceDeleted: 0 }), false)
})

await test('conservar evidencias no cuenta como pérdida', () => {
  assert.equal(hasLoss({ assessments: 0, evidenceDeleted: 0, evidenceKept: 5 }), false)
  assert.equal(hasLoss({ assessments: 1, evidenceDeleted: 0 }), true)
  assert.equal(hasLoss({ assessments: 0, evidenceDeleted: 2 }), true)
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
console.log('\nTodos los tests pasaron')
