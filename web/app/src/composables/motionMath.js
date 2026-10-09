/**
 * Matemática pura de las animaciones, sin Vue ni DOM, para poder probarla con
 * `node` a secas (`test/freeTools.motion.test.mjs`).
 */

/**
 * Lleva un número al rango [0, 1].
 *
 * @param {number} value - Cualquier número.
 * @returns {number} 0 si es menor que 0 o no es un número; 1 si es mayor que 1.
 */
export function clamp01(value) {
  if (!(value > 0)) return 0
  return value > 1 ? 1 : value
}

/**
 * Curva de frenado suave: rápida al principio, lenta al llegar.
 *
 * @param {number} progress - Avance de la animación, de 0 a 1.
 * @returns {number} Avance con la curva aplicada, de 0 a 1.
 */
export function easeOutCubic(progress) {
  return 1 - (1 - clamp01(progress)) ** 3
}

/**
 * Interpolación lineal entre dos números.
 *
 * @param {number} from - Valor de partida.
 * @param {number} to - Valor de llegada.
 * @param {number} fraction - Fracción del camino, de 0 a 1.
 * @returns {number} El valor intermedio.
 */
export function lerp(from, to, fraction) {
  return from + (to - from) * fraction
}

/**
 * Redondea a un número de decimales.
 *
 * @param {number} value - Número a redondear.
 * @param {number} decimals - Decimales que se conservan (0 o más).
 * @returns {number} El número redondeado.
 */
export function roundTo(value, decimals) {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

/**
 * Valor que enseña un contador animado en un instante.
 *
 * @param {number} from - Valor del que parte.
 * @param {number} to - Valor al que llega.
 * @param {number} progress - Avance de la animación, de 0 a 1.
 * @param {number} [decimals=0] - Decimales que se enseñan.
 * @returns {number} El valor intermedio con la curva de frenado; vale exactamente `to` cuando `progress` es 1.
 */
export function countUpValue(from, to, progress, decimals = 0) {
  if (progress >= 1) return to
  return roundTo(lerp(from, to, easeOutCubic(progress)), decimals)
}

/** Caracteres entre los que baraja `scrambleFrame`: sin los que se confunden (0, O, 1, l, I). */
export const SCRAMBLE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%&*?+=-_'

/**
 * Un fotograma de la animación en que un texto se «descifra» de izquierda a derecha.
 *
 * Cada carácter se queda en su valor final a partir de un instante propio: el primero
 * enseguida y el último justo al terminar. Antes de eso enseña un carácter al azar.
 * Los espacios no se barajan.
 *
 * @param {string} target - El texto final.
 * @param {number} progress - Avance de la animación, de 0 a 1. Con 0 no hay ningún carácter fijado y con 1 están todos.
 * @param {() => number} [random] - Fuente de números en [0, 1). Por defecto `Math.random`; se inyecta en los tests.
 * @param {string} [alphabet] - Caracteres entre los que se baraja. Por defecto `SCRAMBLE_ALPHABET`.
 * @returns {string} El texto de ese instante, con la misma longitud que `target`.
 */
export function scrambleFrame(target, progress, random = Math.random, alphabet = SCRAMBLE_ALPHABET) {
  const characters = [...target]
  const settledFrom = 0.2
  return characters
    .map((character, index) => {
      if (character === ' ') return character
      const settleAt = settledFrom + (1 - settledFrom) * ((index + 1) / characters.length)
      return progress >= settleAt ? character : alphabet[Math.floor(random() * alphabet.length)]
    })
    .join('')
}

/**
 * Retraso de entrada de un elemento dentro de una serie que aparece escalonada.
 *
 * @param {number} index - Posición del elemento en la serie (0 es el primero).
 * @param {number} [step=80] - Milisegundos entre un elemento y el siguiente.
 * @param {number} [max=640] - Retraso máximo en milisegundos, para que una serie larga no tarde en acabar.
 * @returns {number} Milisegundos de retraso, nunca negativos.
 */
export function staggerDelay(index, step = 80, max = 640) {
  return Math.max(0, Math.min(index * step, max))
}

/**
 * Generador de números pseudoaleatorios con semilla (mulberry32).
 *
 * Sirve para colocar adornos «al azar» de forma que la escena sea siempre la misma
 * en cada carga y en cada prueba.
 *
 * @param {number} seed - Semilla entera.
 * @returns {() => number} Función que en cada llamada devuelve el siguiente número en [0, 1).
 */
export function seededRandom(seed) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state)
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Cuánto mide un píxel físico de la pantalla en las unidades de un dibujo escalado.
 *
 * @param {number} scale - Píxeles CSS por unidad del dibujo (la escala a la que se pinta).
 * @param {number} [pixelRatio=1] - Píxeles físicos por píxel CSS (`devicePixelRatio`):
 *   `1` en una pantalla normal, `2` o `3` en una de alta densidad.
 * @returns {number} Unidades del dibujo por píxel físico; `0` si la escala no es
 *   positiva (el dibujo aún no tiene tamaño).
 */
export function devicePixelInUnits(scale, pixelRatio = 1) {
  if (!(scale > 0)) return 0
  return Math.round((1 / (scale * Math.max(pixelRatio, 1))) * 1000) / 1000
}

