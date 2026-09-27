/**
 * Test de los ayudantes de indicadores de Iris (`components/iris/indicators.js`).
 *
 * Fija que un indicador se neutraliza antes de pintarlo (nunca un enlace
 * vivo) y que los tipos de indicador y las señales de campaña dan con su
 * rótulo, o con uno genérico si el servidor manda un valor que la interfaz
 * aún no conoce (CONVENCIONES.md § 12.2).
 *
 *   node web/app/test/iris.indicators.test.mjs
 */

import { readFileSync } from 'node:fs'
import { createI18n } from 'vue-i18n'
import { campaignSignalKey, contactDeviationKey, defang, describeDomainContext, indicatorKindKey } from '../src/components/iris/indicators.js'

const spanish = JSON.parse(readFileSync(new URL('../src/i18n/locales/es.json', import.meta.url), 'utf-8'))
const { t, te } = createI18n({ legacy: false, locale: 'es', messages: { es: spanish } }).global

let passed = 0
let failed = 0
function eq(name, actual, expected) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  if (a === e) { passed++; console.log(`  ✓ ${name}`) }
  else { failed++; console.error(`  ✗ ${name} — ${a} !== ${e}`) }
}

console.log('\ndefang')
eq('URL', defang('https://evil.example/login'), 'hxxps://evil[.]example/login')
eq('dirección', defang('ana@evil.example'), 'ana[at]evil[.]example')
eq('hash intacto', defang('ab12'), 'ab12')

console.log('\nrótulos')
eq('tipo de indicador', t(indicatorKindKey('email')), 'Dirección')
eq('tipo desconocido', t(indicatorKindKey('asn')), 'Desconocido')
eq('señal', t(campaignSignalKey('hash')), 'adjunto idéntico')
eq('señal desconocida', t(campaignSignalKey('embedding')), 'Desconocido')
eq('desviación de contacto',
  t(contactDeviationKey('display_name_reuse'), { sender: 'x@evil.example', name: 'Juan', habitual: 'juan@corp.example', count: 3 }),
  '«Juan» escribe desde x@evil.example, pero ese nombre lo usa un contacto habitual tuyo, juan@corp.example (3 mensajes legítimos).')
eq('desviación desconocida', contactDeviationKey('embedding'), 'iris.report.deviation.other')

console.log('\ncontexto de dominio')
eq('reciente', describeDomainContext({ status: 'ok', ageDays: 3, isRecentlyRegistered: true, registrar: 'R', networkName: 'NET', country: 'US', asn: 'AS1' }, t),
  'Registrado hace 3 días (reciente) · Registrador: R · Red NET (US) · AS1')
eq('neutro', describeDomainContext({ status: 'unavailable' }, t), 'El registro no ha respondido; no se puede decir nada de este dominio.')
eq('sin respuesta', describeDomainContext(null, t), 'El registro no ha respondido; no se puede decir nada de este dominio.')

console.log('\ncada clave que puede devolver el módulo existe en el diccionario')
const keys = [
  ...['domain', 'url', 'ip', 'email', 'hash'].map(indicatorKindKey),
  ...['url', 'hash', 'template', 'subject', 'sender', 'domain', 'brand'].map(campaignSignalKey),
  ...['display_name_reuse', 'address_domain_change', 'unknown'].map(contactDeviationKey),
]
eq('sin claves huérfanas', keys.filter(key => !te(key)), [])

console.log(`\n${passed} pasados, ${failed} fallidos\n`)
process.exit(failed === 0 ? 0 : 1)
