/**
 * Tests del detector de dominios engañosos gratuito
 * (`src/components/freeTools/lookalikeDomain.js`).
 *
 * Node puro, sin framework. El juicio lo hace el servidor; aquí se comprueba que
 * cada código que puede mandar tiene su texto y que lo desconocido no se enseña
 * en crudo.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  DOMAIN_EXAMPLES,
  FINDING_TYPES,
  NAMED_SCRIPTS,
  findingLabelKey,
  scriptName,
  verdictOf,
} from '../src/components/freeTools/lookalikeDomain.js'

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

test('cada tipo de hallazgo, alfabeto y veredicto tiene texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.lookalikeDomain
    for (const type of [...FINDING_TYPES, 'other']) assert.ok(item.findings[type], `${code}: ${type}`)
    for (const script of NAMED_SCRIPTS) assert.ok(item.scripts[script], `${code}: ${script}`)
    for (const verdict of ['suspicious', 'ownBrand', 'clean']) assert.ok(item.verdict[verdict], `${code}: ${verdict}`)
  }
})

test('un tipo de hallazgo desconocido cae en «other»', () => {
  assert.equal(findingLabelKey('typo'), 'freeTools.items.lookalikeDomain.findings.typo')
  assert.equal(findingLabelKey('quantum_squat'), 'freeTools.items.lookalikeDomain.findings.other')
  assert.equal(findingLabelKey(undefined), 'freeTools.items.lookalikeDomain.findings.other')
})

test('un alfabeto sin traducir se enseña con su nombre de Unicode en minúsculas', () => {
  const translate = (key) => `«${key}»`
  assert.equal(scriptName('CYRILLIC', translate), '«freeTools.items.lookalikeDomain.scripts.CYRILLIC»')
  assert.equal(scriptName('ARMENIAN', translate), 'Armenian')
})

test('el veredicto prefiere avisar; si no imita nada, distingue el dominio de la propia marca', () => {
  assert.equal(verdictOf({ isSuspicious: true, ownBrand: null }), 'suspicious')
  assert.equal(verdictOf({ isSuspicious: false, ownBrand: 'paypal' }), 'ownBrand')
  assert.equal(verdictOf({ isSuspicious: false, ownBrand: null }), 'clean')
})

test('el primer ejemplo es de verdad un homógrafo: lleva una «а» cirílica', () => {
  assert.ok(DOMAIN_EXAMPLES[0].includes('а'), DOMAIN_EXAMPLES[0])
  assert.notEqual(DOMAIN_EXAMPLES[0], 'paypal.com')
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
