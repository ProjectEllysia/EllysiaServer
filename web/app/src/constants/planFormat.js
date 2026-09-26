/**
 * Cómo se lee un plan: etiquetas, precios y límites.
 *
 * Vivía dentro de `PlansView.vue`. La portada enseña ahora una versión
 * resumida del catálogo y necesita exactamente lo mismo, así que en vez de
 * copiar seis funciones se sacan aquí: si mañana cambia cómo se dice
 * "ilimitado", cambia en un sitio y no en dos que se van separando.
 *
 * Módulo plano, sin `ref` ni composable: son funciones puras sobre el JSON que
 * devuelve `GET /plans`. Mismo criterio que `components/hygeia/format.js`.
 */

import { formatNumber } from '@/i18n/format'
import { i18n } from '@/i18n'

/**
 * Las claves que se enseñan, de las 15 que trae cada plan. El orden importa:
 * es el que se pinta.
 */
export const FEATURED = [
  'themis.lybra.scans',
  'iris.analyses',
  'acheron.items',
  'hygeia.assets',
  'ai.requests',
  'organization.members',
]

/** Las tres que mejor resumen un plan de un vistazo, para la portada. */
export const HEADLINE = [
  'themis.lybra.scans',
  'hygeia.assets',
  'iris.analyses',
]

/**
 * Rama del diccionario de cada clave de límite. Las claves llevan puntos y
 * vue-i18n los lee como niveles del árbol, así que se nombran aparte.
 */
const LABEL_IDS = {
  'themis.lybra.scans': 'scans',
  'iris.analyses': 'mailAnalyses',
  'acheron.items': 'vaultSecrets',
  'hygeia.assets': 'assets',
  'ai.requests': 'aiRequests',
  'organization.members': 'members',
}

/**
 * Rótulo de una clave de límite en el idioma activo.
 *
 * @param {string} key - Clave de límite (`'iris.analyses'`…).
 * @param {boolean} [short=false] - La versión corta, para la portada, donde no
 *   hay ancho para las largas.
 * @returns {string} El rótulo, o la propia clave si no tiene rótulo.
 */
export function labelOf(key, short = false) {
  const id = LABEL_IDS[key]
  if (!id) return key
  return i18n.global.t(`planFormat.${short ? 'shortLabels' : 'labels'}.${id}`)
}

/**
 * Precio mensual en euros, con el formato de moneda del idioma activo.
 *
 * @param {number} cents - Precio en céntimos.
 * @returns {string} El precio sin decimales (`"12 €"`, `"€12"`).
 */
export function euros(cents) {
  return formatNumber(cents / 100, { style: 'currency', currency: 'EUR', maximumFractionDigits: 0, minimumFractionDigits: 0 })
}

/** El límite del titular del plan (no el de sus miembros). */
export function limitOf(plan, key) {
  return plan.limits?.holder?.[key]
}

export function isZero(plan, key) {
  const limit = limitOf(plan, key)
  return !limit || limit.value === 0
}

/**
 * El límite en palabras.
 *
 * `null` y `0` NO son lo mismo y el backend lo documenta así: `null` significa
 * ilimitado y `0` significa que el plan no incluye la característica.
 */
export function describe(plan, key) {
  const limit = limitOf(plan, key)
  const { t } = i18n.global
  if (!limit || limit.value === 0) return t('planFormat.notIncluded')
  if (limit.value === null) return t('planFormat.unlimited')
  return limit.period === 'month' ? t('planFormat.perMonth', { value: limit.value }) : `${limit.value}`
}
