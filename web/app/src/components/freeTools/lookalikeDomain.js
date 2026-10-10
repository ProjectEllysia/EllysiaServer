/**
 * Lógica sin Vue del detector de dominios engañosos gratuito
 * (`views/tools/iris/LookalikeDomainView.vue`), para poder probarla con `node` a
 * secas. El juicio lo hacen las reglas de Iris en `GET /iris/tools/domain`; aquí
 * solo se decide cómo enseñarlo.
 */

/** Tipos de hallazgo que devuelve el servidor, con su texto en `freeTools.items.lookalikeDomain.findings`. */
export const FINDING_TYPES = Object.freeze([
  'idn_homograph',
  'idn_mixed_script',
  'cousin',
  'homoglyph',
  'typo',
  'brand_in_subdomain',
  'brand_action_combo',
])

/** Alfabetos con nombre traducido; el resto se enseña con el nombre de Unicode. */
export const NAMED_SCRIPTS = Object.freeze(['LATIN', 'CYRILLIC', 'GREEK'])

/** Ejemplos que se pueden probar con un clic: un homógrafo con «а» cirílica, un homóglifo con un 1 y una marca de subdominio. */
export const DOMAIN_EXAMPLES = Object.freeze(['pаypal.com', 'paypa1.com', 'github.com.sessions-security.com'])

/**
 * Clave del texto que explica un hallazgo.
 *
 * @param {unknown} type - Tipo de hallazgo que manda el servidor.
 * @returns {string} `freeTools.items.lookalikeDomain.findings.<tipo>`; un tipo que
 *   la interfaz no conoce cae en `other`, en vez de enseñarse en crudo.
 */
export function findingLabelKey(type) {
  return `freeTools.items.lookalikeDomain.findings.${FINDING_TYPES.includes(type) ? type : 'other'}`
}

/**
 * Nombre legible de un alfabeto de Unicode.
 *
 * @param {string} script - Nombre de Unicode, en mayúsculas (`CYRILLIC`).
 * @param {(key: string) => string} translate - El `t` de vue-i18n.
 * @returns {string} El nombre traducido si es uno de `NAMED_SCRIPTS`; si no, el de
 *   Unicode con solo la inicial en mayúscula (`Armenian`).
 */
export function scriptName(script, translate) {
  if (NAMED_SCRIPTS.includes(script)) return translate(`freeTools.items.lookalikeDomain.scripts.${script}`)
  const lower = String(script).toLowerCase()
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

/**
 * Qué veredicto enseñar arriba del resultado.
 *
 * @param {{isSuspicious: boolean, ownBrand: string|null}} result - Respuesta del servidor.
 * @returns {'suspicious'|'ownBrand'|'clean'} `suspicious` si imita a una marca;
 *   `ownBrand` si es el dominio de la propia marca; `clean` en otro caso.
 */
export function verdictOf(result) {
  if (result.isSuspicious) return 'suspicious'
  return result.ownBrand ? 'ownBrand' : 'clean'
}
