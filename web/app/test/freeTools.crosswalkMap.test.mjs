/**
 * Mapa de correspondencias de Eunomia: el índice de enlaces en los dos sentidos, el agrupado por
 * marco y los marcos sin cruce publicado. Y que el enlace del hub apunta a la ruta de la herramienta.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { FREE_TOOLS, freeToolPath } from '../src/freeTools/catalog.js'
import {
  COVERAGE_FULL,
  COVERAGE_PARTIAL,
  correspondencesOf,
  indexLinks,
  unlinkedFrameworks,
} from '../src/components/freeTools/crosswalkMap.js'

let failures = 0
function test(name, fn) {
  try {
    fn()
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failures += 1
    console.log(`  ✗ ${name}\n    ${error.message}`)
  }
}

const link = (fromFramework, fromIdentifier, toFramework, toIdentifier, coverage) =>
  ({ fromFramework, fromIdentifier, toFramework, toIdentifier, coverage })

const links = [
  link('nis2', '20.1', 'ens', 'org.1', COVERAGE_PARTIAL),
  link('nis2', '20.1', 'ens', 'org.2', COVERAGE_FULL),
  link('nis2', '20.1', 'iso27001', 'A.5.4', COVERAGE_PARTIAL),
  link('rgpd', 'art.24', 'nis2', '20.1', COVERAGE_PARTIAL),
]
const ORDER = ['iso27001', 'ens', 'nis2', 'rgpd']
const index = indexLinks(links)

console.log('correspondencias')

test('un enlace se lee desde los dos lados', () => {
  assert.deepEqual(correspondencesOf(index, 'ens', 'org.1', ORDER),
    [{ framework: 'nis2', items: [{ identifier: '20.1', coverage: COVERAGE_PARTIAL }] }])
  assert.deepEqual(correspondencesOf(index, 'nis2', 'art.24', ORDER), [])
})

test('se agrupan por marco, en el orden en que se enseñan los marcos', () => {
  const groups = correspondencesOf(index, 'nis2', '20.1', ORDER)
  assert.deepEqual(groups.map((group) => group.framework), ['iso27001', 'ens', 'rgpd'])
  assert.deepEqual(groups[1].items, [
    { identifier: 'org.1', coverage: COVERAGE_PARTIAL },
    { identifier: 'org.2', coverage: COVERAGE_FULL },
  ])
})

test('un control sin enlaces no tiene correspondencias', () => {
  assert.deepEqual(correspondencesOf(index, 'ens', 'op.acc.2', ORDER), [])
})

console.log('marcos sin cruce')

test('salen los marcos sin ningún enlace con la referencia, y nunca ella misma', () => {
  assert.deepEqual(unlinkedFrameworks(links, 'ens', ORDER), ['iso27001', 'rgpd'])
  assert.deepEqual(unlinkedFrameworks(links, 'nis2', ORDER), [])
})

console.log('hub')

test('el enlace del hub apunta a la ruta de la herramienta', () => {
  const tool = FREE_TOOLS.find((item) => item.id === 'crosswalkMap')
  assert.ok(tool, 'falta crosswalkMap en el catálogo')
  assert.equal(tool.module, 'eunomia')
  const hub = readFileSync(fileURLToPath(new URL('../src/views/eunomia/EunomiaHubView.vue', import.meta.url)), 'utf-8')
  assert.ok(hub.includes(`to: '${freeToolPath(tool)}'`), 'el atajo del hub no coincide con la ruta de la herramienta')
})

if (failures) {
  console.error(`\n${failures} fallo(s)`)
  process.exit(1)
}
console.log('\nOK')
