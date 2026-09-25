/**
 * Orden y filtros de los hallazgos de un veredicto de Lybra.
 *
 * El servidor manda todos los hallazgos de un escaneo de una vez, ya agrupados
 * por la unidad que se remedia (un producto que subir de versión, o una
 * configuración que corregir). Aquí se decide qué se ve y en qué orden, sin
 * pedir nada más: cambiar un filtro no puede costar un viaje de red.
 *
 * Funciones puras y sin Vue, para poder probarlas con Node desnudo. Nada de lo
 * que se recibe se modifica: los grupos y hallazgos resultantes son objetos
 * nuevos o los mismos de entrada, nunca los de entrada retocados.
 */

import { getCollator } from '../../../i18n/format.js'

/** Niveles de gravedad, de más a menos grave. */
export const LADDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

/** Posición de cada nivel en `LADDER`; lo que no está va detrás de `INFO`. */
const SEVERITY_RANK = Object.fromEntries(LADDER.map((level, index) => [level, index]))
const UNKNOWN_RANK = LADDER.length

/**
 * Estados que cuentan como resueltos: corregido por un escaneo posterior,
 * riesgo asumido o desmentido. `open` y `regressed` (volvió a aparecer tras
 * darse por corregido) son trabajo pendiente.
 */
const RESOLVED_STATES = new Set(['fixed', 'accepted', 'false_positive'])

/** Criterios de orden que ofrece la barra, con su etiqueta. */
export const SORT_OPTIONS = [
  { value: 'severity', label: 'Gravedad' },
  { value: 'cvss', label: 'CVSS' },
  { value: 'epss', label: 'EPSS' },
  { value: 'title', label: 'Nombre' },
  { value: 'product', label: 'Producto' },
]

/** Filtro por estado del hallazgo. */
export const STATE_OPTIONS = [
  { value: 'all', label: 'Todos' },
  { value: 'pending', label: 'Pendientes' },
  { value: 'resolved', label: 'Resueltos' },
]

/** Filtro por certeza: comprobado activamente o deducido por versión. */
export const CERTAINTY_OPTIONS = [
  { value: 'all', label: 'Todos' },
  { value: 'confirmed', label: 'Comprobados' },
  { value: 'potential', label: 'Potenciales' },
]

/**
 * Opciones del orden alfabético de títulos y productos. `numeric` hace que
 * «CVE-2021-999» vaya antes que «CVE-2021-1000». El comparador se pide a
 * `getCollator` una vez por ordenación, no por comparación: construirlo es caro.
 */
const COLLATOR_OPTIONS = { numeric: true, sensitivity: 'base' }

/**
 * Texto en el que busca el cuadro de búsqueda, por hallazgo.
 *
 * Se guarda en un `WeakMap` porque un hallazgo no cambia mientras está en
 * pantalla y teclear una búsqueda recorre la lista en cada pulsación: así el
 * texto de cada uno se normaliza una sola vez. Al recargar los hallazgos llegan
 * objetos nuevos y los viejos se liberan solos.
 */
const HAYSTACKS = new WeakMap()

/**
 * Pasa un texto a minúsculas y sin tildes, para que «configuración» encuentre
 * «Configuracion».
 *
 * @param {string} text - Texto cualquiera; `null` o `undefined` se tratan como vacío.
 * @returns {string} El texto normalizado.
 */
