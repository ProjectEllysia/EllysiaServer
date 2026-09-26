/**
 * Rótulos de Iris que solo pinta la interfaz y no se prueban en Node (los que
 * sí, en `verdict.js`, devuelven claves). Un valor que el servidor añada y la
 * interfaz aún no conozca cae en «Desconocido», nunca en el crudo.
 */
import { i18n } from '@/i18n'

const CASE_STATUSES = ['new', 'triage', 'contained', 'resolved', 'false_positive']

/**
 * Rótulo del estado de un caso.
 *
 * @param {string} status - `new`, `triage`, `contained`, `resolved` o `false_positive`.
 * @returns {string} El rótulo en el idioma activo.
 */
export function caseStatusLabel(status) {
  return CASE_STATUSES.includes(status) ? i18n.global.t(`iris.caseStatus.${status}`) : i18n.global.t('common.unknown')
}
