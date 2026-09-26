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
 * Estados de un documento y la clave de su rótulo. `isActive` marca los que
 * todavía no han terminado, que son los que obligan a seguir preguntando por
 * el documento.
 */
export const DOCUMENT_STATUSES = {
  pending: { labelKey: 'hygeia.documentStatus.pending', isActive: true },
  running: { labelKey: 'hygeia.documentStatus.running', isActive: true },
  done: { labelKey: 'hygeia.documentStatus.done', isActive: false },
  error: { labelKey: 'hygeia.documentStatus.error', isActive: false },
}

/** Estado que este módulo no conoce. */
const UNKNOWN_STATUS = { labelKey: 'common.unknown', isActive: false }

/**
 * El estado de un documento con su rótulo.
 *
 * @param {string} status - Estado tal como llega del servidor.
 * @returns {{labelKey: string, isActive: boolean}} El del catálogo, o uno
 *   genérico («Desconocido», no activo) si el servidor manda un estado nuevo.
 *   `labelKey` es la clave del rótulo en los ficheros de idioma.
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
 * @param {Function} t - Función de traducción de vue-i18n (`useI18n().t` o
 *   `i18n.global.t`).
 * @returns {string} La frase, o cadena vacía si no hay periodo o no se entiende.
 */
export function describePeriod(period, t) {
  const match = /^(\d+)([hd])$/.exec(period ?? '')
  if (!match) return ''
  const amount = Number(match[1])
  return t(match[2] === 'h' ? 'hygeia.lastHours' : 'hygeia.lastDays', { count: amount }, amount)
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
 * @param {Function} t - Función de traducción de vue-i18n (`useI18n().t` o
 *   `i18n.global.t`).
 * @returns {{title: string, detail: string}} `title` dice qué es; `detail`,
 *   lo que lo matiza (el periodo, o si lleva el software instalado), o cadena
 *   vacía si no hay nada que matizar.
 */
export function describeDocument(document, t) {
  const parameters = document?.parameters ?? {}

  if (document?.kind === 'inventory-pdf') {
    const title = parameters.scope === 'organization'
      ? t('hygeia.documentTitles.organizationInventory')
      : t('hygeia.documentTitles.myInventory')
    return { title, detail: parameters.includeSoftware ? t('hygeia.documentTitles.withSoftware') : '' }
  }

  if (document?.kind === 'stats-csv' || document?.kind === 'stats-pdf') {
    const label = parameters.scopeLabel
    const metric = metricOf(parameters.metric)
    const titles = {
      summary: () => (label ? t('hygeia.documentTitles.assetStats', { name: label }) : t('hygeia.documentTitles.anAssetStats')),
      'tag-stats': () => (label ? t('hygeia.documentTitles.tagStats', { name: label }) : t('hygeia.documentTitles.aTagStats')),
      ranking: () => t('hygeia.documentTitles.ranking', { metric: metric ? t(metric.labelKey) : t('hygeia.documentTitles.metric') }),
      overview: () => t('hygeia.documentTitles.overview'),
    }
    return {
      title: titles[parameters.dataset]?.() ?? t('hygeia.documentTitles.stats'),
      detail: describePeriod(parameters.period, t),
    }
  }

  return { title: t('hygeia.documentTitles.document'), detail: '' }
}
