/**
 * Test de la búsqueda de activos por texto
 * (`components/hygeia/assetSearch.js`).
 *
 * Lo que se prueba no es que el filtro encuentre —eso lo haría cualquier
 * `includes()`—, sino lo que un desplegable no daba: que el orden del
 * resultado sea el de la calidad de la coincidencia, que escribir unas pocas
 * letras salteadas siga encontrando la máquina, que buscar por sistema
 * operativo o por etiqueta funcione sin que eso adelante a una coincidencia
 * del nombre, y que el resaltado no invente tramos que no existen.
 *
 *   node web/app/test/hygeia.assetSearch.test.mjs
 */

import { MATCH_RANK, highlightParts, matchRank, searchAssets } from '../src/components/hygeia/assetSearch.js'

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

/** Un activo como el que sirve la API, con lo justo para buscarlo. */
function asset(hostname, { os = null, tags = [] } = {}) {
  return { id: hostname, hostname, os, tags: tags.map((name) => ({ id: name, name })) }
}

/** Los nombres del resultado, que es lo que se compara en casi todo el test. */
function hostnames(assets, query) {
  return searchAssets(assets, query).map((a) => a.hostname)
}

console.log('\nEscalones de coincidencia')
check('el nombre exacto es el mejor escalón',
  matchRank(asset('db-01'), 'db-01') === MATCH_RANK.EXACT)
check('empezar por lo escrito va después del exacto',
  matchRank(asset('db-01-replica'), 'db-01') === MATCH_RANK.PREFIX)
check('un tramo que empieza por lo escrito cuenta como palabra',
  matchRank(asset('web-prod-07'), 'prod') === MATCH_RANK.WORD)
check('los tramos se cortan también por punto y por guion bajo',
  matchRank(asset('web.prod_07'), 'prod') === MATCH_RANK.WORD)
check('contenerlo en medio de un tramo es el escalón de subcadena',
  matchRank(asset('reproductor'), 'prod') === MATCH_RANK.SUBSTRING)
check('las letras salteadas encuentran la máquina',
  matchRank(asset('web-prod-07'), 'wp7') === MATCH_RANK.SUBSEQUENCE)
check('el sistema operativo encaja cuando el nombre no',
  matchRank(asset('db-01', { os: 'Ubuntu 24.04' }), 'ubuntu') === MATCH_RANK.META)
check('una etiqueta encaja cuando el nombre no',
  matchRank(asset('db-01', { tags: ['producción'] }), 'producción') === MATCH_RANK.META)
check('lo que no encaja por ninguna vía no devuelve escalón',
  matchRank(asset('db-01', { os: 'Ubuntu', tags: ['producción'] }), 'zzz') === null)
check('las letras salteadas tienen que ir en orden',
  matchRank(asset('web-prod-07'), '7pw') === null)
check('la coincidencia no distingue mayúsculas',
  matchRank(asset('DB-01'), 'db-01') === MATCH_RANK.EXACT)

console.log('\nOrden del resultado')
const parque = [
  asset('web-prod-07'),
  asset('db-01-replica'),
  asset('db-01'),
  asset('reproductor'),
  asset('backup', { tags: ['producción'] }),
]
eq('el orden es el de la calidad de la coincidencia, no el del parque',
  hostnames(parque, 'prod'),
  ['web-prod-07', 'reproductor', 'backup'])
eq('a igualdad de escalón manda el nombre más corto',
  hostnames([asset('db-01-replica'), asset('db-01')], 'db-0'),
  ['db-01', 'db-01-replica'])
eq('el exacto adelanta al que solo empieza igual',
  hostnames([asset('db-01-replica'), asset('db-01')], 'db-01'),
  ['db-01', 'db-01-replica'])
eq('una coincidencia del nombre va por delante de una etiqueta',
  hostnames([asset('backup', { tags: ['producción'] }), asset('reproductor')], 'produc'),
  ['reproductor', 'backup'])
eq('sin texto se devuelve el parque entero en orden alfabético',
  hostnames(parque, ''),
  ['backup', 'db-01', 'db-01-replica', 'reproductor', 'web-prod-07'])
eq('los espacios sueltos se tratan como no haber escrito nada',
  hostnames([asset('b'), asset('a')], '   '),
  ['a', 'b'])
eq('el orden alfabético cuenta los números como números',
  hostnames([asset('nodo-10'), asset('nodo-2')], ''),
  ['nodo-2', 'nodo-10'])
eq('lo que no encaja se queda fuera',
  hostnames(parque, 'zzz'),
  [])

console.log('\nLa lista de entrada no se toca')
const original = [asset('b'), asset('a')]
searchAssets(original, '')
eq('ordenar el resultado no reordena el parque del store',
  original.map((a) => a.hostname),
  ['b', 'a'])

console.log('\nResaltado de la parte que coincide')
eq('la coincidencia literal se parte en tres tramos',
  highlightParts('web-prod-07', 'prod'),
  [{ text: 'web-', isMatch: false }, { text: 'prod', isMatch: true }, { text: '-07', isMatch: false }])
eq('una coincidencia al principio no deja un tramo vacío delante',
  highlightParts('db-01', 'db'),
  [{ text: 'db', isMatch: true }, { text: '-01', isMatch: false }])
eq('el resaltado respeta las mayúsculas del nombre',
  highlightParts('DB-01', 'db'),
  [{ text: 'DB', isMatch: true }, { text: '-01', isMatch: false }])
eq('sin texto no se resalta nada',
  highlightParts('db-01', ''),
  [{ text: 'db-01', isMatch: false }])
eq('llegar por letras salteadas no inventa un tramo resaltado',
  highlightParts('web-prod-07', 'wp7'),
  [{ text: 'web-prod-07', isMatch: false }])
eq('llegar por etiqueta tampoco resalta el nombre',
  highlightParts('backup', 'producción'),
  [{ text: 'backup', isMatch: false }])

console.log(`\n${passed} correctos, ${failed} fallidos`)
process.exit(failed ? 1 : 0)
