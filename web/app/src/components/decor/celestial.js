/**
 * Astronomía sin Vue para las láminas de cielo de las escenas (`scenes/`): proyecta
 * estrellas reales sobre el plano como lo haría un atlas celeste, y traza su retícula
 * y la eclíptica. Se prueba con `node` a secas.
 *
 * Las coordenadas van en grados: ascensión recta (`ra`, de 0 a 360) y declinación
 * (`dec`, de -90 a 90). El plano es el de SVG (la y crece hacia abajo) y, como en
 * cualquier carta del cielo, el este queda a la izquierda: se mira hacia arriba.
 */

const RADIANS = Math.PI / 180
/** Inclinación del eje de la Tierra respecto a su órbita (época J2000), en grados. */
export const OBLIQUITY = 23.4393

/**
 * Crea la proyección estereográfica de una lámina: conserva las formas de las
 * constelaciones, que es por lo que la usan los atlas.
 *
 * @param {object} options - Opciones.
 * @param {number} options.ra - Ascensión recta del centro de la lámina, en grados.
 * @param {number} options.dec - Declinación del centro de la lámina, en grados.
 * @param {number} options.scale - Píxeles por radián en el centro.
 * @param {number} options.x - Abscisa en la que cae el centro.
 * @param {number} options.y - Ordenada en la que cae el centro.
 * @returns {(ra: number, dec: number) => ({x: number, y: number} | null)} Función que
 *   lleva una posición del cielo al plano, redondeada a dos decimales. Devuelve `null`
 *   para un punto del hemisferio opuesto al centro, que la proyección no puede pintar.
 */
export function stereographic({ ra: centerRa, dec: centerDec, scale, x: originX, y: originY }) {
  const sinCenter = Math.sin(centerDec * RADIANS)
  const cosCenter = Math.cos(centerDec * RADIANS)
  return (ra, dec) => {
    const deltaRa = (ra - centerRa) * RADIANS
    const sinDec = Math.sin(dec * RADIANS)
    const cosDec = Math.cos(dec * RADIANS)
    const cosAngle = sinCenter * sinDec + cosCenter * cosDec * Math.cos(deltaRa)
    if (cosAngle <= -0.2) return null
    const factor = (2 / (1 + cosAngle)) * scale
    const east = factor * cosDec * Math.sin(deltaRa)
    const north = factor * (cosCenter * sinDec - sinCenter * cosDec * Math.cos(deltaRa))
    return {
      x: Math.round((originX - east) * 100) / 100,
      y: Math.round((originY - north) * 100) / 100,
    }
  }
}

/**
 * Une puntos proyectados en un trazo SVG, partiéndolo donde la proyección no llega.
 *
 * @param {Array<{x: number, y: number} | null>} points - Puntos en orden.
 * @returns {string} Atributo `d`; vacío si no hay al menos dos puntos seguidos.
 */
function joinPoints(points) {
  let path = ''
  let isDrawing = false
  for (const point of points) {
    if (!point) { isDrawing = false; continue }
    path += `${isDrawing ? 'L' : 'M'}${point.x} ${point.y} `
    isDrawing = true
  }
  return path.trim()
}

/**
 * Retícula de la lámina: círculos de declinación y meridianos de ascensión recta.
 *
 * @param {(ra: number, dec: number) => ({x: number, y: number} | null)} project - La proyección.
 * @param {object} options - Opciones.
 * @param {[number, number]} options.raRange - Ascensión recta mínima y máxima que cubre, en grados.
 * @param {[number, number]} options.decRange - Declinación mínima y máxima que cubre, en grados.
 * @param {number} [options.raStep=7.5] - Separación entre meridianos, en grados (7,5° es media hora).
 * @param {number} [options.decStep=5] - Separación entre círculos de declinación, en grados.
 * @param {number} [options.majorRaStep=15] - Cada cuántos grados un meridiano es mayor (15° es una hora).
 * @param {number} [options.majorDecStep=10] - Cada cuántos grados un círculo de declinación es mayor.
 * @returns {Array<{path: string, kind: 'ra'|'dec', value: number, isMajor: boolean}>}
 *   Una línea por meridiano y por círculo, con el valor que marca y si es mayor.
 */
export function graticule(project, { raRange, decRange, raStep = 7.5, decStep = 5, majorRaStep = 15, majorDecStep = 10 }) {
  const [raMin, raMax] = raRange
  const [decMin, decMax] = decRange
  const lines = []
  for (let ra = Math.ceil(raMin / raStep) * raStep; ra <= raMax; ra += raStep) {
    const points = []
    for (let dec = decMin; dec <= decMax; dec += 1) points.push(project(ra, dec))
    lines.push({ path: joinPoints(points), kind: 'ra', value: ra, isMajor: ra % majorRaStep === 0 })
  }
  for (let dec = Math.ceil(decMin / decStep) * decStep; dec <= decMax; dec += decStep) {
    const points = []
    for (let ra = raMin; ra <= raMax; ra += 1) points.push(project(ra, dec))
    lines.push({ path: joinPoints(points), kind: 'dec', value: dec, isMajor: dec % majorDecStep === 0 })
  }
  return lines.filter((line) => line.path.includes('L'))
}

