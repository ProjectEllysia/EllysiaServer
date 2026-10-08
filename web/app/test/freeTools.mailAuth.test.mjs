/**
 * Tests del comprobador de SPF, DKIM y DMARC gratuito
 * (`src/components/freeTools/mailAuth.js`).
 *
 * Node puro, sin framework. El DNS se simula con un `fetch` falso: aquí no sale
 * ninguna petición. Se fija que se lee bien lo que la gente pega, que cada
 * registro dice lo que tiene que decir y que un fallo del primer servicio de DNS
 * no se confunde con «el dominio no tiene registro».
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  FINDING_CODES,
  FINDING_LEVELS,
  analyseDkim,
  analyseDmarc,
  analyseSpf,
  checkMailAuthentication,
  estimateRsaBits,
  joinTxtData,
  lookupTxt,
  normalizeDomain,
  normalizeSelector,
  parseDnsAnswer,
  parentDomains,
  parseTags,
  worstLevel,
} from '../src/components/freeTools/mailAuth.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const locales = ['es', 'en'].map((code) => [code, JSON.parse(readFileSync(`${appRoot}src/i18n/locales/${code}.json`, 'utf-8'))])

let failures = 0
function test(name, fn) {
  const finish = (error) => {
    if (!error) return console.log(`  ✓ ${name}`)
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
  try {
    const result = fn()
    if (result?.then) return result.then(() => finish(), finish)
    finish()
  } catch (error) {
    finish(error)
  }
}

const codes = (analysis) => analysis.findings.map((finding) => finding.code)
const keyOfBytes = (length) => Buffer.alloc(length, 7).toString('base64')

console.log('dominio y selector')

test('se saca el dominio de lo que la gente pega', () => {
  const expected = {
    'ejemplo.com': 'ejemplo.com',
    '  EJEMPLO.com  ': 'ejemplo.com',
    'ana@ejemplo.com': 'ejemplo.com',
    'Ana Pérez <ana@correo.ejemplo.com>': null,
    'https://www.ejemplo.com/ruta?x=1#y': 'www.ejemplo.com',
    'http://ejemplo.com:8080/': 'ejemplo.com',
    'ejemplo.com.': 'ejemplo.com',
    'mañana.es': 'xn--maana-pta.es',
  }
  for (const [text, domain] of Object.entries(expected)) assert.equal(normalizeDomain(text), domain, text)
})

test('lo que no es un nombre de dominio se rechaza', () => {
  for (const wrong of ['', '   ', 'localhost', 'ejemplo', '-ejemplo.com', 'ejem plo.com', 'ejemplo..com', 'a.b', '1.2.3.4', 'ejemplo.c0m', undefined, 42]) {
    assert.equal(normalizeDomain(wrong), null, String(wrong))
  }
  assert.equal(normalizeDomain(`${'a'.repeat(64)}.com`), null)
})

test('el selector acepta lo que cabe en una etiqueta DNS', () => {
  assert.equal(normalizeSelector(' Google '), 'google')
  assert.equal(normalizeSelector('selector1'), 'selector1')
  assert.equal(normalizeSelector('s_2024-06.a'), 's_2024-06.a')
  for (const wrong of ['', ' ', '-x', 'a b', 'a/b', 'a'.repeat(64), undefined]) assert.equal(normalizeSelector(wrong), null, String(wrong))
})

console.log('respuestas de DNS')

test('un TXT partido en cadenas se une', () => {
  assert.equal(joinTxtData('"v=DKIM1; p=MIIB" "IjAN"'), 'v=DKIM1; p=MIIBIjAN')
  assert.equal(joinTxtData('"v=spf1 -all"'), 'v=spf1 -all')
  assert.equal(joinTxtData('v=spf1 -all'), 'v=spf1 -all')
  assert.equal(joinTxtData('"dice \\"hola\\""'), 'dice "hola"')
})

test('la respuesta distingue registros, nombre inexistente y fallo', () => {
  const ok = parseDnsAnswer({ Status: 0, Answer: [{ type: 5, data: 'otro.' }, { type: 16, data: '"v=spf1 -all"' }] })
  assert.deepEqual(ok, { status: 'ok', records: ['v=spf1 -all'] })
  assert.deepEqual(parseDnsAnswer({ Status: 0 }), { status: 'ok', records: [] })
  assert.deepEqual(parseDnsAnswer({ Status: 3 }), { status: 'nxdomain', records: [] })
  assert.deepEqual(parseDnsAnswer({ Status: 2 }), { status: 'error', records: [] })
  assert.deepEqual(parseDnsAnswer(null), { status: 'error', records: [] })
})

await test('si el primer servicio falla se prueba el segundo, y si fallan los dos se lanza', async () => {
  const asked = []
  const flaky = async (url) => {
    asked.push(url)
    if (url.startsWith('https://cloudflare-dns.com')) throw new Error('sin red')
    return { ok: true, json: async () => ({ Status: 0, Answer: [{ type: 16, data: '"v=spf1 -all"' }] }) }
  }
  assert.deepEqual(await lookupTxt('ejemplo.com', flaky), { status: 'ok', records: ['v=spf1 -all'] })
  assert.equal(asked.length, 2)
  assert.ok(asked[0].includes('name=ejemplo.com&type=TXT'))
  await assert.rejects(() => lookupTxt('ejemplo.com', async () => ({ ok: false, json: async () => ({}) })), /sin respuesta/)
})

await test('«el nombre no existe» es una respuesta y no obliga a probar otro servicio', async () => {
  let calls = 0
  const result = await lookupTxt('no-existe.example', async () => { calls += 1; return { ok: true, json: async () => ({ Status: 3 }) } })
  assert.equal(result.status, 'nxdomain')
  assert.equal(calls, 1)
})

console.log('SPF')

test('sin registro SPF, o con dos, es un fallo', () => {
  assert.deepEqual(codes(analyseSpf(['google-site-verification=abc'])), ['spfMissing'])
  assert.ok(codes(analyseSpf(['v=spf1 -all', 'v=spf1 ~all'])).includes('spfMultiple'))
})

test('cada final del registro dice lo que corresponde', () => {
  const cases = { '-all': ['spfStrict', 'ok'], '~all': ['spfSoftfail', 'info'], '?all': ['spfNeutral', 'warn'], '+all': ['spfOpen', 'bad'], all: ['spfOpen', 'bad'] }
  for (const [ending, [code, level]] of Object.entries(cases)) {
    const { findings } = analyseSpf([`v=spf1 ip4:203.0.113.0/24 ${ending}`])
    assert.deepEqual([findings[0].code, findings[0].level], [code, level], ending)
  }
  assert.deepEqual(codes(analyseSpf(['v=spf1 include:_spf.ejemplo.net'])), ['spfNoAll'])
  assert.deepEqual(codes(analyseSpf(['v=spf1 redirect=_spf.ejemplo.net'])), ['spfRedirect'])
})

test('se cuentan las consultas de DNS y se avisa al pasar de diez', () => {
  const include = (count) => `v=spf1 ${Array.from({ length: count }, (_, index) => `include:s${index}.ejemplo.net`).join(' ')} -all`
  assert.ok(!codes(analyseSpf([include(10)])).includes('spfTooManyLookups'))
  const over = analyseSpf([include(11)]).findings.find((finding) => finding.code === 'spfTooManyLookups')
  assert.deepEqual(over.params, { count: 11 })
  // `all`, `ip4` e `ip6` no cuestan consulta; `a`, `mx`, `exists` y `redirect` sí.
  assert.ok(!codes(analyseSpf(['v=spf1 ip4:1.2.3.4 ip6:::1 -all'])).includes('spfTooManyLookups'))
  const mixed = `v=spf1 a mx:ejemplo.net exists:%{i}.ejemplo.net ${Array.from({ length: 8 }, (_, index) => `include:s${index}.net`).join(' ')} -all`
  assert.ok(codes(analyseSpf([mixed])).includes('spfTooManyLookups'))
})

test('ptr se señala como desaconsejado', () => {
  assert.ok(codes(analyseSpf(['v=spf1 ptr -all'])).includes('spfPtr'))
  assert.ok(!codes(analyseSpf(['v=spf1 ip4:1.2.3.4 -all'])).includes('spfPtr'))
})

console.log('DMARC')

test('etiquetas del registro', () => {
  assert.deepEqual(parseTags('v=DMARC1; p=reject ; RUA=mailto:a@b.es;;x'), { v: 'DMARC1', p: 'reject', rua: 'mailto:a@b.es' })
  assert.deepEqual(parseTags('p=none; p=reject'), { p: 'none' })
})

test('sin registro DMARC, o inválido, es un fallo', () => {
  assert.deepEqual(codes(analyseDmarc([])), ['dmarcMissing'])
  assert.deepEqual(codes(analyseDmarc(['v=spf1 -all'])), ['dmarcMissing'])
  assert.ok(codes(analyseDmarc(['v=DMARC1; p=rechazar'])).includes('dmarcInvalid'))
  assert.ok(codes(analyseDmarc(['v=DMARC1; rua=mailto:a@b.es'])).includes('dmarcInvalid'))
  assert.ok(codes(analyseDmarc(['v=DMARC1; p=reject', 'v=DMARC1; p=none'])).includes('dmarcMultiple'))
})

test('cada política dice lo que corresponde', () => {
  const policy = (record) => analyseDmarc([record]).findings[0]
  assert.deepEqual([policy('v=DMARC1; p=reject').code, policy('v=DMARC1; p=reject').level], ['dmarcReject', 'ok'])
  assert.deepEqual([policy('v=DMARC1; p=Quarantine').code, policy('v=DMARC1; p=Quarantine').level], ['dmarcQuarantine', 'ok'])
  assert.deepEqual([policy('v=DMARC1; p=none').code, policy('v=DMARC1; p=none').level], ['dmarcNone', 'warn'])
})

test('se avisa de subdominios más laxos, de aplicación parcial y de la falta de informes', () => {
  assert.ok(codes(analyseDmarc(['v=DMARC1; p=reject; sp=none'])).includes('dmarcSubdomainWeaker'))
  assert.ok(!codes(analyseDmarc(['v=DMARC1; p=quarantine; sp=reject'])).includes('dmarcSubdomainWeaker'))
  const partial = analyseDmarc(['v=DMARC1; p=quarantine; pct=25']).findings.find((finding) => finding.code === 'dmarcPartial')
  assert.deepEqual(partial.params, { percentage: 25 })
  assert.ok(!codes(analyseDmarc(['v=DMARC1; p=none; pct=25'])).includes('dmarcPartial'))
  assert.ok(codes(analyseDmarc(['v=DMARC1; p=reject'])).includes('dmarcNoReports'))
  assert.ok(!codes(analyseDmarc(['v=DMARC1; p=reject; rua=mailto:dmarc@ejemplo.com'])).includes('dmarcNoReports'))
})

console.log('DKIM')

test('el tamaño de una clave RSA se estima por su longitud', () => {
  assert.equal(estimateRsaBits(keyOfBytes(162)), 1024)
  assert.equal(estimateRsaBits(keyOfBytes(294)), 2048)
  assert.equal(estimateRsaBits(keyOfBytes(422)), 3072)
  assert.equal(estimateRsaBits(keyOfBytes(550)), 4096)
  assert.equal(estimateRsaBits('esto no es base64!!'), null)
})

test('sin registro, revocada, corta, válida o inválida', () => {
  assert.deepEqual(codes(analyseDkim([])), ['dkimMissing'])
  assert.deepEqual(codes(analyseDkim(['v=DKIM1; k=rsa; p='])), ['dkimRevoked'])
  const short = analyseDkim([`v=DKIM1; k=rsa; p=${keyOfBytes(162)}`]).findings[0]
  assert.deepEqual([short.code, short.params], ['dkimShortKey', { bits: 1024 }])
  const good = analyseDkim([`v=DKIM1; p=${keyOfBytes(294)}`]).findings[0]
  assert.deepEqual([good.code, good.level, good.params], ['dkimOk', 'ok', { bits: 2048 }])
  assert.deepEqual(codes(analyseDkim(['v=DKIM1; p=!!no!!'])), ['dkimInvalid'])
  assert.deepEqual(analyseDkim(['v=DKIM1; k=ed25519; p=' + keyOfBytes(32)]).findings[0].params, { bits: 256 })
})

test('el modo de pruebas se señala', () => {
  assert.ok(codes(analyseDkim([`v=DKIM1; t=y; p=${keyOfBytes(294)}`])).includes('dkimTestMode'))
  assert.ok(!codes(analyseDkim([`v=DKIM1; t=s; p=${keyOfBytes(294)}`])).includes('dkimTestMode'))
})

console.log('conjunto')

test('la gravedad de un conjunto es la más alta', () => {
  assert.equal(worstLevel([]), 'ok')
  assert.equal(worstLevel([{ level: 'ok' }, { level: 'info' }]), 'info')
  assert.equal(worstLevel([{ level: 'ok' }, { level: 'bad' }, { level: 'warn' }]), 'bad')
})

/** `fetch` falso que responde con los TXT que se le den por nombre. */
function fakeDns(byName) {
  return async (url) => {
    const name = new URL(url).searchParams.get('name')
    const records = byName[name]
    if (records === 'nxdomain') return { ok: true, json: async () => ({ Status: 3 }) }
    return { ok: true, json: async () => ({ Status: 0, Answer: (records ?? []).map((data) => ({ type: 16, data: `"${data}"` })) }) }
  }
}

