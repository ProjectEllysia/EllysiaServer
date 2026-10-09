/**
 * Geometría sin Vue de los grabados de la decoración (`components/decor/`): el sello
 * de cada módulo y la rosa de los vientos. Se prueba con `node` a secas. Los ángulos
 * van en grados y se miden en sentido horario desde arriba, como una esfera de reloj.
 */

/**
 * Punto de una circunferencia.
 *
 * @param {number} centerX - Abscisa del centro.
 * @param {number} centerY - Ordenada del centro (crece hacia abajo, como en SVG).
 * @param {number} radius - Radio.
 * @param {number} angle - Ángulo en grados: 0 es arriba y crece en sentido horario.
 * @returns {{x: number, y: number}} El punto, redondeado a dos decimales.
 */
export function polarPoint(centerX, centerY, radius, angle) {
  const radians = (angle * Math.PI) / 180
  return {
    x: Math.round((centerX + radius * Math.sin(radians)) * 100) / 100,
    y: Math.round((centerY - radius * Math.cos(radians)) * 100) / 100,
  }
}

/**
 * Una curva de guilloché: el trenzado fino de los billetes y las monedas, que se
 * graba con un torno y no a mano. Es un círculo cuyo radio ondula a lo largo de la
 * vuelta; varias curvas iguales con la fase desplazada se cruzan y tejen la red.
 *
 * @param {object} options - Opciones.
 * @param {number} options.centerX - Abscisa del centro.
 * @param {number} options.centerY - Ordenada del centro.
 * @param {number} options.radius - Radio medio de la curva.
 * @param {number} options.amplitude - Cuánto se aleja el radio del medio, hacia dentro y hacia fuera.
 * @param {number} options.lobes - Ondas que da en una vuelta; entero para que la curva se cierre.
 * @param {number} [options.phase=0] - Desfase de la onda, en radianes.
 * @param {number} [options.samplesPerLobe=14] - Puntos por onda; más puntos, curva más suave y trazo más pesado.
 * @returns {string} Atributo `d` de un trazo cerrado, con una décima de precisión.
 */
export function guillochePath({ centerX, centerY, radius, amplitude, lobes, phase = 0, samplesPerLobe = 14 }) {
  const samples = lobes * samplesPerLobe
  const round = (value) => Math.round(value * 10) / 10
  let path = ''
  for (let step = 0; step < samples; step += 1) {
    const angle = (step / samples) * Math.PI * 2
    const distance = radius + amplitude * Math.sin(lobes * angle + phase)
    path += `${step === 0 ? 'M' : 'L'}${round(centerX + distance * Math.sin(angle))} ${round(centerY - distance * Math.cos(angle))} `
  }
  return `${path}Z`
}
