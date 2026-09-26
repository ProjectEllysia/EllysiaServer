/**
 * Test de los rótulos de documentos de Hygeia (`components/hygeia/documents.js`).
 *
 *   node web/app/test/hygeia.documents.test.mjs
 */

import { readFileSync } from 'node:fs'
import { createI18n } from 'vue-i18n'
import {
  describeDocument, describePeriod, documentStatusOf, hasActiveDocuments,
} from '../src/components/hygeia/documents.js'

// Los rótulos salen de los ficheros de idioma: se comprueban en castellano.
const spanish = JSON.parse(readFileSync(new URL('../src/i18n/locales/es.json', import.meta.url), 'utf-8'))
const { t } = createI18n({ legacy: false, locale: 'es', messages: { es: spanish } }).global

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

console.log('\nestados')

eq('cada estado conocido tiene su rótulo',
  ['pending', 'running', 'done', 'error'].map((status) => t(documentStatusOf(status).labelKey)),
  ['En cola', 'Generándose', 'Listo', 'Ha fallado'])
// Un estado nuevo del servidor no puede pintarse en crudo.
eq('un estado desconocido cae en un rótulo genérico',
  documentStatusOf('archived'), { labelKey: 'common.unknown', isActive: false })
check('en cola y generándose son activos', hasActiveDocuments([{ status: 'done' }, { status: 'running' }]))
check('listos y fallidos no lo son', !hasActiveDocuments([{ status: 'done' }, { status: 'error' }]))
check('una lista vacía o ausente no lo es', !hasActiveDocuments([]) && !hasActiveDocuments(undefined))

console.log('\nperiodos')

eq('horas', describePeriod('24h', t), 'últimas 24 horas')
eq('días', describePeriod('7d', t), 'últimos 7 días')
eq('singular de hora', describePeriod('1h', t), 'última hora')
eq('singular de día', describePeriod('1d', t), 'último día')
eq('sin periodo no hay frase', describePeriod(undefined, t), '')
eq('un periodo ilegible tampoco', describePeriod('forever', t), '')

console.log('\ntítulos')

eq('resumen de un activo',
  describeDocument({ kind: 'stats-csv', format: 'csv',
    parameters: { dataset: 'summary', scopeLabel: 'web-01', period: '7d' } }, t),
  { title: 'Estadísticas de «web-01»', detail: 'últimos 7 días' })
eq('etiqueta',
  describeDocument({ kind: 'stats-csv', format: 'csv',
    parameters: { dataset: 'tag-stats', scopeLabel: 'Producción', period: '24h' } }, t),
  { title: 'Estadísticas de la etiqueta «Producción»', detail: 'últimas 24 horas' })
eq('ranking con el nombre de la métrica, no su clave',
  describeDocument({ kind: 'stats-csv', format: 'csv',
    parameters: { dataset: 'ranking', metric: 'cpuPct', period: '30d' } }, t).title,
  'Ranking del parque por CPU')
eq('el panorama no tiene periodo',
  describeDocument({ kind: 'stats-csv', format: 'csv', parameters: { dataset: 'overview' } }, t),
  { title: 'Panorama del parque', detail: '' })
eq('inventario propio',
  describeDocument({ kind: 'inventory-pdf', format: 'pdf',
    parameters: { scope: 'user', includeSoftware: false } }, t),
  { title: 'Inventario de mis activos', detail: '' })
eq('inventario de la organización con software',
  describeDocument({ kind: 'inventory-pdf', format: 'pdf',
    parameters: { scope: 'organization', includeSoftware: true } }, t),
  { title: 'Inventario de la organización', detail: 'con software instalado' })
eq('un tipo desconocido tiene un título genérico',
  describeDocument({ kind: 'slides', format: 'pptx', parameters: {} }, t),
  { title: 'Documento', detail: '' })

console.log(`\n${passed} pasados, ${failed} fallidos`)
process.exit(failed ? 1 : 0)
