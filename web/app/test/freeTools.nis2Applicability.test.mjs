/**
 * «¿Me aplica NIS2?»: el tamaño según la Recomendación 2003/361/CE y las reglas de los artículos 2 y 3
 * de la directiva, con un caso por cada anexo, por debajo y por encima de los umbrales y cada excepción.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  ACTIVITIES,
  OUTCOME_ESSENTIAL,
  OUTCOME_IMPORTANT,
  OUTCOME_NOT_APPLICABLE,
  OUTCOME_UNCLASSIFIED,
  assess,
  companySize,
  findActivity,
  parseAmount,
} from '../src/components/freeTools/nis2Applicability.js'

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

const base = { hasEuActivity: true, activityId: 'I.3', employees: 300, turnover: null, balance: null }
const ask = (changes) => assess({ ...base, ...changes })

console.log('tamaño')

test('250 personas o más es grande; menos de 50 con 10 M€ o menos es pequeña', () => {
  assert.equal(companySize({ employees: 250, turnover: null, balance: null }), 'large')
  assert.equal(companySize({ employees: 20, turnover: 2, balance: null }), 'small')
  assert.equal(companySize({ employees: 20, turnover: null, balance: 9 }), 'small')
})

test('se es grande solo si se superan a la vez 50 M€ de facturación y 43 M€ de balance', () => {
  assert.equal(companySize({ employees: 100, turnover: 60, balance: 50 }), 'large')
  assert.equal(companySize({ employees: 100, turnover: 60, balance: 40 }), 'medium')
  assert.equal(companySize({ employees: 100, turnover: 40, balance: 90 }), 'medium')
})

test('con 50 personas o más y sin cifras se sabe que no es pequeña, pero no si supera el tope de mediana', () => {
  assert.equal(companySize({ employees: 120, turnover: null, balance: null }), 'atLeastMedium')
  assert.equal(companySize({ employees: 120, turnover: 20, balance: null }), 'medium')
})

test('con menos de 50 personas y cifras por encima de 10 M€ es mediana; sin cifras, no se sabe', () => {
  assert.equal(companySize({ employees: 30, turnover: 15, balance: 12 }), 'medium')
  assert.equal(companySize({ employees: 30, turnover: null, balance: null }), null)
  assert.equal(companySize({ employees: null, turnover: 5, balance: 5 }), null)
})

test('las cifras admiten coma y punto, y rechazan lo que no es un importe', () => {
  assert.equal(parseAmount('12,5'), 12.5)
  assert.equal(parseAmount(' 7.25 '), 7.25)
  assert.equal(parseAmount(''), null)
  assert.equal(parseAmount('-3'), undefined)
  assert.equal(parseAmount('mucho'), undefined)
})

console.log('anexos I y II')

test('anexo I: grande es esencial; mediana, importante; pequeña, no le aplica', () => {
  assert.equal(ask({ employees: 400 }).outcome, OUTCOME_ESSENTIAL)
  assert.equal(ask({ employees: 120, turnover: 20, balance: 15 }).outcome, OUTCOME_IMPORTANT)
  assert.equal(ask({ employees: 20, turnover: 3, balance: 2 }).outcome, OUTCOME_NOT_APPLICABLE)
})

test('anexo II: mediana o grande es importante, nunca esencial; pequeña, no le aplica', () => {
  assert.equal(ask({ activityId: 'II.4', employees: 400 }).outcome, OUTCOME_IMPORTANT)
  assert.equal(ask({ activityId: 'II.4', employees: 120, turnover: 20, balance: 15 }).outcome, OUTCOME_IMPORTANT)
  assert.equal(ask({ activityId: 'II.4', employees: 20, turnover: 3, balance: 2 }).outcome, OUTCOME_NOT_APPLICABLE)
})

test('en el anexo I, una empresa de 50 a 249 personas sin cifras no se puede clasificar: faltan datos', () => {
  assert.deepEqual(ask({ employees: 120 }), { missing: ['size'] })
  assert.equal(ask({ activityId: 'II.4', employees: 120 }).outcome, OUTCOME_IMPORTANT)
})

test('una actividad que no está en los anexos no le aplica, con el aviso de la cadena de suministro', () => {
  const result = ask({ activityId: null })
  assert.equal(result.outcome, OUTCOME_NOT_APPLICABLE)
  assert.ok(result.reasons.includes('noAnnexActivity'))
  assert.ok(result.caveats.includes('supplyChain'))
})

test('sin actividad en la Unión no le aplica, aunque sea de un anexo y grande', () => {
  assert.equal(ask({ hasEuActivity: false }).outcome, OUTCOME_NOT_APPLICABLE)
})

console.log('excepciones por tipo de servicio')

test('DNS y registros de dominio de primer nivel son esenciales sea cual sea su tamaño', () => {
  for (const activityId of ['I.8.dns', 'I.8.tld']) {
    assert.equal(ask({ activityId, employees: 3, turnover: 0.2, balance: 0.1 }).outcome, OUTCOME_ESSENTIAL)
  }
})

test('un prestador de servicios de confianza es esencial si está cualificado e importante si no, sea cual sea su tamaño', () => {
  const tiny = { activityId: 'I.8.trust', employees: 2, turnover: 0.1, balance: 0.1 }
  assert.equal(ask({ ...tiny, isQualifiedTrust: true }).outcome, OUTCOME_ESSENTIAL)
  assert.equal(ask({ ...tiny, isQualifiedTrust: false }).outcome, OUTCOME_IMPORTANT)
})

test('un proveedor de comunicaciones electrónicas públicas es esencial si es mediano o grande e importante si es pequeño', () => {
  assert.equal(ask({ activityId: 'I.8.publicNetwork', employees: 120, turnover: 20, balance: 15 }).outcome, OUTCOME_ESSENTIAL)
  assert.equal(ask({ activityId: 'I.8.publicService', employees: 10, turnover: 1, balance: 1 }).outcome, OUTCOME_IMPORTANT)
  assert.equal(ask({ activityId: 'I.8.publicNetwork', employees: 120 }).outcome, OUTCOME_ESSENTIAL)
})

test('la Administración central es esencial; la regional, importante con el aviso de que depende del Estado', () => {
  assert.equal(ask({ activityId: 'I.10.central', employees: 5, turnover: null, balance: null }).outcome, OUTCOME_ESSENTIAL)
  const regional = ask({ activityId: 'I.10.regional', employees: 5 })
  assert.equal(regional.outcome, OUTCOME_IMPORTANT)
  assert.ok(regional.caveats.includes('regionalAdministration'))
})

test('una entidad crítica es esencial aunque no sea de un anexo ni de tamaño suficiente', () => {
  assert.equal(ask({ activityId: null, employees: 4, turnover: 0.3, balance: 0.2, isCriticalEntity: true }).outcome, OUTCOME_ESSENTIAL)
})

test('identificada por un Estado, o registradora de dominios, le aplica sin que la directiva fije su categoría', () => {
  const tiny = { activityId: null, employees: 4, turnover: 0.3, balance: 0.2 }
  assert.equal(ask({ ...tiny, isIdentifiedByState: true }).outcome, OUTCOME_UNCLASSIFIED)
  assert.equal(ask({ ...tiny, isDomainRegistrar: true }).outcome, OUTCOME_UNCLASSIFIED)
})

test('el resultado más exigente gana: una pequeña de un anexo identificada por el Estado no baja de «le aplica»', () => {
  const result = ask({ employees: 5, turnover: 0.5, balance: 0.4, isIdentifiedByState: true })
  assert.equal(result.outcome, OUTCOME_UNCLASSIFIED)
})

test('un resultado que le aplica avisa de que la transposición española no está publicada', () => {
  assert.ok(ask({ employees: 400 }).caveats.includes('spainTransposition'))
})

console.log('datos')

test('cada actividad del JSON tiene anexo, nombre en los dos idiomas y regla conocida; los id no se repiten', () => {
  const rules = new Set([null, 'dns_or_tld', 'trust', 'public_comms', 'central_admin', 'regional_admin'])
  assert.equal(new Set(ACTIVITIES.map((a) => a.id)).size, ACTIVITIES.length)
  for (const activity of ACTIVITIES) {
    assert.ok(['I', 'II'].includes(activity.annex), activity.id)
    assert.ok(activity.es && activity.en && activity.sector.es && activity.sector.en, activity.id)
    assert.ok(rules.has(activity.rule), activity.id)
  }
  assert.ok(findActivity('I.8.dns'))
})

test('el anexo I trae once sectores y el II siete', () => {
  const sectors = (annex) => new Set(ACTIVITIES.filter((a) => a.annex === annex).map((a) => a.sector.id)).size
  assert.equal(sectors('I'), 11)
  assert.equal(sectors('II'), 7)
})

test('las reglas del dato coinciden con las del borrador de la directiva en el repositorio', () => {
  // El borrador vive en la API: en el despliegue del SPA no está, y la prueba solo se hace donde esté.
  let draft
  try {
    draft = JSON.parse(readFileSync(new URL('../../../API/src/modules/features/eunomia/catalog/nis2/borrador/nis2-estructura.json', import.meta.url), 'utf8'))
  } catch {
    return
  }
  assert.equal(draft.directive.annexI.sectors.length, new Set(ACTIVITIES.filter((a) => a.annex === 'I').map((a) => a.sector.id)).size)
  assert.equal(draft.directive.annexII.sectors.length, new Set(ACTIVITIES.filter((a) => a.annex === 'II').map((a) => a.sector.id)).size)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
console.log('\nTodos los tests de «¿Me aplica NIS2?» pasaron')
