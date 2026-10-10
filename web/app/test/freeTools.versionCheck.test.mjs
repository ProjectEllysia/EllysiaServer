/**
 * Tests de la herramienta gratuita «¿Es vulnerable mi versión?»
 * (`src/components/freeTools/versionCheck.js`).
 *
 * Node puro, sin framework. La correlación la hace el servidor; aquí se
 * comprueba que lo que se valida en el navegador es lo mismo que acepta él y que
 * cada estado tiene su texto.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  MAX_PRODUCT_LENGTH,
  VERSION_EXAMPLES,
  cvssSeverity,
  endOfLifeState,
  isProduct,
  isVersion,
} from '../src/components/freeTools/versionCheck.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const locales = ['es', 'en'].map((code) => [code, JSON.parse(readFileSync(`${appRoot}src/i18n/locales/${code}.json`, 'utf-8'))])

let failures = 0
function test(name, fn) {
  try {
    fn()
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
}

test('una versión normal, de distribución o con época es válida', () => {
  for (const version of ['1.18.0', '8.9p1', '2.4.49', '1:2.3.4-1ubuntu1', '10', 'v2.0', ' 1.2 ']) assert.ok(isVersion(version), version)
})

test('lo que no es una versión no se envía, con el mismo formato que el servidor', () => {
  for (const version of ['', '-1', '1.0 OR 1=1', 'a'.repeat(41), '1.0;', undefined]) assert.equal(isVersion(version), false, String(version))
})

test('el producto no puede ir vacío ni pasarse del límite del servidor', () => {
  assert.ok(isProduct('Apache httpd'))
  assert.equal(isProduct('   '), false)
  assert.equal(isProduct('a'.repeat(MAX_PRODUCT_LENGTH + 1)), false)
  assert.equal(isProduct(null), false)
})

test('la gravedad sale de los tramos de CVSS, y sin puntuación es «sin puntuar»', () => {
  assert.equal(cvssSeverity(9.8), 'critical')
  assert.equal(cvssSeverity(7.5), 'high')
  assert.equal(cvssSeverity(5.3), 'medium')
  assert.equal(cvssSeverity(2), 'low')
  assert.equal(cvssSeverity(null), 'unrated')
})

test('el fin de soporte se distingue entre vencido, vigente y desconocido', () => {
  assert.equal(endOfLifeState({ isPast: true }), 'past')
  assert.equal(endOfLifeState({ isPast: false }), 'supported')
  assert.equal(endOfLifeState(null), null)
})

test('los ejemplos son válidos y cada texto existe en los dos idiomas', () => {
  for (const example of VERSION_EXAMPLES) assert.ok(isProduct(example.product) && isVersion(example.version), example.product)
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.versionCheck
    for (const key of ['past', 'supported']) assert.ok(item.endOfLife[key], `${code}: ${key}`)
    for (const key of ['unknown', 'none', 'found', 'invalidVersion', 'failed', 'identifiedAs', 'backportsNote']) assert.ok(item[key], `${code}: ${key}`)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
