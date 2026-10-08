/**
 * Lógica sin Vue del mini quiz de phishing gratuito
 * (`views/tools/aegis/PhishingQuizView.vue`), para poder probarla con `node` a
 * secas. Los correos son ficticios y fijos: no hay servidor ni cuenta, y ninguna
 * marca real. Los textos van en el diccionario (`freeTools.items.phishingQuiz.cases`);
 * aquí solo lo que no se traduce: las direcciones, los enlaces y la solución.
 */

/**
 * Los correos del quiz.
 *
 * - `id` — nombra sus textos en `cases.<id>` (`name`, `subject`, `body`, `linkText`
 *   si lleva enlace, `explanation` y `clues.1` … `clues.<clueCount>`).
 * - `isPhishing` — la solución.
 * - `address` — dirección real del remitente.
 * - `linkUrl` — destino real del enlace, que solo se enseña tras responder; `null`
 *   si el correo no lleva enlace.
 * - `clueCount` — cuántas pistas explican la solución.
 */
export const QUIZ_CASES = Object.freeze([
  Object.freeze({ id: 'parcel', isPhishing: true, address: 'avisos@paqueteria-expres-envios.info', linkUrl: 'http://paqueteria-expres.entregas-seguras.top/pago', clueCount: 4 }),
  Object.freeze({ id: 'bank', isPhishing: true, address: 'seguridad@banco-ejemplo-seguridad.com', linkUrl: 'https://banco-ejemplo.acceso-clientes.net/login', clueCount: 4 }),
  Object.freeze({ id: 'invoice', isPhishing: false, address: 'facturas@nubesur.es', linkUrl: 'https://area.nubesur.es/facturas', clueCount: 3 }),
  Object.freeze({ id: 'director', isPhishing: true, address: 'emartin.direccion@correo-gratis.com', linkUrl: null, clueCount: 4 }),
  Object.freeze({ id: 'password', isPhishing: false, address: 'soporte@tuempresa.es', linkUrl: null, clueCount: 3 }),
  Object.freeze({ id: 'prize', isPhishing: true, address: 'ganador@mercadillo-premios.xyz', linkUrl: 'http://reclama-premio.mercadillo-ofertas.xyz', clueCount: 4 }),
])

/** Tramos del resultado final, con su texto en `freeTools.items.phishingQuiz.bands`. */
export const RESULT_BANDS = Object.freeze(['perfect', 'good', 'weak'])

/**
 * Baraja una lista sin modificarla (Fisher-Yates).
 *
 * @param {Array} items - La lista.
 * @param {() => number} [random] - Fuente de números en [0, 1). Por defecto `Math.random`;
 *   se inyecta en los tests.
 * @returns {Array} Una copia con los mismos elementos en otro orden.
 */
export function shuffled(items, random = Math.random) {
  const copy = [...items]
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1))
    ;[copy[index], copy[other]] = [copy[other], copy[index]]
  }
  return copy
}

/**
 * Corrige una respuesta.
 *
 * @param {{isPhishing: boolean}} quizCase - El correo.
 * @param {'phishing'|'legit'} answer - Lo que ha contestado el usuario.
 * @returns {boolean} `true` si acierta.
 */
export function isCorrect(quizCase, answer) {
  return (answer === 'phishing') === quizCase.isPhishing
}

/**
 * Tramo del resultado final.
 *
 * @param {number} correct - Aciertos.
 * @param {number} total - Correos del quiz (mayor que 0).
 * @returns {'perfect'|'good'|'weak'} `perfect` si no hay fallos; `good` si se acierta al
 *   menos dos de cada tres; `weak` en otro caso.
 */
export function resultBand(correct, total) {
  if (correct >= total) return 'perfect'
  return correct / total >= 2 / 3 ? 'good' : 'weak'
}
