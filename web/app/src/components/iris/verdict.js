/**
 * Claves de diccionario de los valores cerrados que Iris recibe del servidor:
 * veredicto y estado de un análisis, y categoría y resultado de cada regla.
 *
 * Viven aquí y no en cada componente porque los pintan la tira del
 * historial, el archivo, el comparador, los documentos, los casos y el
 * informe: con un mapa por fichero, al traducir uno el de al lado seguía sin
 * traducir (CONVENCIONES.md § 12.2). Todas caen en una clave genérica ante un
 * valor desconocido, nunca en el crudo.
 *
 * Devuelven claves y no textos porque este módulo se prueba en Node, sin la
 * aplicación ni su diccionario: el componente pinta `t(verdictKey(valor))`.
 */

const VERDICTS = ['legitimate', 'suspicious', 'phishing']
const VERDICT_CLASSES = { legitimate: 'legit', suspicious: 'susp', phishing: 'phish' }

/**
 * Clave del rótulo del veredicto de un análisis.
 *
 * @param {string|null} verdict - Veredicto del servidor (`Legitimate`,
 *   `Suspicious` o `Phishing`); no distingue mayúsculas.
 * @returns {string} `iris.verdict.<veredicto>`, o `iris.verdict.none` si
 *   falta o no se conoce.
 */
export function verdictKey(verdict) {
  const value = verdict?.toLowerCase()
  return `iris.verdict.${VERDICTS.includes(value) ? value : 'none'}`
}

/**
 * Sufijo de clase CSS con el que se colorea un veredicto.
 *
 * @param {string|null} verdict - Veredicto del servidor; no distingue mayúsculas.
 * @returns {'legit'|'susp'|'phish'|'unknown'} El tono del veredicto, o
 *   `'unknown'` si falta o no se conoce.
 */
export function verdictClass(verdict) {
  return VERDICT_CLASSES[verdict?.toLowerCase()] || 'unknown'
}

const ANALYSIS_STATUSES = ['pending', 'running', 'finished', 'failed', 'cancelled']

/**
 * Clave del rótulo del estado de un análisis.
 *
 * @param {string|null} status - `pending`, `running`, `finished`, `failed` o `cancelled`.
 * @returns {string} `iris.analysisStatus.<estado>`, o `common.unknown` si no se conoce.
 */
export function analysisStatusKey(status) {
  return ANALYSIS_STATUSES.includes(status) ? `iris.analysisStatus.${status}` : 'common.unknown'
}

const RULE_CATEGORIES = ['authentication', 'header_analysis', 'content_analysis']

/**
 * Clave del rótulo de la categoría de una regla.
 *
 * @param {string|null} category - `authentication`, `header_analysis` o `content_analysis`.
 * @returns {string} `iris.ruleCategory.<categoría>`, o `iris.ruleCategory.other`
 *   si no se conoce.
 */
export function ruleCategoryKey(category) {
  return `iris.ruleCategory.${RULE_CATEGORIES.includes(category) ? category : 'other'}`
}

/**
 * Resultados de regla. Muchos son los resultados estándar de SPF, DKIM y
 * DMARC (`softfail`, `bestguess`…); el código exacto no se pierde, pasa al
 * tooltip de la tarjeta (CONVENCIONES.md § 12.3). DMARC añade `bestguess`
 * (sin registro, pero pasaría si lo tuviera), `policy` y `none`; los
 * destinatarios, `empty`, `empty_to` y `undisclosed`; la cabecera Date,
 * `future`, `past` y `unparseable`.
 */
const RULE_VERDICTS = [
  'pass', 'fail', 'softfail', 'suspicious', 'neutral', 'missing', 'error', 'trusted',
  'bestguess', 'policy', 'none', 'spoof',
  'empty', 'empty_to', 'undisclosed',
  'future', 'past', 'unparseable',
]

/**
 * Clave del rótulo del resultado de una regla.
 *
 * @param {string|null} verdict - Resultado que emite la regla (`pass`,
 *   `fail`, `softfail`, `bestguess`, `empty_to`…).
 * @returns {string} `iris.ruleVerdict.<resultado>`, o `iris.ruleVerdict.other`
 *   si no se conoce.
 */
export function ruleVerdictKey(verdict) {
  return `iris.ruleVerdict.${RULE_VERDICTS.includes(verdict) ? verdict : 'other'}`
}
