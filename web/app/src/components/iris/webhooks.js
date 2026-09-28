/**
 * Rótulos de los webhooks de Iris: tipos de evento, estados de una entrega y
 * motivos por los que un webhook se desactivó solo.
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
