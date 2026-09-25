/**
 * Idioma activo de la interfaz.
 *
 * Vive aparte de `index.js` para que lo puedan importar los módulos puros que
 * se prueban con `node` a secas (sin Vite): aquí no hay `import.meta.glob` ni
 * nada que dependa del empaquetador, solo un `ref` de Vue.
 *
 * El código de idioma es a la vez el nombre del fichero de `locales/` (`es`
 * para `locales/es.json`) y la etiqueta que se le pasa a `Intl` para formatear
 * fechas y números, así que un idioma nuevo no necesita declarar nada más.
 */
import { ref } from 'vue'

/**
 * Idioma con el que arranca la interfaz y al que se recurre cuando a otro le
 * falta un texto. Es el único idioma completo: todos los textos existen en él.
 */
export const DEFAULT_LOCALE = 'es'

/**
 * Código del idioma en el que se está mostrando la interfaz ahora mismo.
 *
 * Es reactivo: un `computed` o una plantilla que lo lean (directamente o a
 * través de las funciones de `format.js`) se vuelven a pintar al cambiarlo.
 * Se cambia con `setLocale` de `index.js`, que comprueba que el idioma exista;
 * no se asigna a mano.
 *
 * @type {import('vue').Ref<string>}
 */
export const activeLocale = ref(DEFAULT_LOCALE)
