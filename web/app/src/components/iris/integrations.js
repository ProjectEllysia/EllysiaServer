/**
 * Rótulos de las integraciones de Iris: tipos de evento de los webhooks,
 * estados de una entrega, motivos por los que un webhook se desactivó solo,
 * estados de un token de integración y canal desde el que se reportó un correo.
 *
 * Devuelven la clave del diccionario, no el texto (CONVENCIONES § 12.5): así se
 * prueban con `node` a secas y un valor que el servidor añada mañana cae en un
 * rótulo genérico en vez de enseñarse en crudo.
 */

/** Claves i18n de cada tipo de evento, por su nombre en el protocolo (`analysis.finished`…). */
const EVENT_TYPE_KEYS = {
  'analysis.finished': 'analysisFinished',
  'case.updated': 'caseUpdated',
  'campaign.detected': 'campaignDetected',
  'mailbox.reauth_required': 'mailboxReauthRequired',
  ping: 'ping',
}

const DELIVERY_STATUSES = ['pending', 'delivering', 'delivered', 'failed']

const DISABLED_REASONS = ['failures', 'gone']

const TOKEN_STATUSES = ['active', 'expired', 'revoked']

const REPORT_CHANNELS = ['outlook_addin', 'gmail_addon', 'browser_extension', 'api']

/**
 * Clave del texto que dice desde dónde reportó el usuario un correo.
 *
 * @param {string|null} channel - `outlook_addin`, `gmail_addon`, `browser_extension` o `api`.
 * @returns {string|null} `iris.reporting.channels.<canal>`; `iris.reporting.channels.api` si no
 *   se conoce, y `null` si el correo no llegó por el canal de reporte.
 */
export function reportChannelKey(channel) {
  if (!channel) return null
  return `iris.reporting.channels.${REPORT_CHANNELS.includes(channel) ? channel : 'api'}`
}

/**
 * Clave del rótulo del estado de un token de integración.
 *
 * @param {string} status - `active`, `expired` o `revoked`.
 * @returns {string} `iris.reporting.tokenStatus.<estado>`, o `common.unknown`.
 */
export function tokenStatusKey(status) {
  return TOKEN_STATUSES.includes(status) ? `iris.reporting.tokenStatus.${status}` : 'common.unknown'
}

/**
 * Clave del rótulo de un tipo de evento.
 *
 * @param {string} eventType - Nombre del evento (`analysis.finished`, `case.updated`…).
 * @returns {string} `iris.webhooks.events.<clave>`, o `common.unknown` si no se conoce.
 */
export function webhookEventKey(eventType) {
  const key = EVENT_TYPE_KEYS[eventType]
  return key ? `iris.webhooks.events.${key}` : 'common.unknown'
}

/**
 * Clave del rótulo del estado de una entrega.
 *
 * @param {string} status - `pending`, `delivering`, `delivered` o `failed`.
 * @returns {string} `iris.webhooks.deliveryStatus.<estado>`, o `common.unknown`.
 */
export function deliveryStatusKey(status) {
  return DELIVERY_STATUSES.includes(status) ? `iris.webhooks.deliveryStatus.${status}` : 'common.unknown'
}

/**
 * Clave del texto que explica por qué un webhook se desactivó solo.
 *
 * @param {string|null} reason - `failures`, `gone`, o `null` si lo apagó el usuario.
 * @returns {string} `iris.webhooks.disabledReason.<motivo>`; `iris.webhooks.disabledReason.manual`
 *   si no hay motivo y `common.unknown` si no se conoce.
 */
export function disabledReasonKey(reason) {
  if (!reason) return 'iris.webhooks.disabledReason.manual'
  return DISABLED_REASONS.includes(reason) ? `iris.webhooks.disabledReason.${reason}` : 'common.unknown'
}
