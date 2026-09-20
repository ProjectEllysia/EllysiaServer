/**
 * Búsqueda de activos por texto — sin Vue ni DOM, para poder testearla en Node
 * igual que `format.js`, `chartMath.js` y `statsMath.js`.
 *
 * El problema que resuelve es el de un parque grande: con doscientas máquinas,
 * decidir cuáles se parecen a lo escrito no basta con un `includes()`, porque
 * eso devuelve un montón sin ningún orden y quien busca acaba leyéndolos todos.
 * Aquí la coincidencia se **puntúa** por lo bien que encaja, y el orden del
 * resultado es el de esa puntuación.
 *
 * Los escalones, de mejor a peor, están en `MATCH_RANK`. El más interesante es
 * el último de los que miran al nombre, la subsecuencia: las letras de lo
 * escrito aparecen en orden dentro del nombre aunque salteadas, que es lo que
 * hace que `wp7` encuentre `web-prod-07`. Va el último a propósito, porque es
 * el que más ruido admite.
 *
 * Nada de esto viaja al servidor: `GET /hygeia/assets` devuelve el parque
 * entero sin paginar y el cliente ya lo tiene en memoria.
 */

/**
 * Calidad de una coincidencia, de mejor (0) a peor (5). El número es el
 * criterio de orden principal, así que los huecos importan menos que el orden.
 *
 * - `EXACT`: el nombre es exactamente lo escrito.
 * - `PREFIX`: el nombre empieza por lo escrito.
 * - `WORD`: un tramo del nombre empieza por lo escrito. Los tramos se cortan
 *   por `-`, `.` y `_`, que es como se nombran las máquinas.
 * - `SUBSTRING`: el nombre lo contiene en cualquier posición.
 * - `SUBSEQUENCE`: las letras de lo escrito salen en orden dentro del nombre,
 *   aunque con otras de por medio.
 * - `META`: no encaja el nombre, pero sí el sistema operativo o una etiqueta.
 */
export const MATCH_RANK = {
  EXACT: 0,
  PREFIX: 1,
  WORD: 2,
  SUBSTRING: 3,
  SUBSEQUENCE: 4,
  META: 5,
}

/** Separadores de tramo dentro de un nombre de máquina. */
const WORD_SEPARATORS = /[-._]/

/**
 * Si las letras de `needle` aparecen en `haystack` en el mismo orden, aunque
 * no seguidas.
 *
 * @param {string} haystack - Texto donde buscar, ya en minúsculas.
 * @param {string} needle - Texto buscado, ya en minúsculas y sin espacios en
 *   los extremos. Con la cadena vacía devuelve `true`.
 * @returns {boolean} `true` si están todas y en orden.
 */
function isSubsequence(haystack, needle) {
  let position = 0
  for (const letter of needle) {
    position = haystack.indexOf(letter, position) + 1
    if (position === 0) return false
  }
  return true
}

/**
 * Puntúa lo bien que un activo encaja con lo escrito.
 *
 * @param {object} asset - Activo tal y como lo sirve la API: se miran
 *   `hostname`, `os` y los `name` de `tags`.
 * @param {string} needle - Lo escrito, ya normalizado a minúsculas y sin
 *   espacios en los extremos.
 * @returns {number|null} El escalón de `MATCH_RANK` al que llega, o `null` si
 *   no encaja por ninguna vía.
 */
export function matchRank(asset, needle) {
  const hostname = (asset.hostname ?? '').toLowerCase()
  if (hostname === needle) return MATCH_RANK.EXACT
  if (hostname.startsWith(needle)) return MATCH_RANK.PREFIX
  if (hostname.split(WORD_SEPARATORS).some((word) => word.startsWith(needle))) return MATCH_RANK.WORD
  if (hostname.includes(needle)) return MATCH_RANK.SUBSTRING

  // El sistema operativo y las etiquetas van por delante de la subsecuencia
  // del nombre solo cuando contienen lo escrito entero: «ubuntu» o
  // «producción» son búsquedas deliberadas, no aproximaciones.
  const meta = [asset.os ?? '', ...(asset.tags ?? []).map((tag) => tag.name ?? '')]
  if (meta.some((value) => value.toLowerCase().includes(needle))) return MATCH_RANK.META

  if (isSubsequence(hostname, needle)) return MATCH_RANK.SUBSEQUENCE
  return null
}

/**
 * Ordena por nombre, que es el orden con el que se presenta un parque cuando
 * no se ha escrito nada. `localeCompare` para que las tildes y las mayúsculas
 * no partan la lista en dos bloques.
 *
 * @param {object} a - Primer activo.
 * @param {object} b - Segundo activo.
 * @returns {number} Negativo, cero o positivo, como espera `Array.sort`.
 */
function byHostname(a, b) {
  return (a.hostname ?? '').localeCompare(b.hostname ?? '', 'es', { numeric: true })
}

/**
 * Los activos que encajan con lo escrito, ordenados por calidad de
 * coincidencia.
 *
 * Sin texto devuelve el parque entero por orden alfabético, así que el
 * buscador sigue sirviendo como desplegable para quien tenga cuatro máquinas.
 * A igualdad de escalón desempata el nombre más corto —en `db-01` y
 * `db-01-replica`, quien escribe `db-01` casi siempre busca el primero— y
 * después el orden alfabético.
 *
 * @param {Array<object>} assets - Parque completo, tal y como lo sirve la API.
 * @param {string} [query=''] - Lo que el usuario ha escrito, sin normalizar.
 * @returns {Array<object>} Los activos que encajan, en orden de presentación.
 *   Es una lista nueva; no se toca la de entrada.
 */
export function searchAssets(assets, query = '') {
  const needle = query.trim().toLowerCase()
  if (!needle) return [...assets].sort(byHostname)

  return assets
    .map((asset) => ({ asset, rank: matchRank(asset, needle) }))
    .filter((entry) => entry.rank !== null)
    .sort((a, b) => a.rank - b.rank
      || (a.asset.hostname ?? '').length - (b.asset.hostname ?? '').length
      || byHostname(a.asset, b.asset))
    .map((entry) => entry.asset)
}

/**
 * Parte un nombre en tramos para poder resaltar en la lista la parte que
 * coincide con lo escrito.
 *
 * Solo resalta la coincidencia literal y contigua: si se llegó al activo por
 * subsecuencia o por una etiqueta, no hay un tramo que señalar y se devuelve
 * el nombre entero sin marcar. Subrayar letras sueltas repartidas por el
 * nombre lo vuelve ilegible, que es justo lo contrario de lo que se busca.
 *
 * @param {string} hostname - Nombre del activo.
 * @param {string} [query=''] - Lo que el usuario ha escrito, sin normalizar.
 * @returns {Array<{text: string, isMatch: boolean}>} Los tramos en orden. Sin
 *   coincidencia literal es un único tramo con `isMatch` a `false`.
 */
export function highlightParts(hostname, query = '') {
  const needle = query.trim().toLowerCase()
  const at = needle ? hostname.toLowerCase().indexOf(needle) : -1
  if (at === -1) return [{ text: hostname, isMatch: false }]

  return [
    { text: hostname.slice(0, at), isMatch: false },
    { text: hostname.slice(at, at + needle.length), isMatch: true },
    { text: hostname.slice(at + needle.length), isMatch: false },
  ].filter((part) => part.text)
}
