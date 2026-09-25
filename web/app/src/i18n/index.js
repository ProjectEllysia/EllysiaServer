/**
 * Mecanismo de idiomas de la interfaz (vue-i18n).
 *
 * Cada idioma es un fichero de `locales/` con el mismo árbol de claves que
 * `locales/es.json`. Los ficheros se descubren solos con `import.meta.glob`:
 * añadir `locales/en.json` basta para que el inglés exista, sin tocar este
 * fichero ni ningún componente.
 *
 * Un texto que falte en un idioma se muestra en el idioma por defecto
 * (`DEFAULT_LOCALE`), nunca como su clave: un idioma a medio traducir se lee
 * mezclado, pero se lee.
 *
 * @example
 * // En un componente:
 * const { t } = useI18n()
 * t('shell.logout')
 * // Fuera de un componente (stores, composables):
 * import { i18n } from '@/i18n'
 * i18n.global.t('shell.logout')
 */
import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import { DEFAULT_LOCALE, activeLocale } from './locale.js'

const localeModules = import.meta.glob('./locales/*.json', { eager: true, import: 'default' })

/**
 * Textos de cada idioma, indexados por su código (el nombre del fichero sin
 * extensión).
 *
 * @type {Record<string, object>}
 */
const messagesByLocale = Object.fromEntries(
  Object.entries(localeModules).map(([path, messages]) => [path.match(/([^/]+)\.json$/)[1], messages]),
)

/**
 * Códigos de los idiomas que tienen fichero en `locales/`, en orden alfabético.
 *
 * @type {string[]}
 */
export const AVAILABLE_LOCALES = Object.keys(messagesByLocale).sort()

/**
 * Nombre de un idioma en sí mismo, según su fichero de textos.
 *
 * @param {string} localeCode - Código del idioma.
 * @returns {string} El nombre («English»), o el código si su fichero no lo trae.
 */
export function localeName(localeCode) {
  return messagesByLocale[localeCode]?.language?.name ?? localeCode
}

/**
 * Opciones para un selector de idioma: cada idioma con el nombre que se da a
 * sí mismo, así que uno nuevo aparece con solo añadir su fichero.
 *
 * @type {Array<{ code: string, name: string }>}
 */
export const LOCALE_OPTIONS = AVAILABLE_LOCALES.map((code) => ({ code, name: localeName(code) }))

/**
 * Clave en localStorage del último idioma elegido en este dispositivo.
 *
 * Es solo el recuerdo local: sirve para que la interfaz arranque en el idioma
 * que el usuario eligió la última vez, también antes de iniciar sesión. No se
 * usa el idioma del navegador mientras ningún idioma aparte del castellano
 * esté completo: un navegador en inglés vería la interfaz mezclada nada más
 * entrar, sin haber pedido nada.
 */
const STORAGE_KEY = 'ellysia_locale'

/**
 * Lee el idioma guardado en este dispositivo.
 *
 * @returns {string|null} El código guardado si existe y tiene fichero en
 *   `locales/`; `null` si no hay ninguno, no es válido o el navegador no deja
 *   leer localStorage (modo privado estricto, almacenamiento bloqueado).
 */
function readStoredLocale() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return AVAILABLE_LOCALES.includes(stored) ? stored : null
  } catch {
    return null
  }
}

/**
 * Guarda el idioma elegido en este dispositivo.
 *
 * Un fallo al escribir (almacenamiento bloqueado o lleno) se ignora: el idioma
 * ya está aplicado y solo se pierde el recuerdo para la próxima visita.
 *
 * @param {string} localeCode - Código del idioma que se acaba de aplicar.
 */
function storeLocale(localeCode) {
  try {
    localStorage.setItem(STORAGE_KEY, localeCode)
  } catch {
    // Sin almacenamiento, el idioma dura lo que dure la pestaña.
  }
}

activeLocale.value = readStoredLocale() ?? DEFAULT_LOCALE

/**
 * Instancia de vue-i18n de la aplicación, en modo composición (`useI18n`).
 *
 * `missingWarn` y `fallbackWarn` avisan en consola solo en desarrollo: en
 * producción un texto que cae al idioma por defecto es el comportamiento
 * esperado de un idioma incompleto, no un fallo.
 */
export const i18n = createI18n({
  legacy: false,
  locale: activeLocale.value,
  fallbackLocale: DEFAULT_LOCALE,
  messages: messagesByLocale,
  missingWarn: import.meta.env.DEV,
  fallbackWarn: false,
})

/**
 * Cambia el idioma de la interfaz y lo recuerda en este dispositivo.
 *
 * Un código sin fichero en `locales/` se ignora y la interfaz sigue en el
 * idioma que tenía: mejor eso que una pantalla llena de textos de respaldo por
 * una preferencia mal escrita.
 *
 * @param {string} localeCode - Código del idioma (`'es'`, y los que se añadan
 *   a `locales/`).
 * @returns {boolean} `true` si el idioma existía y se aplicó; `false` si no
 *   existe y no se cambió nada.
 */
export function setLocale(localeCode) {
  if (!AVAILABLE_LOCALES.includes(localeCode)) return false
  activeLocale.value = localeCode
  storeLocale(localeCode)
  return true
}

// vue-i18n y el atributo `lang` del documento siguen al idioma activo. El
// `lang` no es decorativo: los lectores de pantalla lo usan para elegir la voz
// y el navegador para partir palabras y ofrecer traducción.
watch(activeLocale, (localeCode) => {
  i18n.global.locale.value = localeCode
  document.documentElement.lang = localeCode
}, { immediate: true })
