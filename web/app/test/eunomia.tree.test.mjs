/**
 * Tests de la lógica pura del árbol personal de Eunomia: filtrado, aplanado de lo visible y
 * navegación con el teclado, con árboles de dos y de cuatro niveles.
 */

import assert from 'node:assert/strict'

const { filterTree, visibleNodes, keyAction, groupCodes, findNode, statusOf } =
  await import('../src/components/eunomia/tree.js')

let failures = 0
async function test(name, fn) {
  try { await fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

const leaf = (code, title, status) => ({
  code, identifier: code.split(':')[1], title, description: '', children: [],
  assessment: { status },
})
const group = (code, title, children) => ({ code, identifier: code.split(':')[1], title, description: '', children, assessment: null })

// ISO 27001: dos niveles. ENS: cuatro (marco > grupo > subgrupo > medida).
const twoLevels = [group('iso:A.5', 'Organizativos', [leaf('iso:A.5.9', 'Inventario', 'pending'), leaf('iso:A.5.15', 'Control de acceso', 'implemented')])]
const fourLevels = [
  group('ens:op', 'Marco operacional', [
    group('ens:op.acc', 'Control de acceso', [
      group('ens:op.acc.6', 'Autenticación', [leaf('ens:op.acc.6.1', 'Usuarios', 'in_progress')]),
    ]),
  ]),
]

console.log('eunomia.tree')

await test('el aplanado respeta lo contraído y numera los niveles', () => {
  const rows = visibleNodes(fourLevels, new Set(['ens:op', 'ens:op.acc']))
  assert.deepEqual(rows.map((row) => [row.node.code, row.level]),
    [['ens:op', 1], ['ens:op.acc', 2], ['ens:op.acc.6', 3]])
})

await test('un árbol de cuatro niveles se despliega entero', () => {
  const rows = visibleNodes(fourLevels, groupCodes(fourLevels))
  assert.equal(Math.max(...rows.map((row) => row.level)), 4)
})

await test('un árbol de dos niveles no necesita nada especial', () => {
  const rows = visibleNodes(twoLevels, new Set(['iso:A.5']))
  assert.equal(rows.length, 3)
  assert.equal(rows[1].hasChildren, false)
})

await test('buscar conserva el camino hasta la coincidencia', () => {
  const filtered = filterTree(fourLevels, { query: 'usuarios' })
  assert.deepEqual(visibleNodes(filtered, groupCodes(filtered)).map((row) => row.node.code),
    ['ens:op', 'ens:op.acc', 'ens:op.acc.6', 'ens:op.acc.6.1'])
  assert.equal(filtered[0].isPathOnly, true)
})

await test('filtrar por estado deja solo los controles con ese estado y su camino', () => {
  const filtered = filterTree(twoLevels, { status: 'implemented' })
  assert.deepEqual(visibleNodes(filtered, groupCodes(filtered)).map((row) => row.node.code),
    ['iso:A.5', 'iso:A.5.15'])
})

await test('sin filtros el árbol se devuelve tal cual', () => {
  assert.equal(filterTree(twoLevels), twoLevels)
})

await test('una búsqueda sin resultados da un árbol vacío', () => {
  assert.deepEqual(filterTree(twoLevels, { query: 'zzz' }), [])
})

await test('teclado: abajo y arriba se mueven por lo visible y no se salen', () => {
  const rows = visibleNodes(twoLevels, new Set(['iso:A.5']))
  assert.equal(keyAction(rows, 'iso:A.5', 'ArrowDown').focus, 'iso:A.5.9')
  assert.equal(keyAction(rows, 'iso:A.5', 'ArrowUp').focus, 'iso:A.5')
  assert.equal(keyAction(rows, 'iso:A.5.15', 'ArrowDown').focus, 'iso:A.5.15')
  assert.equal(keyAction(rows, 'iso:A.5.9', 'End').focus, 'iso:A.5.15')
  assert.equal(keyAction(rows, 'iso:A.5.15', 'Home').focus, 'iso:A.5')
})

await test('teclado: derecha abre un grupo cerrado, entra en uno abierto; izquierda cierra o sube', () => {
  const closed = visibleNodes(twoLevels, new Set())
  assert.deepEqual(keyAction(closed, 'iso:A.5', 'ArrowRight'), { focus: null, toggle: 'open' })

  const open = visibleNodes(twoLevels, new Set(['iso:A.5']))
  assert.equal(keyAction(open, 'iso:A.5', 'ArrowRight').focus, 'iso:A.5.9')
  assert.deepEqual(keyAction(open, 'iso:A.5', 'ArrowLeft'), { focus: null, toggle: 'close' })
  assert.equal(keyAction(open, 'iso:A.5.9', 'ArrowLeft').focus, 'iso:A.5')
})

await test('un grupo no tiene estado y findNode localiza a cualquier profundidad', () => {
  assert.equal(statusOf(fourLevels[0]), null)
  assert.equal(findNode(fourLevels, 'ens:op.acc.6.1').title, 'Usuarios')
  assert.equal(findNode(fourLevels, 'no:existe'), null)
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
console.log('\nTodos los tests pasaron')
