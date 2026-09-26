/**
 * Test de los rótulos de Iris (`components/iris/verdict.js`).
 *
 * Fija que los valores que el servidor manda en inglés dan con su rótulo del
 * diccionario, y que un valor desconocido cae en un rótulo genérico en vez de
 * llegar crudo a la pantalla (CONVENCIONES.md § 12.2). El módulo devuelve
 * claves; aquí se resuelven contra `locales/es.json` para comprobar también lo
 * que se lee.
 *
 *   node web/app/test/iris.verdict.test.mjs
 */

import { readFileSync } from 'node:fs'
import { createI18n } from 'vue-i18n'
import {
  verdictKey, verdictClass, analysisStatusKey, ruleCategoryKey, ruleVerdictKey,
} from '../src/components/iris/verdict.js'

const spanish = JSON.parse(readFileSync(new URL('../src/i18n/locales/es.json', import.meta.url), 'utf-8'))
const { t, te } = createI18n({ legacy: false, locale: 'es', messages: { es: spanish } }).global

let passed = 0
let failed = 0
function check(name, cond, detail = '') {
  if (cond) { passed++; console.log(`  ✓ ${name}`) }
  else { failed++; console.error(`  ✗ ${name}${detail ? ' — ' + detail : ''}`) }
}
function eq(name, actual, expected) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  check(name, a === e, `esperado ${e}, obtenido ${a}`)
}

console.log('\nverdictKey / verdictClass')
eq('veredicto del servidor, en castellano', t(verdictKey('Suspicious')), 'Sospechoso')
eq('no distingue mayúsculas', t(verdictKey('legitimate')), 'Legítimo')
eq('sin veredicto', t(verdictKey(null)), 'Sin veredicto')
eq('veredicto desconocido: genérico, nunca el crudo', t(verdictKey('Spam')), 'Sin veredicto')
eq('tono del veredicto', verdictClass('Phishing'), 'phish')
eq('tono desconocido', verdictClass(undefined), 'unknown')

console.log('\nanalysisStatusKey')
eq('en curso', t(analysisStatusKey('running')), 'En análisis')
eq('estado desconocido', t(analysisStatusKey('queued')), 'Desconocido')

console.log('\nruleCategoryKey / ruleVerdictKey')
eq('categoría', t(ruleCategoryKey('content_analysis')), 'Contenido')
eq('categoría desconocida', t(ruleCategoryKey('reputation')), 'Otra')
eq('resultado SPF', t(ruleVerdictKey('softfail')), 'Falla leve')
eq('resultado desconocido', t(ruleVerdictKey('temperror')), 'Otro')

console.log('\ncada clave que puede devolver el módulo existe en el diccionario')
const values = {
  verdictKey: ['legitimate', 'suspicious', 'phishing', null],
  analysisStatusKey: ['pending', 'running', 'finished', 'failed', 'cancelled', null],
  ruleCategoryKey: ['authentication', 'header_analysis', 'content_analysis', null],
  ruleVerdictKey: ['pass', 'fail', 'softfail', 'suspicious', 'neutral', 'missing', 'error', 'trusted',
    'bestguess', 'policy', 'none', 'spoof', 'empty', 'empty_to', 'undisclosed', 'future', 'past', 'unparseable', null],
}
const functions = { verdictKey, analysisStatusKey, ruleCategoryKey, ruleVerdictKey }
const missing = Object.entries(values).flatMap(([name, list]) => list.map(value => functions[name](value)).filter(key => !te(key)))
eq('sin claves huérfanas', missing, [])

console.log(`\n${passed} pasados, ${failed} fallidos\n`)
process.exit(failed === 0 ? 0 : 1)
