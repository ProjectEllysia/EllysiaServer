/**
 * Formato de fechas, números y orden de textos según el idioma activo.
 *
 * Son envoltorios finos de `Intl`: reciben las mismas opciones que
 * `toLocaleDateString`, `toLocaleString` o `Intl.Collator`, y lo único que
 * añaden es el idioma, que sale de `activeLocale` en vez de ir escrito a mano en
 * cada llamada. Las opciones describen *qué* piezas mostrar (día, mes, hora);
 * el *orden* y los separadores los decide el idioma, así que la misma llamada
 * da «05/03/2026» en castellano y «03/05/2026» en inglés de EE. UU.
 *
 * Al leer `activeLocale`, un `computed` o una plantilla que las usen se vuelven
 * a pintar al cambiar de idioma.
 *
 * Se importan con ruta relativa desde los módulos que se prueban con `node` a
 * secas, que no conocen el alias `@`.
 */
import { activeLocale } from './locale.js'

/**
 * Formatea la parte de fecha de un instante en el idioma activo.
 *
 * @param {string|number|Date} value - Instante a formatear: fecha ISO 8601,
 *   milisegundos desde la época o un `Date`.
 * @param {Intl.DateTimeFormatOptions} [options] - Piezas a mostrar, como en
 *   `Date.prototype.toLocaleDateString`. Sin opciones, la fecha numérica
 *   corta del idioma. Si incluyen la hora, también se muestra.
 * @returns {string} La fecha formateada. Un valor que no es una fecha válida
 *   devuelve `"Invalid Date"`, como `Date`; quien pueda recibir un vacío lo
 *   comprueba antes.
 */
export function formatDate(value, options) {
  return new Date(value).toLocaleDateString(activeLocale.value, options)
}

/**
 * Formatea un instante con fecha y hora en el idioma activo.
 *
 * @param {string|number|Date} value - Instante a formatear: fecha ISO 8601,
 *   milisegundos desde la época o un `Date`.
 * @param {Intl.DateTimeFormatOptions} [options] - Piezas a mostrar, como en
 *   `Date.prototype.toLocaleString`. Sin opciones, fecha y hora completas.
 * @returns {string} El instante formateado, o `"Invalid Date"` si el valor no
 *   es una fecha válida.
 */
export function formatDateTime(value, options) {
  return new Date(value).toLocaleString(activeLocale.value, options)
}

/**
 * Formatea un número con los separadores de miles y decimales del idioma activo.
 *
 * @param {number} value - Número a formatear.
 * @param {Intl.NumberFormatOptions} [options] - Opciones de
 *   `Number.prototype.toLocaleString` (`maximumFractionDigits`, `style`…).
 * @returns {string} El número formateado.
 */
export function formatNumber(value, options) {
  return Number(value).toLocaleString(activeLocale.value, options)
}

/**
 * Comparadores de texto ya construidos, por idioma y opciones.
 *
 * @type {Map<string, Intl.Collator>}
 */
const collatorsByKey = new Map()

/**
 * Devuelve un comparador de textos con las reglas de orden alfabético del
 * idioma activo.
 *
 * El orden alfabético depende del idioma (la «ñ» va tras la «n» en castellano;
 * en otros idiomas, no), así que ordenar con `<` o sin idioma pondría las
 * palabras con tilde o eñe al final.
 *
 * Construir un `Intl.Collator` es caro, y `localeCompare` con idioma construye
 * uno por llamada: en una ordenación de miles de elementos eso es la mayor
 * parte del tiempo. Por eso se guardan y se reutilizan; quien ordena pide el
 * comparador una vez, antes de ordenar, no dentro de la función de comparación.
 *
 * @param {Intl.CollatorOptions} [options] - Opciones de `Intl.Collator`;
 *   `{ numeric: true }` ordena «host2» antes que «host10». Por defecto, ninguna.
 * @returns {Intl.Collator} Siempre un comparador; su `compare(left, right)`
 *   devuelve negativo, cero o positivo, como espera `Array.prototype.sort`.
 */
export function getCollator(options = {}) {
  const key = `${activeLocale.value}|${JSON.stringify(options)}`
  let collator = collatorsByKey.get(key)
  if (!collator) {
    collator = new Intl.Collator(activeLocale.value, options)
    collatorsByKey.set(key, collator)
  }
  return collator
}