await test('un dominio completo se comprueba entero', async () => {
  const fetchImplementation = fakeDns({
    'ejemplo.com': ['v=spf1 include:_spf.ejemplo.net -all'],
    '_dmarc.ejemplo.com': ['v=DMARC1; p=reject; rua=mailto:d@ejemplo.com'],
    'selector1._domainkey.ejemplo.com': [`v=DKIM1; p=${keyOfBytes(294)}`],
  })
  const result = await checkMailAuthentication({ domain: 'ejemplo.com', selector: 'selector1', fetchImplementation })
  assert.equal(result.exists, true)
  assert.deepEqual(codes(result.spf), ['spfStrict'])
  assert.deepEqual(codes(result.dmarc), ['dmarcReject'])
  assert.deepEqual(codes(result.dkim), ['dkimOk'])
})

await test('sin selector no se comprueba DKIM, y el dominio inexistente no da más resultados', async () => {
  const fetchImplementation = fakeDns({ 'ejemplo.com': [], '_dmarc.ejemplo.com': [], 'no-existe.example': 'nxdomain', '_dmarc.no-existe.example': 'nxdomain' })
  const result = await checkMailAuthentication({ domain: 'ejemplo.com', fetchImplementation })
  assert.equal(result.dkim, null)
  assert.deepEqual(codes(result.spf), ['spfMissing'])
  assert.deepEqual(codes(result.dmarc), ['dmarcMissing'])
  assert.deepEqual(await checkMailAuthentication({ domain: 'no-existe.example', fetchImplementation }), {
    domain: 'no-existe.example', exists: false, spf: null, dmarc: null, dkim: null,
  })
})

