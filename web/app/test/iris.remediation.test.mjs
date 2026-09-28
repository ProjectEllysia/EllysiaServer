/**
 * Test de los rótulos de las acciones sobre el buzón (`components/iris/remediation.js`).
 *
 * Fija que cada acción, estado y motivo de indisponibilidad tiene texto, y que
 * un valor desconocido cae en el rótulo genérico (CONVENCIONES.md § 12.2).
 *
 *   node web/app/test/iris.remediation.test.mjs
 */

import { readFileSync } from 'node:fs'
import { createI18n } from 'vue-i18n'
import { isActionInFlight, mailboxActionKey, mailboxActionStatusKey, unavailableReasonKey } from '../src/components/iris/remediation.js'

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

console.log('\nacciones')
for (const action of ['quarantine', 'label', 'report_phishing', 'delete']) {
  eq(`${action} tiene rótulo`, te(mailboxActionKey(action)), true)
}
eq('cuarentena', t(mailboxActionKey('quarantine')), 'Poner en cuarentena')
eq('acción desconocida', t(mailboxActionKey('purge')), 'Desconocido')

console.log('\nestados')
for (const status of ['pending', 'running', 'succeeded', 'failed', 'rolled_back']) {
  eq(`${status} tiene rótulo`, te(mailboxActionStatusKey(status)), true)
}
eq('estado desconocido', t(mailboxActionStatusKey('queued')), 'Desconocido')
eq('pendiente sigue en curso', isActionInFlight({ status: 'pending' }), true)
eq('hecha ya no', isActionInFlight({ status: 'succeeded' }), false)

console.log('\nmotivos')
for (const reason of ['not_from_mailbox', 'connection_gone', 'reauth_required', 'missing_scope']) {
  eq(`${reason} tiene texto`, te(unavailableReasonKey(reason)), true)
}
eq('se puede actuar', unavailableReasonKey(null), null)
eq('motivo desconocido', t(unavailableReasonKey('quota')), 'Desconocido')

console.log(`\n${passed} correctos, ${failed} fallidos`)
if (failed) process.exit(1)