/**
 * Posición en el cielo de un punto de la eclíptica, el camino aparente del Sol, por
 * el que pasan las constelaciones del zodiaco.
 *
 * @param {number} longitude - Longitud eclíptica, en grados.
 * @returns {{ra: number, dec: number}} Ascensión recta (en [0, 360)) y declinación, en grados.
 */
export function eclipticPoint(longitude) {
  const lambda = longitude * RADIANS
  const epsilon = OBLIQUITY * RADIANS
  const ra = Math.atan2(Math.sin(lambda) * Math.cos(epsilon), Math.cos(lambda)) / RADIANS
  const dec = Math.asin(Math.sin(epsilon) * Math.sin(lambda)) / RADIANS
  return { ra: (ra + 360) % 360, dec }
}

/**
 * Trazo de la eclíptica sobre la lámina.
 *
 * @param {(ra: number, dec: number) => ({x: number, y: number} | null)} project - La proyección.
 * @param {[number, number]} longitudeRange - Longitud eclíptica inicial y final, en grados.
 * @returns {string} Atributo `d`.
 */
export function eclipticPath(project, [from, to]) {
  const points = []
  for (let longitude = from; longitude <= to; longitude += 1) {
    const { ra, dec } = eclipticPoint(longitude)
    points.push(project(ra, dec))
  }
  return joinPoints(points)
}

/**
 * Radio con que un atlas pinta una estrella según su brillo: cuanto menor la
 * magnitud, más brillante y más grande.
 *
 * @param {number} magnitude - Magnitud aparente (1 es muy brillante; 6, el límite del ojo).
 * @returns {number} Radio en unidades del dibujo, nunca menor que `0.7`.
 */
export function starRadius(magnitude) {
  return Math.max(0.7, Math.round((1 + (5 - magnitude) * 0.95) * 100) / 100)
}

/**
 * Segmento entre dos estrellas que se detiene antes de tocarlas, como en los atlas:
 * el trazo de la figura no tapa la estrella.
 *
 * @param {{x: number, y: number}} from - Primera estrella, ya proyectada.
 * @param {{x: number, y: number}} to - Segunda estrella, ya proyectada.
 * @param {number} fromGap - Hueco junto a la primera.
 * @param {number} toGap - Hueco junto a la segunda.
 * @returns {string} Atributo `d`; vacío si las estrellas están más juntas que los dos huecos.
 */
export function gappedSegment(from, to, fromGap, toGap) {
  const length = Math.hypot(to.x - from.x, to.y - from.y)
  if (length <= fromGap + toGap) return ''
  const unitX = (to.x - from.x) / length
  const unitY = (to.y - from.y) / length
  const round = (value) => Math.round(value * 100) / 100
  return `M${round(from.x + unitX * fromGap)} ${round(from.y + unitY * fromGap)} L${round(to.x - unitX * toGap)} ${round(to.y - unitY * toGap)}`
}

/**
 * Proyecta las estrellas de un catálogo y les da el tamaño de su brillo.
 *
 * @param {(ra: number, dec: number) => ({x: number, y: number} | null)} project - La proyección.
 * @param {Array<{letter: string, ra: number, dec: number, magnitude: number}>} catalog - Estrellas,
 *   cada una con su letra de Bayer, su posición en grados y su magnitud; pueden traer
 *   más campos (nombre propio, si es variable), que se conservan.
 * @returns {Array<object>} Las estrellas que caen en el plano, con `x`, `y` y `radius`
 *   añadidos. Las del hemisferio opuesto se descartan.
 */
export function projectCatalog(project, catalog) {
  return catalog.flatMap((star) => {
    const point = project(star.ra, star.dec)
    return point ? [{ ...star, ...point, radius: starRadius(star.magnitude) }] : []
  })
}

/**
 * Trazos de la figura de una constelación, de estrella a estrella por su letra.
 *
 * @param {Array<{letter: string, x: number, y: number, radius: number}>} stars - Estrellas ya proyectadas.
 * @param {Array<[string, string]>} pairs - Parejas de letras que se unen.
 * @param {number} [gap=5] - Hueco que se deja entre el borde de cada estrella y el trazo.
 * @returns {string[]} Un atributo `d` por pareja que se puede dibujar; las parejas con
 *   una estrella fuera del plano o demasiado juntas se omiten.
 */
export function constellationEdges(stars, pairs, gap = 5) {
  const byLetter = Object.fromEntries(stars.map((star) => [star.letter, star]))
  return pairs
    .filter(([from, to]) => byLetter[from] && byLetter[to])
    .map(([from, to]) => gappedSegment(byLetter[from], byLetter[to], byLetter[from].radius + gap, byLetter[to].radius + gap))
    .filter(Boolean)
}

/**
 * Escribe una declinación como en los atlas: con su signo siempre y el signo menos tipográfico.
 *
 * @param {number} declination - Declinación en grados.
 * @returns {string} Por ejemplo `+40°`, `0°` o `−20°`.
 */
export function formatDeclination(declination) {
  if (declination === 0) return '0°'
  return `${declination > 0 ? '+' : '−'}${Math.abs(declination)}°`
}
