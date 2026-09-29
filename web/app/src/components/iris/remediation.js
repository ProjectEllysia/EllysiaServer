/**
 * Rótulos de las acciones de Iris sobre el buzón conectado: qué acción es, en
 * qué estado está y por qué no se puede actuar sobre un correo.
 *
 * Devuelven la clave del diccionario, no el texto (CONVENCIONES § 12.5), y un
 * valor que la interfaz no conoce cae en el rótulo genérico.
 */

const ACTIONS = ['quarantine', 'label', 'report_phishing', 'delete']

const STATUSES = ['pending', 'running', 'succeeded', 'failed', 'rolled_back']

const UNAVAILABLE_REASONS = ['not_from_mailbox', 'connection_gone', 'reauth_required', 'missing_scope']

/**
 * Clave del rótulo de una acción (el verbo del botón y de la auditoría).
 *
 * @param {string} action - `quarantine`, `label`, `report_phishing` o `delete`.
 * @returns {string} `iris.remediation.actions.<acción>`, o `common.unknown`.
 */
export function mailboxActionKey(action) {
  return ACTIONS.includes(action) ? `iris.remediation.actions.${action}` : 'common.unknown'
}

/**
 * Clave del rótulo del estado de una acción.
 *
 * @param {string} status - `pending`, `running`, `succeeded`, `failed` o `rolled_back`.
 * @returns {string} `iris.remediation.statuses.<estado>`, o `common.unknown`.
 */
export function mailboxActionStatusKey(status) {
  return STATUSES.includes(status) ? `iris.remediation.statuses.${status}` : 'common.unknown'
}

/**
 * Clave del texto que explica por qué no se puede actuar sobre un correo.
 *
 * @param {string|null} reason - `not_from_mailbox`, `connection_gone`, `reauth_required`,
 *   `missing_scope`, o `null` si se puede actuar.
 * @returns {string|null} `iris.remediation.unavailable.<motivo>`, `common.unknown` si no se
 *   conoce, o `null` si se puede actuar.
 */
export function unavailableReasonKey(reason) {
  if (!reason) return null
  return UNAVAILABLE_REASONS.includes(reason) ? `iris.remediation.unavailable.${reason}` : 'common.unknown'
}

/**
 * Si una acción de la auditoría todavía no ha terminado (y conviene volver a preguntar).
 *
 * @param {{status: string}} entry - Fila de la auditoría.
 * @returns {boolean} `true` si está `pending` o `running`.
 */
export function isActionInFlight(entry) {
  return entry.status === 'pending' || entry.status === 'running'
}
