/**
 * Lo que Lybra ve más allá de un único equipo, preparado para pintarlo: la
 * exposición en la nube de un dominio, el riesgo de movimiento lateral de una
 * red y qué escaneos son de red.
 *
 * Sin Vue ni textos (CONVENCIONES.md §12.5): devuelve claves y estructuras, y
 * quien pinta elige la frase. Se prueba con `node` a secas.
 */

import { classifyTarget } from './targetShapes.js'

/** Las cuatro reglas de riesgo lateral que tiene el motor hoy. */
export const LATERAL_RULES = Object.freeze(['exposed-service', 'shared-vulnerability', 'multi-homed', 'shared-credentials'])

/** Los cuatro proveedores cloud que se pueden declarar. */
export const CLOUD_PROVIDERS = Object.freeze(['s3', 'gcs', 'azure', 'firebase'])

// Un rango IPv4 escrito como `192.168.1.1-10`: la otra forma de pedir una red.
const IPV4_RANGE_RE = /^\d{1,3}(\.\d{1,3}){3}-\d{1,3}$/

/**
 * Si un escaneo Lybra es de red: el padre de un escaneo por equipo.
 *
 * El listado no dice cuántos hijos tiene un escaneo, pero sí su objetivo, y
 * solo un rango (`10.0.0.0/24`, `192.168.1.1-10`) produce hijos. Un escaneo
 * hijo lleva `parentScanId` y nunca es de red.
 *
 * @param {{target?: string, parentScanId?: number|null}} scan - Escaneo del listado.
 * @returns {boolean} `true` si su objetivo es un rango de más de una dirección.
 */
export function isNetworkScan(scan) {
  if (!scan || scan.parentScanId) return false
  const target = (scan.target || '').trim()
  if (IPV4_RANGE_RE.test(target)) return true
  if (classifyTarget(target) !== 'network' || !target.includes('/')) return false
  const prefix = Number(target.split('/')[1])
  return target.includes(':') ? prefix < 128 : prefix < 32
}

/**
 * Clave de diccionario de una regla de riesgo lateral.
 *
 * El diccionario usa camelCase (`lybra.lateral.rules.exposedService`) porque
 * un guion dentro de una ruta de clave no es un identificador.
 *
 * @param {string} rule - La regla que manda el servidor (`exposed-service`…).
 * @returns {string} La regla en camelCase si se conoce; `unknown` si no, para
 *          que una regla nueva del motor se lea con un rótulo genérico.
 */
export function lateralRuleKey(rule) {
  if (!LATERAL_RULES.includes(rule)) return 'unknown'
  return rule.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())
}

/**
 * Cómo se reparte el alcance de un riesgo en la red, para dibujar un rombo por
 * equipo.
 *
 * Los rombos se cortan en `limit` para que una red de doscientos equipos no
 * ocupe la pantalla: los que no caben se cuentan aparte.
 *
 * @param {{hosts?: Array}} risk - Riesgo de `GET /themis/network-risk`.
 * @param {number} hostCount - Equipos que tiene la red analizada.
 * @param {number} [limit=24] - Rombos que se dibujan como mucho.
 * @returns {{marks: boolean[], hidden: number, involved: number}} `marks` trae
 *          un `true` por equipo implicado y un `false` por cada uno que no, en
 *          ese orden; `hidden`, los equipos que no caben; `involved`, cuántos
 *          implica el riesgo.
 */
export function reachMarks(risk, hostCount, limit = 24) {
  const total = Math.max(hostCount || 0, risk?.hosts?.length || 0)
  const involved = Math.min(risk?.hosts?.length || 0, total)
  const shown = Math.min(total, limit)
  const filled = Math.min(involved, shown)
  const marks = Array.from({ length: shown }, (_, index) => index < filled)
  return { marks, hidden: total - shown, involved }
}

/**
 * Proveedor de un recurso cloud declarado, para rotularlo.
 *
 * @param {string} subject - El recurso canónico (`s3:nombre`).
 * @returns {string} `s3`, `gcs`, `azure` o `firebase`; `unknown` si no lo es.
 */
export function cloudProviderKey(subject) {
  const provider = String(subject || '').split(':', 1)[0].toLowerCase()
  return CLOUD_PROVIDERS.includes(provider) ? provider : 'unknown'
}

/**
 * El veredicto de cada cosa que se comprobó en un escaneo cloud.
 *
 * El escaneo solo guarda hallazgos, pero lo que el usuario quiere saber es qué
 * pasó con **cada** recurso que declaró: los que no tienen hallazgo quedaron
 * cerrados, y decirlo es tan informativo como señalar los abiertos. Los
 * hallazgos que no son de un recurso declarado son de subdominios.
 *
 * @param {{cloudResources?: string[], findings?: Array}} scan - Detalle de
 *        `GET /themis/osint/<id>`.
 * @returns {{resources: Array<{subject: string, finding: object|null}>,
 *            subdomains: Array<object>}} Los recursos en el orden en que se
 *          declararon, cada uno con su hallazgo o `null`; y los hallazgos de
 *          subdominio.
 */
export function cloudVerdicts(scan) {
  const findings = scan?.findings || []
  const declared = (scan?.cloudResources || []).map(subject => subject.toLowerCase())
  const bySubject = new Map(findings.map(finding => [String(finding.service || '').toLowerCase(), finding]))
  return {
    resources: declared.map(subject => ({ subject, finding: bySubject.get(subject) || null })),
    subdomains: findings.filter(finding => !declared.includes(String(finding.service || '').toLowerCase())),
  }
}

/**
 * Si un objetivo está cubierto por el registro de objetivos autorizados.
 *
 * Es una comprobación en el navegador para avisar antes de lanzar; la que
 * cuenta la hace el servidor. Un dominio registrado cubre sus subdominios; un
 * recurso cloud, solo a sí mismo. Las redes no se comprueban aquí: eso lo hace
 * el panel del motor, que lanza contra direcciones.
 *
 * @param {string} target - Lo que se quiere lanzar (dominio o recurso cloud).
 * @param {Array<{target: string}>} entries - El registro del usuario.
 * @returns {boolean} `true` si alguna entrada lo cubre.
 */
export function isCoveredByRegister(target, entries) {
  const needle = String(target || '').trim().toLowerCase().replace(/\.$/, '')
  const shape = classifyTarget(needle)
  if (!needle || (shape !== 'domain' && shape !== 'cloud')) return false
  return (entries || []).some(({ target: entry }) => {
    const registered = String(entry || '').toLowerCase()
    if (shape === 'cloud') return registered === needle
    return classifyTarget(registered) === 'domain'
      && (needle === registered || needle.endsWith(`.${registered}`))
  })
}
