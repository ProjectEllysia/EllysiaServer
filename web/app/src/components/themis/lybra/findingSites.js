/**
 * A qué web pertenece cada hallazgo de Lybra.
 *
 * Un mismo servidor puede alojar varias webs en la misma dirección, y el motor
 * revisa cada una por separado: el mismo aviso puede salir en dos de ellas.
 * Sin decir de cuál es cada fila, las dos se leen como un duplicado.
 */

/** Marca con la que el backend nombra el sitio que responde sin nombre. */
const DEFAULT_SITE_MARKER = '(sitio por defecto)'

/** Explicación que acompaña a la etiqueta del sitio al pasar el ratón. */
export const SITE_HINT = 'Este servidor aloja varias webs en la misma dirección y cada una se '
  + 'revisa por separado: el mismo aviso puede aparecer en más de una, y hay que '
  + 'corregirlo en cada web donde aparezca.'

/**
 * Indica si un grupo mezcla hallazgos de varias webs.
 *
 * Sólo entonces merece la pena etiquetar cada fila: en un grupo de una única
 * web la etiqueta no distingue nada. El grupo de sitios detectados queda
 * fuera, porque el título de cada fila ya es el sitio.
 *
 * @param {{ findings: Array<{ vhost?: string|null, category?: string }> }} group
 *   Grupo tal como lo devuelve la API, con sus hallazgos.
 * @returns {boolean} `true` si hay al menos dos webs distintas en el grupo
 *   (contando la que responde al entrar por la IP); `false` en otro caso.
 */
export function hasSeveralSites(group) {
  const findings = group?.findings || []
  if (findings.some(finding => finding.category === 'virtual_host')) return false
  return new Set(findings.map(finding => siteLabel(finding))).size > 1
}

/**
 * Nombra la web de un hallazgo para el usuario.
 *
 * @param {{ vhost?: string|null }} finding Hallazgo tal como lo devuelve la
 *   API. `vhost` es el nombre de la web, `null` si el hallazgo se obtuvo
 *   entrando por la IP, o la marca del sitio por defecto, que significa lo
 *   mismo.
 * @returns {string} `"Al entrar por la IP"` o `"En <nombre de la web>"`.
 */
export function siteLabel(finding) {
  const vhost = finding?.vhost
  if (!vhost || vhost === DEFAULT_SITE_MARKER) return 'Al entrar por la IP'
  return `En ${vhost}`
}
