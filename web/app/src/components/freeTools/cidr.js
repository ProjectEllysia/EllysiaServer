/**
 * Lógica sin Vue de la calculadora de rangos de red gratuita
 * (`views/tools/themis/CidrCalculatorView.vue`), para poder probarla con `node`
 * a secas. Solo IPv4. Las direcciones se manejan como enteros sin signo de 32
 * bits y se convierten a texto al final.
 */

/** Motivos por los que un texto no es una red, con su rótulo en `freeTools.items.cidrCalculator.errors`. */
export const CIDR_ERRORS = Object.freeze(['format', 'octet', 'prefix', 'mask'])

/** Clases de dirección que reconoce `classifyAddress`, con su rótulo en `...cidrCalculator.kinds`. */
export const ADDRESS_KINDS = Object.freeze([
  'public', 'private', 'loopback', 'linkLocal', 'cgnat', 'multicast', 'reserved', 'documentation', 'unspecified', 'mixed',
])

/**
 * Convierte una dirección con puntos en un entero.
 *
 * @param {string} dotted - Cuatro octetos decimales separados por puntos.
 * @returns {number|null} El entero sin signo de 32 bits, o `null` si no son cuatro
 *   números enteros entre 0 y 255.
 */
export function addressToInt(dotted) {
  const parts = dotted.split('.')
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part))) return null
  const octets = parts.map(Number)
  if (octets.some((octet) => octet > 255)) return null
  return ((octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]) >>> 0
}

/**
 * Escribe un entero como dirección con puntos.
 *
 * @param {number} value - Entero sin signo de 32 bits.
 * @returns {string} Por ejemplo `192.168.0.1`.
 */
export function intToAddress(value) {
  return [24, 16, 8, 0].map((shift) => (value >>> shift) & 255).join('.')
}

/**
 * Máscara de red de un prefijo.
 *
 * @param {number} prefix - Bits de red, de 0 a 32.
 * @returns {number} La máscara como entero sin signo (`/24` → `0xFFFFFF00`).
 */
function maskOf(prefix) {
  return prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0
}

/**
 * Lee lo que escribe el usuario como una red.
 *
 * Acepta `10.0.0.0/22`, una dirección suelta (`10.0.0.5`, que es un `/32`) y una
 * dirección con máscara, separada por espacio o por barra (`10.0.0.0 255.255.252.0`).
 *
 * @param {unknown} text - Lo escrito. Se ignoran los espacios de los extremos.
 * @returns {{ok: true, address: number, prefix: number}|{ok: false, reason: string}}
 *   La dirección tal como se escribió (no se fuerza a la de red) y el prefijo, o el
 *   motivo del fallo, uno de `CIDR_ERRORS`. Un texto vacío da `{ok: false, reason: 'format'}`.
 */
export function parseNetwork(text) {
  const clean = typeof text === 'string' ? text.trim() : ''
  const parts = clean.split(/\s*\/\s*|\s+/)
  if (!clean || parts.length > 2) return { ok: false, reason: 'format' }
  const [addressText, suffix] = parts
  if (!/^[\d.]+$/.test(addressText)) return { ok: false, reason: 'format' }
  const address = addressToInt(addressText)
  if (address === null) return { ok: false, reason: addressText.split('.').length === 4 ? 'octet' : 'format' }
  if (suffix === undefined) return { ok: true, address, prefix: 32 }

  if (/^\d{1,2}$/.test(suffix)) {
    const prefix = Number(suffix)
    return prefix <= 32 ? { ok: true, address, prefix } : { ok: false, reason: 'prefix' }
  }
  const mask = addressToInt(suffix)
  if (mask === null) return { ok: false, reason: 'mask' }
  // Una máscara válida son unos seguidos de ceros: su complemento es 0…01…1.
  const inverse = (~mask) >>> 0
  if (((inverse + 1) & inverse) !== 0) return { ok: false, reason: 'mask' }
  return { ok: true, address, prefix: 32 - Math.log2(inverse + 1) }
}

