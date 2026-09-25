/**
 * Traducción de los errores de la API al idioma de la interfaz.
 *
 * El servidor contesta a un error con su texto en castellano
 * (`error_description`) y, cuando ese texto sale entero de una plantilla, con
 * la referencia a la plantilla: `messageKey` (qué frase es) y `params` (con qué
 * valores se rellena). Así el servidor no necesita saber en qué idioma está el
 * usuario: la interfaz busca la plantilla en `apiErrors` de su diccionario y la
 * rellena ella.
 *
 * Un error sin `messageKey`, o con una clave que el diccionario no conoce (un
 * servidor más nuevo que la interfaz), no se traduce: quien llama enseña el
 * texto del servidor.
 *
 * `API/tests/unit/test_shared_error_messages.py` comprueba que cada plantilla
 * de `apiErrors` en `locales/es.json` da exactamente el texto del servidor.
 */
import { DEFAULT_LOCALE } from './locale.js'

/**
 * Devuelve el texto de un error de la API en el idioma de la interfaz.
 *
 * @param {object|null|undefined} body - Cuerpo JSON de la respuesta de error.
 *   Se usan `body.messageKey` (cadena, p. ej. `"missingParameter"` o
 *   `"entityNotFound.scan"`) y `body.params` (objeto con los valores de los
 *   huecos de la plantilla).
 * @param {{ t: Function, te: Function }} translator - El `t` y el `te` de
 *   vue-i18n (`i18n.global` fuera de un componente). Se reciben como
 *   argumento para poder probar la función sin montar la aplicación.
 * @returns {string|null} El texto traducido, o `null` si el error no trae
 *   clave o el diccionario no la tiene; entonces quien llama usa el texto del
 *   servidor.
 */
export function translateApiError(body, translator) {
  const messageKey = body?.messageKey
  if (typeof messageKey !== 'string' || !messageKey) return null
  const path = `apiErrors.${messageKey}`
  // El idioma por defecto tiene todas las plantillas; si el activo no tiene
  // esta, `t` cae a él.
  if (!translator.te(path) && !translator.te(path, DEFAULT_LOCALE)) return null
  const params = body.params && typeof body.params === 'object' ? body.params : {}
  return translator.t(path, params)
}
