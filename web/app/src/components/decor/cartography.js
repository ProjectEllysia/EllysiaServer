/**
 * Cartografía sin Vue para la escena de Acheron (`scenes/AcheronScene.vue`): costas,
 * ríos, lagos y relieve dibujados como en un mapa grabado antiguo. Se prueba con
 * `node` a secas. Los puntos son `{x, y}` en el plano de SVG (la y crece hacia abajo).
 */

const round = (value) => Math.round(value * 10) / 10

/**
 * Trazo suave que pasa por todos los puntos (spline de Catmull-Rom convertida a curvas
 * de Bézier), para que una costa o un río no se vean como una línea quebrada.
 *
 * @param {Array<{x: number, y: number}>} points - Puntos por los que pasa, en orden; al menos dos.
 * @param {boolean} [isClosed=false] - Si el trazo vuelve al primer punto (un lago) o queda abierto (un río).
 * @returns {string} Atributo `d`.
 */
export function smoothPath(points, isClosed = false) {
  const count = points.length
  const at = (index) => (isClosed ? points[(index + count) % count] : points[Math.max(0, Math.min(count - 1, index))])
  let path = `M${round(points[0].x)} ${round(points[0].y)}`
  const segments = isClosed ? count : count - 1
  for (let index = 0; index < segments; index += 1) {
    const [previous, start, end, next] = [at(index - 1), at(index), at(index + 1), at(index + 2)]
    const first = { x: start.x + (end.x - previous.x) / 6, y: start.y + (end.y - previous.y) / 6 }
    const second = { x: end.x - (next.x - start.x) / 6, y: end.y - (next.y - start.y) / 6 }
    path += ` C${round(first.x)} ${round(first.y)} ${round(second.x)} ${round(second.y)} ${round(end.x)} ${round(end.y)}`
  }
  return isClosed ? `${path} Z` : path
}

/**
 * Puntos de un cauce que serpentea entre dos extremos: se aleja de la recta a un lado
 * y a otro, con una segunda onda más corta y de fase al azar para que no parezca una
 * onda de manual. Las dos ondas son suaves, así que el cauce no sale dentado.
 *
 * @param {{x: number, y: number}} start - Nacimiento.
 * @param {{x: number, y: number}} end - Desembocadura.
 * @param {object} options - Opciones.
 * @param {number} options.amplitude - Cuánto se aparta de la recta, como máximo.
 * @param {number} options.bends - Cuántas curvas da.
 * @param {() => number} options.random - Generador en [0, 1) con semilla, para que el río sea siempre el mismo;
 *   se usa una sola vez, para la fase de la segunda onda.
 * @param {number} [options.samples=24] - Cuántos puntos devuelve, extremos incluidos.
 * @returns {Array<{x: number, y: number}>} Los puntos, del nacimiento a la desembocadura.
 *   Empiezan y acaban exactamente en los extremos.
 */
export function meanderPoints(start, end, { amplitude, bends, random, samples = 24 }) {
  const length = Math.hypot(end.x - start.x, end.y - start.y)
  const normal = { x: -(end.y - start.y) / length, y: (end.x - start.x) / length }
  const phase = random() * Math.PI * 2
  return Array.from({ length: samples }, (_, index) => {
    const progress = index / (samples - 1)
    const envelope = Math.sin(Math.PI * progress)
    const wave = Math.sin(progress * bends * Math.PI) + 0.35 * Math.sin(progress * bends * 2.3 * Math.PI + phase)
    const offset = amplitude * wave * envelope
    return { x: start.x + (end.x - start.x) * progress + normal.x * offset, y: start.y + (end.y - start.y) * progress + normal.y * offset }
  })
}

/**
 * Copia de una línea desplazada en perpendicular: con ella se dibujan las líneas de
 * agua paralelas a la costa, la marca de los mapas grabados.
 *
 * @param {Array<{x: number, y: number}>} points - La línea original, en orden.
 * @param {number} distance - Desplazamiento; positivo hacia la izquierda de la dirección de avance.
 * @returns {Array<{x: number, y: number}>} Tantos puntos como la original.
 */
