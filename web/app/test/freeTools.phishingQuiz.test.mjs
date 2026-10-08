/**
 * Tests del mini quiz de phishing gratuito (`src/components/freeTools/phishingQuiz.js`).
 *
 * Node puro, sin framework. Además de la corrección y el barajado, se fija que cada
 * correo tiene todos sus textos en los dos idiomas y que el quiz no regala la
 * respuesta con la proporción de soluciones ni con direcciones de marcas reales.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { QUIZ_CASES, RESULT_BANDS, isCorrect, resultBand, shuffled } from '../src/components/freeTools/phishingQuiz.js'

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

console.log('quiz de phishing')

test('hay correos de los dos tipos y ninguno repetido', () => {
  const ids = QUIZ_CASES.map((quizCase) => quizCase.id)
  assert.equal(new Set(ids).size, ids.length)
  assert.ok(QUIZ_CASES.filter((quizCase) => quizCase.isPhishing).length >= 2)
  assert.ok(QUIZ_CASES.filter((quizCase) => !quizCase.isPhishing).length >= 2)
  assert.ok(QUIZ_CASES.some((quizCase) => quizCase.isPhishing) && QUIZ_CASES.some((quizCase) => !quizCase.isPhishing))
})

test('cada correo trae una dirección y, si lleva enlace, un destino', () => {
  for (const quizCase of QUIZ_CASES) {
    assert.match(quizCase.address, /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/, quizCase.id)
    if (quizCase.linkUrl !== null) assert.match(quizCase.linkUrl, /^https?:\/\/\S+$/, quizCase.id)
    assert.ok(quizCase.clueCount >= 2, quizCase.id)
  }
})

test('el enlace de un correo legítimo es del mismo dominio que su remitente, y el de uno falso no', () => {
  const domainOf = (url) => new URL(url).hostname.split('.').slice(-2).join('.')
  for (const quizCase of QUIZ_CASES.filter((candidate) => candidate.linkUrl)) {
    const sameDomain = domainOf(quizCase.linkUrl) === quizCase.address.split('@')[1].split('.').slice(-2).join('.')
    assert.equal(sameDomain, !quizCase.isPhishing, quizCase.id)
  }
})

test('ningún correo usa un dominio de una marca real conocida', () => {
  const realBrands = /(correos|dhl|seur|ups|fedex|santander|bbva|caixa|paypal|amazon|apple|google|microsoft|netflix|ebay|mercadolibre|aliexpress)/i
  for (const quizCase of QUIZ_CASES) assert.ok(!realBrands.test(`${quizCase.address} ${quizCase.linkUrl ?? ''}`), quizCase.id)
})

test('corregir: solo acierta quien coincide con la solución', () => {
  const phishing = { isPhishing: true }
  const legit = { isPhishing: false }
  assert.equal(isCorrect(phishing, 'phishing'), true)
  assert.equal(isCorrect(phishing, 'legit'), false)
  assert.equal(isCorrect(legit, 'legit'), true)
  assert.equal(isCorrect(legit, 'phishing'), false)
})

test('el barajado conserva los elementos, no toca la lista original y depende de la fuente', () => {
  const original = [1, 2, 3, 4, 5, 6]
  const result = shuffled(original, () => 0)
  assert.deepEqual([...result].sort(), original)
  assert.deepEqual(original, [1, 2, 3, 4, 5, 6])
  assert.notDeepEqual(result, original)
  assert.deepEqual(shuffled(original, () => 0.999999), original)
  assert.deepEqual(shuffled([], () => 0), [])
})

test('el resultado final tiene tres tramos', () => {
  assert.equal(resultBand(6, 6), 'perfect')
  assert.equal(resultBand(5, 6), 'good')
  assert.equal(resultBand(4, 6), 'good')
  assert.equal(resultBand(3, 6), 'weak')
  assert.equal(resultBand(0, 6), 'weak')
})

test('cada correo tiene todos sus textos en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.phishingQuiz
    for (const band of RESULT_BANDS) assert.ok(item.bands[band], `${code}: tramo ${band}`)
    for (const quizCase of QUIZ_CASES) {
      const texts = item.cases[quizCase.id]
      for (const key of ['name', 'subject', 'body', 'explanation']) assert.ok(texts?.[key], `${code}: ${quizCase.id}.${key}`)
      if (quizCase.linkUrl) assert.ok(texts.linkText, `${code}: ${quizCase.id}.linkText`)
      for (let clue = 1; clue <= quizCase.clueCount; clue += 1) assert.ok(texts.clues?.[clue], `${code}: ${quizCase.id}.clues.${clue}`)
      assert.equal(Object.keys(texts.clues).length, quizCase.clueCount, `${code}: ${quizCase.id} tiene pistas de más`)
    }
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