export function normalizeText(text) {
  return (text || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/**
 * Texto normalizado en el que se busca un hallazgo: su título, sus CVEs y el
 * producto o servicio del grupo al que pertenece.
 *
 * @param {object} finding - Hallazgo de la API.
 * @param {object} group - Grupo que lo contiene.
 * @returns {string} El texto, calculado la primera vez y leído de `HAYSTACKS` después.
 */
function haystackOf(finding, group) {
  let haystack = HAYSTACKS.get(finding)
  if (haystack === undefined) {
    haystack = normalizeText([finding.title, ...(finding.cveIds || []), group.label, group.service].join(' '))
    HAYSTACKS.set(finding, haystack)
  }
  return haystack
}

/**
 * Criterios con los que se abre el capítulo de hallazgos.
 *
 * @returns {{sortKey: string, reversed: boolean, state: string, certainty: string, priorities: string[], text: string}}
 *          Orden por gravedad (lo más grave arriba), sin invertir y sin ningún
 *          filtro. `priorities` vacío significa «todas las gravedades».
 */
export function defaultCriteria() {
  return { sortKey: 'severity', reversed: false, state: 'all', certainty: 'all', priorities: [], text: '' }
}

/**
 * Indica si los criterios esconden algún hallazgo.
 *
 * El orden no cuenta: reordenar no oculta nada.
 *
 * @param {object} criteria - Criterios como los de `defaultCriteria()`.
 * @returns {boolean} `true` si hay al menos un filtro activo.
 */
export function isFiltering(criteria) {
  return criteria.state !== 'all' || criteria.certainty !== 'all'
    || criteria.priorities.length > 0 || criteria.text.trim() !== ''
}

/**
 * Indica si un hallazgo está resuelto.
 *
 * @param {{state?: string}} finding - Hallazgo; sin `state` se trata como abierto.
 * @returns {boolean} `true` para `fixed`, `accepted` y `false_positive`.
 */
export function isResolved(finding) {
  return RESOLVED_STATES.has(finding.state)
}

/**
 * Posición de una gravedad en `LADDER`, que es la clave numérica por la que se
 * ordena: más baja, más grave.
 *
 * @param {string|null|undefined} priority - Nivel de `LADDER`; sin nivel cuenta como `INFO`.
 * @returns {number} De `0` (`CRITICAL`) a `4` (`INFO`); `5` si el nivel es desconocido.
 */
function rankOf(priority) {
  return SEVERITY_RANK[priority || 'INFO'] ?? UNKNOWN_RANK
}

/**
 * Compara dos puntuaciones de mayor a menor (o al revés con `direction = -1`).
 *
 * Los ausentes van al final en los dos sentidos: un hallazgo sin CVSS no es
 * «CVSS 0», es que no se sabe, y ponerlo el primero al invertir el orden lo
 * haría pasar por el más leve.
 *
 * @param {number|null} left - Puntuación del primero, o `null`.
 * @param {number|null} right - Puntuación del segundo, o `null`.
 * @param {1|-1} direction - `1` de mayor a menor, `-1` de menor a mayor.
 * @returns {number} Negativo si `left` va antes, positivo si va después, `0` si empatan.
 */
function nullsLast(left, right, direction) {
  if (left == null) return right == null ? 0 : 1
  if (right == null) return -1
  return direction * (right - left)
}

/**
 * Orden de los hallazgos dentro de un grupo.
 *
 * Cada entrada es la versión «decorada» del hallazgo: sus claves de orden se
 * calculan una vez antes de ordenar, y el comparador solo las lee. Recalcular
 * el rango o el título normalizado dentro del comparador los repetiría
 * O(n log n) veces en vez de n.
 *
 * El primer criterio respeta `reversed`; los desempates no, porque el sentido
 * pedido es el del criterio elegido y no el de los que lo acompañan. El último
 * desempate es la posición de llegada, así que el orden es estable y
 * determinista.
 *
 * Con `product` lo que se ordena son los grupos: dentro de cada uno los
 * hallazgos siguen de más a menos grave, se invierta o no el orden.
 *
 * @param {string} sortKey - `severity`, `cvss`, `epss`, `title` o `product`.
 * @param {1|-1} direction - `1` en el sentido natural del criterio, `-1` invertido.
 * @returns {Function} Comparador de hallazgos decorados para `Array.prototype.sort`.
 */
function compareFindings(sortKey, direction) {
  const bySeverity = (left, right) => left.rank - right.rank
    || (right.kev - left.kev)
    || nullsLast(left.cvss, right.cvss, 1)
  const collator = getCollator(COLLATOR_OPTIONS)
  const byTitle = (left, right) => collator.compare(left.title, right.title)
  const byIndex = (left, right) => left.index - right.index

  switch (sortKey) {
    case 'cvss':
      return (left, right) => nullsLast(left.cvss, right.cvss, direction)
        || bySeverity(left, right) || byTitle(left, right) || byIndex(left, right)
    case 'epss':
      return (left, right) => nullsLast(left.epss, right.epss, direction)
        || bySeverity(left, right) || byTitle(left, right) || byIndex(left, right)
    case 'title':
      return (left, right) => direction * byTitle(left, right)
        || bySeverity(left, right) || byIndex(left, right)
    default:
      return (left, right) => (sortKey === 'severity' ? direction : 1) * (left.rank - right.rank)
        || (right.kev - left.kev)
        || nullsLast(left.cvss, right.cvss, 1)
        || byTitle(left, right) || byIndex(left, right)
  }
}

/**
 * Orden de los grupos dentro de una sección, sobre la parte visible de cada uno.
 *
 * Con `title` los grupos conservan el orden de gravedad y lo que cambia es el
 * orden de los hallazgos dentro de cada grupo. El último desempate es la
 * posición en que llegó el grupo, que ya viene de más grave a menos.
 *
 * @param {string} sortKey - `severity`, `cvss`, `epss`, `title` o `product`.
 * @param {1|-1} direction - `1` en el sentido natural del criterio, `-1` invertido.
 * @returns {Function} Comparador de grupos decorados para `Array.prototype.sort`.
 */
function compareGroups(sortKey, direction) {
  const collator = getCollator(COLLATOR_OPTIONS)
  const byIndex = (left, right) => left.index - right.index
  const bySeverity = (left, right) => left.rank - right.rank
  switch (sortKey) {
    case 'cvss':
      return (left, right) => nullsLast(left.cvss, right.cvss, direction) || bySeverity(left, right) || byIndex(left, right)
    case 'epss':
      return (left, right) => nullsLast(left.epss, right.epss, direction) || bySeverity(left, right) || byIndex(left, right)
    case 'product':
      return (left, right) => direction * collator.compare(left.label, right.label) || bySeverity(left, right) || byIndex(left, right)
    case 'title':
      return (left, right) => bySeverity(left, right) || byIndex(left, right)
    default:
      return (left, right) => direction * bySeverity(left, right) || byIndex(left, right)
  }
}

/**
 * Recuento vacío por gravedad, con los cinco niveles de `LADDER`.
 *
 * @returns {Object<string, number>} Un contador a cero por nivel.
 */
function emptyPriorityCounts() {
  return { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 }
}

/**
 * Filtra y ordena los grupos de hallazgos de un escaneo y los reparte en sus
 * dos secciones.
 *
 * Las secciones son dos clases de trabajo distintas —subir un producto de
 * versión, y arreglar una configuración— y se mantienen con cualquier orden: el
 * orden actúa dentro de cada una.
 *
 * Todo se hace en una pasada por hallazgo para filtrar y contar, y una
 * ordenación por grupo y por sección solo sobre lo que sobrevive al filtro.
 *
 * Los recuentos de las pastillas son «facetados»: el de cada gravedad cuenta
 * los hallazgos que pasan todos los demás filtros, que es cuántos se verían al
 * pulsarla. Si contara solo lo visible, apagar una gravedad dejaría su pastilla
 * a cero y no habría forma de saber qué se está escondiendo.
 *
 * @param {Array<object>} groups - Grupos tal como llegan de la API (`label`,
 *        `isProduct`, `findings`, …), ya de más grave a menos.
 * @param {object} criteria - Criterios como los de `defaultCriteria()`:
 *        `sortKey` (`severity`, `cvss`, `epss`, `title` o `product`),
 *        `reversed` (invierte el criterio principal), `state` (`all`,
 *        `pending` o `resolved`), `certainty` (`all`, `confirmed` o
 *        `potential`), `priorities` (niveles de `LADDER` que se muestran;
 *        vacío = todos) y `text` (busca en título, CVEs y producto).
 * @returns {{sections: Array<object>, priorityCounts: Object<string, number>,
 *           stateCounts: {pending: number, resolved: number},
 *           visibleTotal: number, total: number}}
 *          `sections` trae siempre las dos secciones (`prod` y `conf`), cada
 *          una con sus grupos visibles, su `balance` por gravedad y su
 *          `total`. Cada grupo es una copia del de entrada con `findings`
 *          reducido y ordenado, `totalFindings` con lo visible,
 *          `allFindings` con el total original y `priority` con la gravedad
 *          máxima de lo visible. Un grupo sin nada visible no aparece.
 *          `visibleTotal` es lo que se ve y `total`, lo que hay.
 */
export function arrangeGroups(groups, criteria) {
  const direction = criteria.reversed ? -1 : 1
  const wantedPriorities = criteria.priorities.length ? new Set(criteria.priorities) : null
  const needle = normalizeText(criteria.text.trim())
  const findingOrder = compareFindings(criteria.sortKey, direction)

  const priorityCounts = emptyPriorityCounts()
  const stateCounts = { pending: 0, resolved: 0 }
  const decoratedGroups = { prod: [], conf: [] }
  let total = 0
  let visibleTotal = 0

  groups.forEach((group, groupIndex) => {
    const kept = []
    const findings = group.findings || []
    total += findings.length

    for (let index = 0; index < findings.length; index++) {
      const finding = findings[index]
      const priority = finding.priority || 'INFO'
      const resolved = isResolved(finding)
      const passesState = criteria.state === 'all' || (criteria.state === 'resolved') === resolved
      const passesCertainty = criteria.certainty === 'all' || (criteria.certainty === 'confirmed') === !!finding.confirmed
      const passesText = !needle || haystackOf(finding, group).includes(needle)
      const passesPriority = !wantedPriorities || wantedPriorities.has(priority)

      if (passesState && passesCertainty && passesText && priority in priorityCounts) priorityCounts[priority]++
      if (passesCertainty && passesText && passesPriority) stateCounts[resolved ? 'resolved' : 'pending']++
      if (!(passesState && passesCertainty && passesText && passesPriority)) continue

      kept.push({
        finding,
        index,
        rank: rankOf(priority),
        kev: finding.inKev ? 1 : 0,
        cvss: finding.cvssScore ?? null,
        epss: finding.epssScore ?? null,
        title: finding.title || '',
      })
    }
    if (!kept.length) return

    kept.sort(findingOrder)
    visibleTotal += kept.length

    let rank = UNKNOWN_RANK
    let cvss = null
    let epss = null
    for (const entry of kept) {
      if (entry.rank < rank) rank = entry.rank
      if (entry.cvss != null && (cvss == null || entry.cvss > cvss)) cvss = entry.cvss
      if (entry.epss != null && (epss == null || entry.epss > epss)) epss = entry.epss
    }

    decoratedGroups[group.isProduct ? 'prod' : 'conf'].push({
      index: groupIndex,
      rank,
      cvss,
      epss,
      label: group.label || '',
      group: {
        ...group,
        findings: kept.map(entry => entry.finding),
        totalFindings: kept.length,
        allFindings: findings.length,
        priority: LADDER[rank] || group.priority,
      },
    })
  })

  const groupOrder = compareGroups(criteria.sortKey, direction)
  const sections = [
    buildSection('prod', 'Productos afectados', decoratedGroups.prod, groupOrder),
    buildSection('conf', 'Configuración y exposición', decoratedGroups.conf, groupOrder),
  ]
  return { sections, priorityCounts, stateCounts, visibleTotal, total }
}

/**
 * Ordena los grupos decorados de una sección y le añade su balanza.
 *
 * La balanza se cuenta hallazgo a hallazgo y no por la gravedad del grupo, que
 * es la máxima de los suyos: un producto con un CVE crítico y nueve bajos pesa
 * un crítico y nueve bajos, no diez críticos.
 *
 * @param {string} key - `prod` o `conf`.
 * @param {string} title - Título visible de la sección.
 * @param {Array<object>} decorated - Grupos decorados de la sección.
 * @param {Function} groupOrder - Comparador de `compareGroups`.
 * @returns {{key: string, title: string, groups: Array<object>,
 *           balance: Array<{level: string, count: number}>, total: number}}
 *          La sección, con `balance` limitado a los niveles presentes en el
 *          orden de `LADDER` y `total` como suma de todos ellos.
 */
function buildSection(key, title, decorated, groupOrder) {
  decorated.sort(groupOrder)
  const counts = emptyPriorityCounts()
  const groups = decorated.map(entry => entry.group)
  for (const group of groups) {
    for (const finding of group.findings) {
      const level = finding.priority || 'INFO'
      counts[level] = (counts[level] || 0) + 1
    }
  }
  const balance = LADDER.filter(level => counts[level]).map(level => ({ level, count: counts[level] }))
  return { key, title, groups, balance, total: balance.reduce((sum, segment) => sum + segment.count, 0) }
}
