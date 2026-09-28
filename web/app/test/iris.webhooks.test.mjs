/**
 * Test de los rótulos de webhooks de Iris (`components/iris/webhooks.js`).
 *
 * Fija que cada tipo de evento, estado de entrega y motivo de desactivación
 * da con su texto en castellano, y que un valor que el servidor añada sin que
 * la interfaz lo conozca cae en el rótulo genérico en vez de enseñarse en crudo
 * (CONVENCIONES.md § 12.2).
 *
 *   node web/app/test/iris.webhooks.test.mjs
 */

import { readFileSync } from 'node:fs'
import { createI18n } from 'vue-i18n'
import { deliveryStatusKey, disabledReasonKey, webhookEventKey } from '../src/components/iris/webhooks.js'

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

console.log('\ntipos de evento')
for (const eventType of ['analysis.finished', 'case.updated', 'campaign.detected', 'mailbox.reauth_required', 'ping']) {
  eq(`${eventType} tiene rótulo`, te(webhookEventKey(eventType)), true)
}
eq('análisis terminado', t(webhookEventKey('analysis.finished')), 'Análisis terminado')
eq('evento desconocido', t(webhookEventKey('user.deleted')), 'Desconocido')

console.log('\nestados de entrega')
for (const status of ['pending', 'delivering', 'delivered', 'failed']) {
  eq(`${status} tiene rótulo`, te(deliveryStatusKey(status)), true)
}
eq('fallida', t(deliveryStatusKey('failed')), 'No entregado')
eq('estado desconocido', t(deliveryStatusKey('bounced')), 'Desconocido')

console.log('\nmotivos de desactivación')
eq('sin motivo: lo apagó el usuario', t(disabledReasonKey(null)), 'Lo desactivaste tú.')
eq('fallos', te(disabledReasonKey('failures')), true)
eq('410', te(disabledReasonKey('gone')), true)
eq('motivo desconocido', t(disabledReasonKey('quota')), 'Desconocido')

console.log(`\n${passed} correctos, ${failed} fallidos`)
if (failed) process.exit(1)
