/**
 * Rótulos de los valores que Themis recibe del servidor como códigos.
 *
 * Varios componentes pintan la misma prioridad o el mismo estado de un
 * hallazgo; con un mapa por componente, traducir uno dejaba el de al lado en
 * el idioma anterior. Los textos viven en `themis.priority` y
 * `themis.findingState` del diccionario, y un código que el servidor añada y
 * la interfaz aún no conozca cae en «Desconocido», nunca en el crudo.
 */
import { i18n } from '@/i18n'

const PRIORITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
const FINDING_STATES = ['open', 'fixed', 'regressed', 'accepted', 'false_positive']

/**
 * Rótulo de una prioridad de hallazgo.
 *
 * @param {string|null|undefined} priority - `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` o `INFO`.
 *   Un valor vacío se lee como `INFO`.
 * @returns {string} El rótulo en el idioma activo.
 */
export function priorityLabel(priority) {
  const level = priority || 'INFO'
  return PRIORITIES.includes(level) ? i18n.global.t(`themis.priority.${level}`) : i18n.global.t('common.unknown')
}

/**
 * Rótulo del estado de un hallazgo.
 *
 * @param {string} state - `open`, `fixed`, `regressed`, `accepted` o `false_positive`.
 * @returns {string} El rótulo en el idioma activo.
 */
export function findingStateLabel(state) {
  return FINDING_STATES.includes(state) ? i18n.global.t(`themis.findingState.${state}`) : i18n.global.t('common.unknown')
}
