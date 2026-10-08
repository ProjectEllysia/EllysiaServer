/**
 * Lógica sin Vue de la herramienta gratuita «Consulta de CVE»
 * (`views/tools/aegis/CveLookupView.vue`), para poder probarla con `node` a
 * secas. Los datos vienen de `GET /themis/kb/cve`.
 */

/** Mismo formato que acepta el servidor: `CVE-AAAA-NNNN` con 4 a 7 cifras. */
const CVE_ID_PATTERN = /^CVE-\d{4}-\d{4,7}$/

/**
 * Deja un identificador como lo espera el servidor.
 *
 * @param {unknown} text - Lo que haya escrito o pegado el usuario.
 * @returns {string} El texto sin espacios alrededor ni dentro (`cve - 2024 - 6387`
 *   se pega a veces con huecos) y en mayúsculas. Vacío si no es texto.
 */
export function normalizeCveId(text) {
  if (typeof text !== 'string') return ''
  return text.replace(/\s+/g, '').toUpperCase()
}

/**
 * @param {unknown} text - Texto ya normalizado o no.
 * @returns {boolean} `true` si, normalizado, es un identificador de CVE completo.
 */
export function isCveId(text) {
  return CVE_ID_PATTERN.test(normalizeCveId(text))
}

/** Gravedades que conoce la interfaz, de la más a la menos grave. */
export const CVE_SEVERITIES = Object.freeze(['critical', 'high', 'medium', 'low', 'none'])

/**
 * Clave del diccionario con el rótulo de una gravedad.
 *
 * @param {unknown} severity - Gravedad que manda el servidor (`CRITICAL`, `high`…);
 *   puede venir vacía si NVD aún no puntúa la CVE.
 * @returns {string} `freeTools.items.cveLookup.severity.<nivel>`; una gravedad que
 *   la interfaz no conoce sale como `unrated` en vez de enseñarse en crudo.
 */
export function severityLabelKey(severity) {
  const level = typeof severity === 'string' ? severity.toLowerCase() : ''
  return `freeTools.items.cveLookup.severity.${CVE_SEVERITIES.includes(level) ? level : 'unrated'}`
}

/**
 * Gravedad normalizada para pintar el color, que el CSS elige por atributo.
 *
 * @param {unknown} severity - La que manda el servidor.
 * @returns {string} Uno de `CVE_SEVERITIES`, o `unrated`.
 */
export function severityLevel(severity) {
  const level = typeof severity === 'string' ? severity.toLowerCase() : ''
  return CVE_SEVERITIES.includes(level) ? level : 'unrated'
}

/**
 * Convierte la probabilidad EPSS (0 a 1) en un porcentaje legible.
 *
 * @param {number|null|undefined} score - Probabilidad de explotación en los próximos
 *   30 días, de 0 a 1; `null` si la fuente no puntúa la CVE.
 * @returns {number|null} El porcentaje (de 0 a 100) con un decimal, o `null` si no hay dato.
 */
export function epssPercent(score) {
  if (typeof score !== 'number' || !Number.isFinite(score)) return null
  return Math.round(Math.min(1, Math.max(0, score)) * 1000) / 10
}

/**
 * Cuántos elementos de una lista recortada por el servidor no se muestran.
 *
 * @param {Array} shown - Los que llegaron.
 * @param {number|undefined} total - Cuántos hay en total según el servidor.
 * @returns {number} La diferencia; `0` si no hay total o no es mayor que lo mostrado.
 */
export function hiddenCount(shown, total) {
  if (!Array.isArray(shown) || typeof total !== 'number') return 0
  return Math.max(0, total - shown.length)
}

/** Estados que una distribución da a un paquete frente a una CVE. */
export const DISTRO_STATUSES = Object.freeze(['fixed', 'vulnerable', 'unknown'])

/**
 * Clave del diccionario con el rótulo del estado de un paquete en una distribución.
 *
 * @param {unknown} status - Estado que manda el servidor (`fixed`, `vulnerable`, `unknown`).
 * @returns {string} `freeTools.items.cveLookup.distroStatus.<estado>`; un valor que
 *   la interfaz no conoce se enseña como `unknown`, nunca en crudo.
 */
export function distroStatusLabelKey(status) {
  return `freeTools.items.cveLookup.distroStatus.${DISTRO_STATUSES.includes(status) ? status : 'unknown'}`
}
