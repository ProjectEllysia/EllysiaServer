/**
 * Rótulos de los documentos de Hygeia (estadísticas en CSV o PDF, e inventario en PDF).
 *
 * Lógica pura, sin Vue ni DOM, para poder testearla en Node igual que
 * `statsMath.js`. El servidor guarda cada documento como la consulta que lo
 * produjo (`kind` + `parameters`); aquí se convierte esa consulta en el título
 * y la descripción que ve el usuario, y cada estado en su rótulo.
 */

import { metricOf } from './statsMath.js'

/**
 * Estados de un documento y su rótulo. `isActive` marca los que todavía no han
 * terminado, que son los que obligan a seguir preguntando por el documento.
 */
export const DOCUMENT_STATUSES = {
  pending: { label: 'En cola', isActive: true },
  running: { label: 'Generándose', isActive: true },
  done: { label: 'Listo', isActive: false },
  error: { label: 'Ha fallado', isActive: false },
}

/** Rótulo de un estado que este módulo no conoce. */
const UNKNOWN_STATUS = { label: 'Desconocido', isActive: false }

/**
 * El estado de un documento con su rótulo.
 *
 * @param {string} status - Estado tal como llega del servidor.
 * @returns {{label: string, isActive: boolean}} El del catálogo, o uno genérico
 *   («Desconocido», no activo) si el servidor manda un estado nuevo.
 */
export function documentStatusOf(status) {
  return DOCUMENT_STATUSES[status] ?? UNKNOWN_STATUS
}

/**
 * Si algún documento de la lista sigue en cola o generándose.
 *
 * @param {Array<{status: string}>} documents - Documentos.
 * @returns {boolean} `true` si hay que seguir preguntando por ellos.
 */
export function hasActiveDocuments(documents) {
  return (documents ?? []).some((document) => documentStatusOf(document.status).isActive)
}

/**
 * Periodo pedido en palabras: `24h` → «últimas 24 horas», `7d` → «últimos 7 días».
 *
 * @param {string|null|undefined} period - Periodo en la forma `<n>h`/`<n>d`.
 * @returns {string} La frase, o cadena vacía si no hay periodo o no se entiende.
 */
export function describePeriod(period) {
  const match = /^(\d+)([hd])$/.exec(period ?? '')
  if (!match) return ''
  const amount = Number(match[1])
  if (match[2] === 'h') return amount === 1 ? 'última hora' : `últimas ${amount} horas`
  return amount === 1 ? 'último día' : `últimos ${amount} días`
}

/**
 * Título y descripción de un documento, a partir de la consulta que lo produjo.
 *
 * El nombre del activo o de la etiqueta sale de `parameters.scopeLabel`, que el
 * servidor guarda al pedir el documento: así el título sigue diciendo algo
 * aunque el activo o la etiqueta ya no existan.
 *
 * El formato no forma parte de la descripción: la lista lo enseña aparte, en
 * la insignia de cada fila.
 *
 * @param {{kind: string, parameters?: object}} document - Documento.
 * @returns {{title: string, detail: string}} `title` dice qué es; `detail`,
 *   lo que lo matiza (el periodo, o si lleva el software instalado), o cadena
 *   vacía si no hay nada que matizar.
 */
export function describeDocument(document) {
  const parameters = document?.parameters ?? {}

  if (document?.kind === 'inventory-pdf') {
    const title = parameters.scope === 'organization'
      ? 'Inventario de la organización'
      : 'Inventario de mis activos'
    return { title, detail: parameters.includeSoftware ? 'con software instalado' : '' }
  }

  if (document?.kind === 'stats-csv' || document?.kind === 'stats-pdf') {
    const label = parameters.scopeLabel
    const titles = {
      summary: `Estadísticas de ${label ? `«${label}»` : 'un activo'}`,
      'tag-stats': `Estadísticas de la etiqueta ${label ? `«${label}»` : ''}`.trim(),
      ranking: `Ranking del parque por ${metricOf(parameters.metric)?.name ?? 'métrica'}`,
      overview: 'Panorama del parque',
    }
    return {
      title: titles[parameters.dataset] ?? 'Estadísticas',
      detail: describePeriod(parameters.period),
    }
  }

  return { title: 'Documento', detail: '' }
}
