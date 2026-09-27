/**
 * Ayudantes de los indicadores (IOCs) que pinta Iris: el panel de IOCs de un
 * informe y los indicadores comunes de una campaña. Sin Vue ni diccionario,
 * para poder probarlos con `node` a secas.
 */

/**
 * Neutraliza un indicador para que no se convierta en un enlace ni resuelva
 * por accidente al pegarlo en otra herramienta.
 *
 * @param {string} value - Dominio, URL, IP, dirección o hash.
 * @returns {string} El valor con `http` → `hxxp`, `.` → `[.]` y `@` → `[at]`.
 */
export function defang(value) {
  return String(value)
    .replace(/https?/gi, (match) => match.replace(/^http/i, 'hxxp'))
    .replace(/\./g, '[.]')
    .replace(/@/g, '[at]')
}

const INDICATOR_KINDS = ['domain', 'url', 'ip', 'email', 'hash']

/**
 * Clave del rótulo del tipo de un indicador del índice de IOCs.
 *
 * @param {string} kind - `domain`, `url`, `ip`, `email` o `hash`.
 * @returns {string} `iris.indicatorKind.<tipo>`, o `common.unknown` si no se conoce.
 */
export function indicatorKindKey(kind) {
  return INDICATOR_KINDS.includes(kind) ? `iris.indicatorKind.${kind}` : 'common.unknown'
}

const CAMPAIGN_SIGNALS = ['url', 'hash', 'template', 'subject', 'sender', 'domain', 'brand']

/**
 * Clave del rótulo de una señal por la que un mensaje entró en una campaña.
 *
 * @param {string} signal - `url`, `hash`, `template`, `subject`, `sender`,
 *   `domain` o `brand`.
 * @returns {string} `iris.campaigns.signals.<señal>`, o `common.unknown` si no se conoce.
 */
export function campaignSignalKey(signal) {
  return CAMPAIGN_SIGNALS.includes(signal) ? `iris.campaigns.signals.${signal}` : 'common.unknown'
}

const CONTACT_DEVIATIONS = ['display_name_reuse', 'address_domain_change']

/**
 * Clave de la frase que explica cómo imita un remitente a un contacto habitual.
 *
 * @param {string} kind - `display_name_reuse` o `address_domain_change`.
 * @returns {string} `iris.report.deviation.<tipo>`, o `iris.report.deviation.other`
 *   si no se conoce. Las frases llevan los huecos `sender`, `name`,
 *   `habitual` y `count`.
 */
export function contactDeviationKey(kind) {
  return `iris.report.deviation.${CONTACT_DEVIATIONS.includes(kind) ? kind : 'other'}`
}
