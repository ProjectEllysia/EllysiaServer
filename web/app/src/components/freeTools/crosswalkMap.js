/**
 * Lógica pura del mapa de correspondencias de Eunomia: de la lista plana de enlaces que manda
 * `GET /eunomia/crosswalks` a «qué controles de qué marcos corresponden con este». Sin Vue ni
 * red, para probarla con `node`.
 *
 * No hay aquí ninguna lista de marcos: los marcos, sus controles y los enlaces vienen del
 * catálogo de la API, así que añadir, actualizar o quitar un marco no toca este fichero.
 */

/** Cobertura de un enlace: cumplir uno de los dos controles cubre en lo esencial al otro. */
export const COVERAGE_FULL = 'full'
/** Cobertura de un enlace: cumplir uno de los dos controles cubre al otro solo en parte. */
export const COVERAGE_PARTIAL = 'partial'

/**
 * Clave de un control en el índice.
 *
 * @param {string} framework - Clave del marco (`'nis2'`).
 * @param {string} identifier - Identificador del control dentro del marco (`'21.2.e'`).
 * @returns {string} `marco:identificador`, la misma forma que el código global del catálogo.
 */
export function controlKey(framework, identifier) {
  return `${framework}:${identifier}`
}

/**
 * Indexa los enlaces por control, en los dos sentidos: un enlace de A a B sirve también para
 * quien mira desde B.
 *
 * @param {Array<{fromFramework: string, fromIdentifier: string, toFramework: string,
 *   toIdentifier: string, coverage: string}>} links - Los enlaces de la API.
 * @returns {Map<string, Array<{framework: string, identifier: string, coverage: string}>>}
 *   Para cada control, los controles de otros marcos con los que corresponde, en el orden de
 *   los enlaces. Un control sin correspondencias no figura en el mapa.
 */
export function indexLinks(links) {
  const index = new Map()
  const add = (framework, identifier, other) => {
    const key = controlKey(framework, identifier)
    if (!index.has(key)) index.set(key, [])
    index.get(key).push(other)
  }
  for (const link of links) {
    add(link.fromFramework, link.fromIdentifier,
      { framework: link.toFramework, identifier: link.toIdentifier, coverage: link.coverage })
    add(link.toFramework, link.toIdentifier,
      { framework: link.fromFramework, identifier: link.fromIdentifier, coverage: link.coverage })
  }
  return index
}

/**
 * Las correspondencias de un control, agrupadas por marco.
 *
 * @param {Map} index - Lo que devuelve `indexLinks`.
 * @param {string} framework - Marco del control.
 * @param {string} identifier - Identificador del control.
 * @param {string[]} frameworkOrder - Claves de los marcos en el orden en que se enseñan.
 * @returns {Array<{framework: string, items: Array<{identifier: string, coverage: string}>}>}
 *   Un grupo por marco con correspondencias, en `frameworkOrder`; vacío si el control no tiene.
 */
export function correspondencesOf(index, framework, identifier, frameworkOrder) {
  const found = index.get(controlKey(framework, identifier)) ?? []
  return frameworkOrder
    .map((key) => ({
      framework: key,
      items: found.filter((item) => item.framework === key)
        .map(({ identifier: id, coverage }) => ({ identifier: id, coverage })),
    }))
    .filter((group) => group.items.length)
}

/**
 * Los marcos con los que el de referencia no tiene ninguna correspondencia publicada.
 *
 * Sirve para decir «sin cruce publicado» y no dejar creer que dos marcos no tienen nada en
 * común: lo que falta es el fichero de correspondencias, no el solapamiento.
 *
 * @param {Array<{fromFramework: string, toFramework: string}>} links - Los enlaces de la API.
 * @param {string} reference - Clave del marco de referencia.
 * @param {string[]} frameworkOrder - Claves de todos los marcos, en el orden en que se enseñan.
 * @returns {string[]} Las claves de los otros marcos sin ningún enlace con el de referencia.
 */
export function unlinkedFrameworks(links, reference, frameworkOrder) {
  const linked = new Set()
  for (const link of links) {
    if (link.fromFramework === reference) linked.add(link.toFramework)
    else if (link.toFramework === reference) linked.add(link.fromFramework)
  }
  return frameworkOrder.filter((key) => key !== reference && !linked.has(key))
}