/** Rangos reservados, del más específico al más general. `[dirección, prefijo, clase]`. */
const RESERVED_RANGES = [
  ['0.0.0.0', 8, 'unspecified'],
  ['10.0.0.0', 8, 'private'],
  ['100.64.0.0', 10, 'cgnat'],
  ['127.0.0.0', 8, 'loopback'],
  ['169.254.0.0', 16, 'linkLocal'],
  ['172.16.0.0', 12, 'private'],
  ['192.0.2.0', 24, 'documentation'],
  ['192.168.0.0', 16, 'private'],
  ['198.51.100.0', 24, 'documentation'],
  ['203.0.113.0', 24, 'documentation'],
  ['224.0.0.0', 4, 'multicast'],
  ['240.0.0.0', 4, 'reserved'],
].map(([dotted, prefix, kind]) => ({ start: addressToInt(dotted), mask: maskOf(prefix), kind }))

/**
 * Clase de una dirección: pública, privada, loopback…
 *
 * @param {number} address - Dirección como entero.
 * @returns {string} Uno de `ADDRESS_KINDS` salvo `mixed`; `public` si no cae en
 *   ningún rango reservado.
 */
export function classifyAddress(address) {
  const range = RESERVED_RANGES.find((candidate) => ((address & candidate.mask) >>> 0) === candidate.start)
  return range ? range.kind : 'public'
}

/**
 * Calcula todo lo que se pregunta de una red.
 *
 * @param {number} address - Cualquier dirección de la red, como entero.
 * @param {number} prefix - Bits de red, de 0 a 32.
 * @returns {{
 *   network: string, broadcast: string, netmask: string, wildcard: string,
 *   firstHost: string, lastHost: string, total: number, usable: number,
 *   prefix: number, kind: string, cidr: string
 * }} Todo como texto salvo `total` y `usable`. En un `/31` los dos equipos son
 *   utilizables (enlace punto a punto) y en un `/32` hay uno solo. `kind` es una de
 *   `ADDRESS_KINDS`: `mixed` si el rango mezcla clases (por ejemplo un `/1`).
 */
export function describeNetwork(address, prefix) {
  const mask = maskOf(prefix)
  const network = (address & mask) >>> 0
  const broadcast = (network | (~mask >>> 0)) >>> 0
  const total = 2 ** (32 - prefix)
  const hasHostRange = prefix < 31
  const firstKind = classifyAddress(network)
  return {
    network: intToAddress(network),
    broadcast: intToAddress(broadcast),
    netmask: intToAddress(mask),
    wildcard: intToAddress((~mask) >>> 0),
    firstHost: intToAddress(hasHostRange ? network + 1 : network),
    lastHost: intToAddress(hasHostRange ? broadcast - 1 : broadcast),
    total,
    usable: prefix === 32 ? 1 : prefix === 31 ? 2 : total - 2,
    prefix,
    kind: firstKind === classifyAddress(broadcast) ? firstKind : 'mixed',
    cidr: `${intToAddress(network)}/${prefix}`,
  }
}

/**
 * Parte una red en subredes iguales.
 *
 * @param {number} address - Cualquier dirección de la red, como entero.
 * @param {number} prefix - Prefijo de la red.
 * @param {number} newPrefix - Prefijo de las subredes; tiene que ser mayor que `prefix` y no pasar de 32.
 * @param {number} [limit=32] - Cuántas subredes se devuelven como mucho.
 * @returns {{count: number, subnets: string[], hidden: number}|null} `count` es el
 *   total de subredes; `subnets`, las primeras (`limit`) en notación CIDR; `hidden`,
 *   las que no se listan. `null` si `newPrefix` no es válido.
 */
export function splitNetwork(address, prefix, newPrefix, limit = 32) {
  if (!Number.isInteger(newPrefix) || newPrefix <= prefix || newPrefix > 32) return null
  const network = (address & maskOf(prefix)) >>> 0
  const count = 2 ** (newPrefix - prefix)
  const size = 2 ** (32 - newPrefix)
  const subnets = Array.from({ length: Math.min(count, limit) }, (_, index) => `${intToAddress(network + index * size)}/${newPrefix}`)
  return { count, subnets, hidden: count - subnets.length }
}
