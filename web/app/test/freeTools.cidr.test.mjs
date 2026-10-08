/**
 * Tests de la calculadora de rangos de red gratuita
 * (`src/components/freeTools/cidr.js`).
 *
 * Node puro, sin framework. Se fijan los casos que más se equivocan a mano: los
 * `/31` y `/32`, las máscaras no contiguas, la aritmética de 32 bits sin signo
 * (que en JavaScript se rompe con los `|` y `<<`) y la clase de cada rango.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  ADDRESS_KINDS,
  CIDR_ERRORS,
  addressToInt,
  classifyAddress,
  describeNetwork,
  intToAddress,
  parseNetwork,
  splitNetwork,
} from '../src/components/freeTools/cidr.js'

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

const parsed = (text) => {
  const result = parseNetwork(text)
  assert.ok(result.ok, `${text}: ${result.reason}`)
  return describeNetwork(result.address, result.prefix)
}

console.log('direcciones')

test('una dirección va y viene de entero sin perder el signo', () => {
  assert.equal(addressToInt('0.0.0.0'), 0)
  assert.equal(addressToInt('255.255.255.255'), 4294967295)
  assert.equal(addressToInt('192.168.1.10'), 3232235786)
  for (const dotted of ['10.0.0.1', '128.0.0.0', '255.255.255.0', '172.16.5.4']) assert.equal(intToAddress(addressToInt(dotted)), dotted)
})

test('lo que no son cuatro octetos entre 0 y 255 no es dirección', () => {
  for (const wrong of ['', '1.2.3', '1.2.3.4.5', '256.1.1.1', '1.2.3.-4', '1.2.3.a', '1..3.4', '01234.1.1.1']) assert.equal(addressToInt(wrong), null, wrong)
})

console.log('lectura')

test('se leen la notación CIDR, la dirección suelta y la dirección con máscara', () => {
  assert.deepEqual(parseNetwork('10.0.0.0/22'), { ok: true, address: addressToInt('10.0.0.0'), prefix: 22 })
  assert.deepEqual(parseNetwork('  192.168.1.5  '), { ok: true, address: addressToInt('192.168.1.5'), prefix: 32 })
  assert.deepEqual(parseNetwork('10.0.0.0 255.255.252.0'), { ok: true, address: addressToInt('10.0.0.0'), prefix: 22 })
  assert.deepEqual(parseNetwork('10.0.0.0/255.255.252.0'), { ok: true, address: addressToInt('10.0.0.0'), prefix: 22 })
  assert.deepEqual(parseNetwork('10.0.0.0 / 24'), { ok: true, address: addressToInt('10.0.0.0'), prefix: 24 })
  assert.equal(parseNetwork('0.0.0.0/0').prefix, 0)
  assert.equal(parseNetwork('1.1.1.1 255.255.255.255').prefix, 32)
  assert.equal(parseNetwork('1.1.1.1 0.0.0.0').prefix, 0)
})

test('cada texto inválido da su motivo', () => {
  assert.deepEqual(parseNetwork(''), { ok: false, reason: 'format' })
  assert.deepEqual(parseNetwork(undefined), { ok: false, reason: 'format' })
  assert.deepEqual(parseNetwork('hola'), { ok: false, reason: 'format' })
  assert.deepEqual(parseNetwork('10.0.0/24'), { ok: false, reason: 'format' })
  assert.deepEqual(parseNetwork('300.0.0.1/24'), { ok: false, reason: 'octet' })
  assert.deepEqual(parseNetwork('10.0.0.0/33'), { ok: false, reason: 'prefix' })
  assert.deepEqual(parseNetwork('10.0.0.0/255.0.255.0'), { ok: false, reason: 'mask' })
  assert.deepEqual(parseNetwork('10.0.0.0 255.255.255.1'), { ok: false, reason: 'mask' })
  assert.deepEqual(parseNetwork('10.0.0.0/x'), { ok: false, reason: 'mask' })
})

console.log('cálculo')

test('un /24 clásico', () => {
  const network = parsed('192.168.1.77/24')
  assert.equal(network.network, '192.168.1.0')
  assert.equal(network.broadcast, '192.168.1.255')
  assert.equal(network.netmask, '255.255.255.0')
  assert.equal(network.wildcard, '0.0.0.255')
  assert.equal(network.firstHost, '192.168.1.1')
  assert.equal(network.lastHost, '192.168.1.254')
  assert.equal(network.total, 256)
  assert.equal(network.usable, 254)
  assert.equal(network.cidr, '192.168.1.0/24')
})

test('una dirección escrita a medias en la red se lleva a la dirección de red', () => {
  assert.equal(parsed('10.0.3.9/22').network, '10.0.0.0')
  assert.equal(parsed('10.0.3.9/22').broadcast, '10.0.3.255')
  assert.equal(parsed('10.0.3.9/22').usable, 1022)
})

test('un /31 tiene dos equipos utilizables y un /32 uno', () => {
  const pair = parsed('10.0.0.4/31')
  assert.deepEqual([pair.firstHost, pair.lastHost, pair.usable, pair.total], ['10.0.0.4', '10.0.0.5', 2, 2])
  const single = parsed('203.0.113.9/32')
  assert.deepEqual([single.firstHost, single.lastHost, single.usable, single.total], ['203.0.113.9', '203.0.113.9', 1, 1])
})

test('los extremos no se desbordan: /0 y direcciones altas', () => {
  const all = parsed('0.0.0.0/0')
  assert.deepEqual([all.network, all.broadcast, all.netmask, all.total], ['0.0.0.0', '255.255.255.255', '0.0.0.0', 4294967296])
  const top = parsed('255.255.255.254/31')
  assert.deepEqual([top.network, top.broadcast], ['255.255.255.254', '255.255.255.255'])
  assert.equal(parsed('200.1.2.3/1').network, '128.0.0.0')
})

console.log('clases de dirección')

test('cada rango reservado se reconoce y lo demás es público', () => {
  const expected = {
    '0.1.2.3': 'unspecified', '10.20.30.40': 'private', '172.16.0.1': 'private', '172.31.255.255': 'private',
    '172.32.0.1': 'public', '192.168.0.1': 'private', '100.64.0.1': 'cgnat', '100.128.0.1': 'public',
    '127.0.0.1': 'loopback', '169.254.1.1': 'linkLocal', '192.0.2.5': 'documentation', '224.0.0.1': 'multicast',
    '255.255.255.255': 'reserved', '8.8.8.8': 'public', '1.1.1.1': 'public',
  }
  for (const [address, kind] of Object.entries(expected)) assert.equal(classifyAddress(addressToInt(address)), kind, address)
})

test('un rango que mezcla clases se señala como mezcla', () => {
  assert.equal(parsed('10.0.0.0/8').kind, 'private')
  assert.equal(parsed('0.0.0.0/0').kind, 'mixed')
  assert.equal(parsed('8.8.8.0/24').kind, 'public')
})

console.log('subredes')

test('una red se parte en subredes iguales', () => {
  const result = splitNetwork(addressToInt('192.168.0.0'), 24, 26)
  assert.deepEqual(result, { count: 4, subnets: ['192.168.0.0/26', '192.168.0.64/26', '192.168.0.128/26', '192.168.0.192/26'], hidden: 0 })
})

test('si hay más subredes que el límite, se cuentan las que no se listan', () => {
  const result = splitNetwork(addressToInt('10.0.0.0'), 16, 24, 5)
  assert.equal(result.count, 256)
  assert.equal(result.subnets.length, 5)
  assert.equal(result.hidden, 251)
  assert.equal(result.subnets[4], '10.0.4.0/24')
})

test('un prefijo de subred que no es mayor, o pasa de 32, no se acepta', () => {
  for (const bad of [24, 20, 33, 1.5, NaN]) assert.equal(splitNetwork(addressToInt('10.0.0.0'), 24, bad), null, String(bad))
})

test('cada motivo de error y cada clase tienen texto en los dos idiomas', () => {
  for (const [code, dictionary] of locales) {
    const item = dictionary.freeTools.items.cidrCalculator
    for (const reason of CIDR_ERRORS) assert.ok(item.errors[reason], `${code}: error ${reason}`)
    for (const kind of ADDRESS_KINDS) assert.ok(item.kinds[kind], `${code}: clase ${kind}`)
  }
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