test('los dominios padre se listan del más cercano al más general', () => {
  assert.deepEqual(parentDomains('ejemplo.com'), [])
  assert.deepEqual(parentDomains('mail.ejemplo.com'), ['ejemplo.com'])
  assert.deepEqual(parentDomains('a.b.ejemplo.com'), ['b.ejemplo.com', 'ejemplo.com'])
})

await test('un subdominio sin DMARC propio hereda el del dominio padre y lo dice', async () => {
  const fetchImplementation = fakeDns({
    'mail.ejemplo.com': ['v=spf1 -all'],
    '_dmarc.mail.ejemplo.com': [],
    '_dmarc.ejemplo.com': ['v=DMARC1; p=reject; rua=mailto:d@ejemplo.com'],
  })
  const result = await checkMailAuthentication({ domain: 'mail.ejemplo.com', fetchImplementation })
  assert.deepEqual(codes(result.dmarc), ['dmarcInherited', 'dmarcReject'])
  assert.deepEqual(result.dmarc.findings[0].params, { domain: 'ejemplo.com' })
})

await test('si ni el subdominio ni sus padres tienen DMARC, falta', async () => {
  const fetchImplementation = fakeDns({ 'mail.ejemplo.com': [], '_dmarc.mail.ejemplo.com': [], '_dmarc.ejemplo.com': [] })
  assert.deepEqual(codes((await checkMailAuthentication({ domain: 'mail.ejemplo.com', fetchImplementation })).dmarc), ['dmarcMissing'])
})

test('cada hallazgo tiene texto en los dos idiomas, y cada gravedad su rótulo', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.mailAuthChecker
    for (const finding of FINDING_CODES) assert.ok(item.findings[finding], `${code}: ${finding}`)
    for (const level of FINDING_LEVELS) assert.ok(item.levels[level], `${code}: ${level}`)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
