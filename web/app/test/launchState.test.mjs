/**
 * Tests de `launchState.js`: qué funciones enseña la SPA según `GET /system/launch`.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Lo que se fija es la regla de «ante la duda, cerrado» (una respuesta que
 * falla o que no tiene la forma esperada lo cierra todo) y que la exención del
 * administrador principal coincide con la de la API.
 */

import assert from 'node:assert/strict'
import {
  CLOSED_LAUNCH_STATE,
  ROOT_EXEMPT_SURFACES,
  fetchLaunchState,
  isSurfaceOpen,
  parseLaunchState,
} from '../src/composables/launchState.js'

let failures = 0
async function test(name, fn) {
  try {
    await fn()
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
}

const OPEN_BODY = {
  mode: 'public',
  surfaces: {
    registration: true, pricing: true, thirdPartyScanners: true,
    campaigns: true, mailboxConnectors: true, externalAi: true,
  },
}

console.log('launchState')

await test('una respuesta válida se conserva', () => {
  const state = parseLaunchState(OPEN_BODY)
  assert.equal(state.mode, 'public')
  assert.equal(isSurfaceOpen(state, 'pricing'), true)
})

await test('un cuerpo sin la forma esperada lo cierra todo', () => {
  for (const body of [null, 'texto', {}, { mode: 'public' }, { mode: 'public', surfaces: null }]) {
    assert.equal(parseLaunchState(body), CLOSED_LAUNCH_STATE)
  }
})

await test('un interruptor que no es booleano cuenta como cerrado', () => {
  const state = parseLaunchState({ mode: 'public', surfaces: { pricing: 'true', campaigns: 1 } })
  assert.equal(isSurfaceOpen(state, 'pricing'), false)
  assert.equal(isSurfaceOpen(state, 'campaigns'), false)
})

await test('una superficie que no viene cuenta como cerrada', () => {
  assert.equal(isSurfaceOpen(parseLaunchState({ mode: 'public', surfaces: {} }), 'registration'), false)
})

await test('el estado inicial lo tiene todo cerrado', () => {
  for (const surface of Object.keys(OPEN_BODY.surfaces)) {
    assert.equal(isSurfaceOpen(CLOSED_LAUNCH_STATE, surface), false)
  }
})

await test('el administrador principal está exento solo donde la API lo exime', () => {
  assert.deepEqual([...ROOT_EXEMPT_SURFACES].sort(), ['campaigns', 'mailboxConnectors', 'thirdPartyScanners'])
  for (const surface of ROOT_EXEMPT_SURFACES) {
    assert.equal(isSurfaceOpen(CLOSED_LAUNCH_STATE, surface, true), true)
  }
  for (const surface of ['registration', 'pricing', 'externalAi']) {
    assert.equal(isSurfaceOpen(CLOSED_LAUNCH_STATE, surface, true), false)
  }
})

await test('si la petición falla, todo cerrado', async () => {
  const failingFetch = async () => { throw new Error('red caída') }
  assert.equal(await fetchLaunchState(failingFetch), CLOSED_LAUNCH_STATE)
})

await test('si el servidor responde con error, todo cerrado', async () => {
  const errorFetch = async () => ({ ok: false, json: async () => OPEN_BODY })
  assert.equal(await fetchLaunchState(errorFetch), CLOSED_LAUNCH_STATE)
})

await test('pide el estado sin caché', async () => {
  let requestedOptions
  const recordingFetch = async (_url, options) => {
    requestedOptions = options
    return { ok: true, json: async () => OPEN_BODY }
  }
  const state = await fetchLaunchState(recordingFetch)
  assert.equal(requestedOptions.cache, 'no-store')
  assert.equal(isSurfaceOpen(state, 'registration'), true)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
