/**
 * Tests del analizador de cabeceras gratuito
 * (`src/components/freeTools/headerAnalyzer.js`).
 *
 * Node puro, sin framework. La lectura la hace el servidor; aquí se comprueba que
 * cada código que puede mandar tiene su texto y su tono, y que lo desconocido no
 * se enseña en crudo.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  AUTH_CHECKS,
  AUTH_VERDICTS,
  MAX_HEADERS_LENGTH,
  SAMPLE_HEADERS,
  rejectionReason,
  verdictLabelKey,
  verdictTone,
} from '../src/components/freeTools/headerAnalyzer.js'

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

test('cada comprobación y cada veredicto tienen texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.headerAnalyzer
    for (const check of AUTH_CHECKS) assert.ok(item.checks[check]?.name && item.checks[check]?.what, `${code}: ${check}`)
    for (const verdict of [...AUTH_VERDICTS, 'other']) assert.ok(item.verdicts[verdict], `${code}: ${verdict}`)
    for (const reason of ['tooLong', 'notHeaders', 'failed']) assert.ok(item.errors[reason], `${code}: ${reason}`)
  }
})

test('un veredicto desconocido cae en «other» y se pinta neutro', () => {
  assert.equal(verdictLabelKey('pass'), 'freeTools.items.headerAnalyzer.verdicts.pass')
  assert.equal(verdictLabelKey('temperror'), 'freeTools.items.headerAnalyzer.verdicts.other')
  assert.equal(verdictTone('temperror'), 'unknown')
})

test('pasar es verde, fallar es rojo, a medias es ámbar y no saber es neutro', () => {
  assert.equal(verdictTone('pass'), 'good')
  assert.equal(verdictTone('fail'), 'bad')
  assert.equal(verdictTone('softfail'), 'warn')
  for (const silent of ['missing', 'neutral', 'policy']) assert.equal(verdictTone(silent), 'unknown', silent)
})

test('un 422 por tamaño se distingue de unas cabeceras que no se pueden leer', () => {
  assert.equal(rejectionReason(422, 'a'.repeat(MAX_HEADERS_LENGTH + 1)), 'tooLong')
  assert.equal(rejectionReason(422, 'corto'), 'notHeaders')
  assert.equal(rejectionReason(400, 'una frase'), 'notHeaders')
  assert.equal(rejectionReason(500, 'lo que sea'), 'failed')
  assert.equal(rejectionReason(429, 'lo que sea'), 'failed')
})

test('el ejemplo trae una cadena Received, autenticación y remitente, y cabe en el límite', () => {
  assert.equal(SAMPLE_HEADERS.match(/^Received:/gm).length, 3)
  for (const header of ['Authentication-Results:', 'From:', 'Subject:']) assert.ok(SAMPLE_HEADERS.includes(header), header)
  assert.ok(SAMPLE_HEADERS.length < MAX_HEADERS_LENGTH)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