export function offsetPoints(points, distance) {
  return points.map((point, index) => {
    const previous = points[Math.max(0, index - 1)]
    const next = points[Math.min(points.length - 1, index + 1)]
    const length = Math.hypot(next.x - previous.x, next.y - previous.y) || 1
    return { x: point.x + ((next.y - previous.y) / length) * distance, y: point.y - ((next.x - previous.x) / length) * distance }
  })
}

/**
 * Contorno de un lago: un círculo cuyo radio varía con unos pocos armónicos.
 *
 * @param {object} options - Opciones.
 * @param {number} options.centerX - Abscisa del centro.
 * @param {number} options.centerY - Ordenada del centro.
 * @param {number} options.radius - Radio medio.
 * @param {number} [options.stretch=1] - Cuánto se alarga en horizontal.
 * @param {Array<[number, number, number]>} [options.harmonics=[]] - Cada armónico es
 *   `[ondas por vuelta, amplitud, fase]`.
 * @param {number} [options.inset=0] - Cuánto se encoge el contorno hacia dentro; para
 *   las líneas de agua interiores.
 * @param {number} [options.samples=36] - Puntos del contorno.
 * @returns {Array<{x: number, y: number}>} Los puntos, en sentido horario.
 */
export function lakePoints({ centerX, centerY, radius, stretch = 1, harmonics = [], inset = 0, samples = 36 }) {
  return Array.from({ length: samples }, (_, index) => {
    const angle = (index / samples) * Math.PI * 2
    const distance = harmonics.reduce((total, [waves, amplitude, phase]) => total + amplitude * Math.sin(waves * angle + phase), radius) - inset
    return { x: centerX + distance * Math.cos(angle) * stretch, y: centerY + distance * Math.sin(angle) }
  })
}

/**
 * Sombreado de relieve de los mapas antiguos: trazos cortos que bajan desde la cresta
 * de una sierra, más largos donde la pendiente es mayor.
 *
 * @param {Array<{x: number, y: number}>} ridge - Puntos de la cresta, en orden.
 * @param {object} options - Opciones.
 * @param {number} options.spacing - Distancia entre trazos a lo largo de la cresta.
 * @param {number} options.length - Largo máximo de un trazo.
 * @param {() => number} options.random - Generador en [0, 1) con semilla.
 * @param {number} [options.backSlope=0.45] - Largo de los trazos de la vertiente iluminada
 *   respecto a los de la umbría; `0` deja solo la umbría.
 * @returns {string[]} Un atributo `d` por trazo: los de la umbría, a la derecha de la
 *   dirección de avance de la cresta, y los de la otra vertiente, más cortos. Todos se
 *   acortan hacia los extremos de la sierra.
 */
export function hachures(ridge, { spacing, length, random, backSlope = 0.45 }) {
  const strokes = []
  for (let index = 0; index < ridge.length - 1; index += 1) {
    const from = ridge[index]
    const to = ridge[index + 1]
    const segment = Math.hypot(to.x - from.x, to.y - from.y)
    const unit = { x: (to.x - from.x) / segment, y: (to.y - from.y) / segment }
    const normal = { x: -unit.y, y: unit.x }
    for (let travelled = 0; travelled < segment; travelled += spacing) {
      const progress = (index + travelled / segment) / (ridge.length - 1)
      const size = length * Math.sin(Math.PI * progress) * (0.55 + random() * 0.45)
      const base = { x: from.x + unit.x * travelled, y: from.y + unit.y * travelled }
      strokes.push(`M${round(base.x)} ${round(base.y)} L${round(base.x + normal.x * size)} ${round(base.y + normal.y * size)}`)
      if (backSlope > 0) {
        const back = size * backSlope
        strokes.push(`M${round(base.x)} ${round(base.y)} L${round(base.x - normal.x * back)} ${round(base.y - normal.y * back)}`)
      }
    }
  }
  return strokes
}
