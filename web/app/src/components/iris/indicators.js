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

/**
 * Frase con el contexto de infraestructura (RDAP) de un dominio.
 *
 * Sin datos del registro —no respondió, cupo agotado o consultas apagadas— la
 * frase lo dice sin sacar ninguna conclusión: es el modo neutro.
 *
 * @param {object|null} context - Respuesta de `GET /iris/domains/<dominio>/context`.
 * @param {Function} t - Función de traducción de vue-i18n.
 * @returns {string} La frase en el idioma activo.
 */
export function describeDomainContext(context, t) {
  if (!context) return t('iris.enrichment.unavailable')
  if (context.status === 'rate_limited') return t('iris.enrichment.rateLimited')
  if (context.status === 'disabled') return t('iris.enrichment.disabled')
  if (context.status !== 'ok') return t('iris.enrichment.unavailable')
  const parts = []
  if (context.ageDays !== null && context.ageDays !== undefined) {
    parts.push(t(context.isRecentlyRegistered ? 'iris.enrichment.ageRecent' : 'iris.enrichment.age', { days: context.ageDays }))
  }
  if (context.registrar) parts.push(t('iris.enrichment.registrar', { name: context.registrar }))
  if (context.networkName || context.country) {
    parts.push(t('iris.enrichment.network', { name: context.networkName || '—', country: context.country || '—' }))
  }
  if (context.asn) parts.push(context.asn)
  return parts.length ? parts.join(' · ') : t('iris.enrichment.noData')
}

const HOP_ERRORS = ['private_address', 'scheme', 'port', 'unresolvable', 'timeout', 'tls', 'connection', 'protocol', 'too_many_redirects']

/**
 * Frase con a dónde lleva de verdad una URL tras seguir sus redirects.
 *
 * @param {object|null} expansion - Una expansión de `GET /iris/results/<id>/url-expansions`.
 * @param {Function} t - Función de traducción de vue-i18n.
 * @returns {string} La frase en el idioma activo: saltos, destino, título de
 *   la página, si cambia de dominio y, si la cadena se cortó, por qué.
 */
export function describeUrlExpansion(expansion, t) {
  if (!expansion) return t('iris.enrichment.unavailable')
  if (expansion.status === 'rate_limited') return t('iris.enrichment.rateLimited')
  if (expansion.status === 'disabled') return t('iris.enrichment.disabled')
  if (['pending', 'running'].includes(expansion.status)) return t('iris.enrichment.stillExpanding')
  const parts = []
  const redirects = Math.max(0, (expansion.hops?.length ?? 1) - 1)
  if (expansion.finalUrl) {
    parts.push(t('iris.enrichment.leadsTo', { count: redirects, domain: expansion.finalDomain || expansion.finalUrl }))
  }
  if (expansion.isDomainChanged) parts.push(t('iris.enrichment.domainChanged'))
  if (expansion.pageTitle) parts.push(t('iris.enrichment.pageTitle', { title: expansion.pageTitle }))
  const lastError = expansion.hops?.at(-1)?.error
  if (lastError) {
    parts.push(t(`iris.enrichment.hopErrors.${HOP_ERRORS.includes(lastError) ? lastError : 'other'}`))
  }
  return parts.length ? parts.join(' · ') : t('iris.enrichment.unavailable')
}

const REPUTATION_VERDICTS = ['known_malicious', 'suspicious', 'unknown', 'unavailable', 'rate_limited']
const PROVIDER_NAMES = { virustotal: 'VirusTotal', urlscan: 'urlscan.io', phishtank: 'PhishTank', urlhaus: 'URLhaus' }

/**
 * Clave del rótulo de un veredicto de reputación.
 *
 * @param {string} verdict - `known_malicious`, `suspicious`, `unknown`,
 *   `unavailable` o `rate_limited`.
 * @returns {string} `iris.enrichment.reputationVerdicts.<veredicto>`, o el de
 *   `unavailable` si no se conoce.
 */
export function reputationVerdictKey(verdict) {
  return `iris.enrichment.reputationVerdicts.${REPUTATION_VERDICTS.includes(verdict) ? verdict : 'unavailable'}`
}

/**
 * Frase con la reputación de un indicador en los proveedores configurados.
 *
 * @param {object|null} result - Respuesta de `POST /iris/indicators/reputation`.
 * @param {Function} t - Función de traducción de vue-i18n.
 * @returns {string} El veredicto global y el de cada proveedor.
 */
export function describeReputation(result, t) {
  if (!result) return t('iris.enrichment.unavailable')
  if (result.status === 'disabled') return t('iris.enrichment.disabled')
  if (result.status === 'not_configured') return t('iris.enrichment.notConfigured')
  const providers = (result.providers ?? [])
    .map((provider) => `${PROVIDER_NAMES[provider.provider] ?? provider.provider}: ${t(reputationVerdictKey(provider.verdict))}`)
  const summary = t(reputationVerdictKey(result.verdict))
  return [summary.charAt(0).toUpperCase() + summary.slice(1), ...providers].join(' · ')
}
