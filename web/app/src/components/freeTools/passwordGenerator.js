/**
 * Lógica sin Vue del generador de contraseñas gratuito
 * (`views/tools/acheron/PasswordGeneratorView.vue`), para poder probarla con
 * `node` a secas. El sorteo en sí lo hace `generatePassword` de
 * `@projectellysia/acheron-core-js`, el mismo que usa la bóveda.
 */

/** Longitud mínima, máxima y inicial de la contraseña generada. */
export const PASSWORD_LENGTH = Object.freeze({ min: 8, max: 64, initial: 20 })

/** Tipos de carácter que se pueden activar, en el orden en que se muestran. */
export const CHARACTER_CLASSES = Object.freeze(['uppercase', 'lowercase', 'digits', 'symbols'])

/**
 * Lleva una longitud cualquiera al rango permitido.
 *
 * @param {unknown} value - Lo que haya escrito el usuario: número, texto o vacío.
 * @returns {number} Un entero entre `PASSWORD_LENGTH.min` y `PASSWORD_LENGTH.max`;
 *   `PASSWORD_LENGTH.initial` si `value` no es un número.
 */
export function clampPasswordLength(value) {
  const length = Math.round(Number(value))
  if (!Number.isFinite(length)) return PASSWORD_LENGTH.initial
  return Math.min(PASSWORD_LENGTH.max, Math.max(PASSWORD_LENGTH.min, length))
}

/**
 * Indica si un tipo de carácter es el único que queda activo.
 *
 * La interfaz bloquea esa casilla: sin ningún tipo no hay alfabeto del que
 * sacar la contraseña.
 *
 * @param {Record<string, boolean>} state - Estado de las casillas, con una
 *   propiedad booleana por cada elemento de `CHARACTER_CLASSES`.
 * @param {string} characterClass - Uno de `CHARACTER_CLASSES`.
 * @returns {boolean} `true` si `characterClass` está activo y ningún otro lo está.
 */
export function isLastActiveClass(state, characterClass) {
  return state[characterClass] === true && CHARACTER_CLASSES.every((other) => other === characterClass || !state[other])
}

/**
 * Convierte el estado de la pantalla en las opciones de `generatePassword`.
 *
 * @param {object} state - Estado de la pantalla.
 * @param {number|string} state.length - Longitud pedida; se lleva al rango permitido.
 * @param {boolean} state.uppercase - Incluir mayúsculas.
 * @param {boolean} state.lowercase - Incluir minúsculas.
 * @param {boolean} state.digits - Incluir números.
 * @param {boolean} state.symbols - Incluir símbolos.
 * @param {boolean} state.excludeAmbiguous - Dejar fuera `0`, `O`, `1`, `l` e `I`.
 * @returns {object} Opciones listas para `generatePassword`. Si no hay ningún tipo
 *   activo, activa las minúsculas para que siempre haya alfabeto.
 */
export function toGeneratorOptions(state) {
  const hasAnyClass = CHARACTER_CLASSES.some((characterClass) => state[characterClass])
  return {
    length: clampPasswordLength(state.length),
    uppercase: Boolean(state.uppercase),
    lowercase: hasAnyClass ? Boolean(state.lowercase) : true,
    digits: Boolean(state.digits),
    symbols: Boolean(state.symbols),
    excludeAmbiguous: Boolean(state.excludeAmbiguous),
  }
}

/**
 * Clasifica un carácter para pintarlo: las cifras y los símbolos se distinguen
 * a simple vista de las letras, que es justo lo que confunde al teclear una
 * contraseña a mano.
 *
 * @param {string} character - Un carácter.
 * @returns {'letter'|'digit'|'symbol'} Su clase.
 */
export function characterKind(character) {
  if (/[A-Za-z]/.test(character)) return 'letter'
  if (/\d/.test(character)) return 'digit'
  return 'symbol'
}

/**
 * Clave del diccionario con el rótulo de un nivel de solidez.
 *
 * @param {number} score - Puntuación de `scorePassword`, de 0 a 4.
 * @returns {string} `freeTools.items.passwordGenerator.strength.<score>`. Una
 *   puntuación fuera de rango se lleva al extremo más cercano.
 */
export function strengthLabelKey(score) {
  const level = Math.min(4, Math.max(0, Math.round(Number(score)) || 0))
  return `freeTools.items.passwordGenerator.strength.${level}`
}
