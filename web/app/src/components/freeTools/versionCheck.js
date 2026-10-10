/**
 * Lógica sin Vue de la herramienta gratuita «¿Es vulnerable mi versión?»
 * (`views/tools/themis/VersionCheckView.vue`), para poder probarla con `node` a
 * secas. La correlación la hace el motor de Lybra en `GET /themis/kb/version`;
 * aquí solo se valida lo escrito y se decide cómo enseñar la respuesta.
 */

import { severityOf } from './cvss.js'

/** Mismo formato de versión que acepta el servidor: empieza por letra o cifra, hasta 40 caracteres. */
const VERSION_PATTERN = /^[0-9A-Za-z][0-9A-Za-z.+~_:-]{0,39}$/

/** Longitud máxima del nombre de producto, la misma que en el servidor. */
export const MAX_PRODUCT_LENGTH = 80

/** Ejemplos que se pueden probar con un clic: ramas viejas de software muy expuesto. */
export const VERSION_EXAMPLES = Object.freeze([
  Object.freeze({ product: 'nginx', version: '1.18.0' }),
  Object.freeze({ product: 'OpenSSH', version: '8.9' }),
  Object.freeze({ product: 'Apache httpd', version: '2.4.49' }),
])

/**
 * @param {unknown} text - Versión escrita, ya sin espacios alrededor o no.
 * @returns {boolean} `true` si, sin espacios alrededor, tiene el formato que acepta
 *   el servidor.
 */
export function isVersion(text) {
  return typeof text === 'string' && VERSION_PATTERN.test(text.trim())
}

/**
 * @param {unknown} text - Nombre de producto escrito.
 * @returns {boolean} `true` si, sin espacios alrededor, no está vacío y cabe en
 *   `MAX_PRODUCT_LENGTH`.
 */
export function isProduct(text) {
  return typeof text === 'string' && text.trim().length > 0 && text.trim().length <= MAX_PRODUCT_LENGTH
}

/**
 * Gravedad de una CVE a partir de su puntuación, con los tramos de CVSS 3.
 *
 * @param {number|null|undefined} score - CVSS base de 0 a 10; `null` si NVD aún no la
 *   puntúa.
 * @returns {string} `none`, `low`, `medium`, `high` o `critical`, o `unrated` sin
 *   puntuación. Es lo que esperan `severityLabelKey` y el CSS de la gravedad.
 */
export function cvssSeverity(score) {
  return typeof score === 'number' ? severityOf(score) : 'unrated'
}

/**
 * Qué decir del fin de soporte.
 *
 * @param {{isPast: boolean}|null|undefined} endOfLife - Lo que manda el servidor.
 * @returns {'past'|'supported'|null} `past` si la rama ya no recibe parches;
 *   `supported` si tiene fecha y aún no llegó; `null` si el catálogo no la conoce.
 */
export function endOfLifeState(endOfLife) {
  if (!endOfLife) return null
  return endOfLife.isPast ? 'past' : 'supported'
}
