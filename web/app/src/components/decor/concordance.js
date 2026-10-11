/**
 * Geometría de la lámina de concordancias de Eunomia (`scenes/EunomiaScene.vue`): una regla con
 * una marca por requisito evaluable de cada marco y, encima, un arco por cada correspondencia
 * entre requisitos de marcos distintos. Sin Vue ni red, para probarla con `node`.
 *
 * Los datos son `concordance.json`, una copia del catálogo de la API que ata
 * `API/tests/unit/test_eunomia_scene_data.py`:
 *
 * - `order`: claves de los marcos, de izquierda a derecha sobre la regla.
 * - `frameworks`: `{clave: {label, count}}`; `count` es cuántos requisitos evaluables tiene.
 * - `links`: `[marcoOrigen, índice, marcoDestino, índice, esTotal]`, donde el índice es la
 *   posición del requisito entre los evaluables de su marco y `esTotal` vale 1 si cumplir uno cubre
 *   en lo esencial al otro y 0 si solo lo cubre en parte.
 */

const round = (value) => Math.round(value * 10) / 10

/**
 * Reparte la regla entre los marcos: cada uno ocupa un tramo proporcional a sus requisitos, con
 * el mismo ancho por requisito en todos, y un hueco fijo entre tramos.
 *
 * @param {{order: string[], frameworks: Record<string, {count: number}>}} data - Datos de la lámina.
 * @param {object} [options]
 * @param {number} [options.left=60] - Abscisa donde empieza el primer tramo.
 * @param {number} [options.right=1140] - Abscisa donde acaba el último.
 * @param {number} [options.gap=40] - Hueco entre dos tramos contiguos.
 * @returns {{step: number, segments: Record<string, {x0: number, x1: number, count: number}>}}
 *   `step` es el ancho de la celda de un requisito; `segments` da el tramo de cada marco.
 */
export function layoutRuler({ order, frameworks }, { left = 60, right = 1140, gap = 40 } = {}) {
  const total = order.reduce((sum, key) => sum + frameworks[key].count, 0)
  const step = (right - left - gap * (order.length - 1)) / total
  const segments = {}
  let x = left
  for (const key of order) {
    const { count } = frameworks[key]
    segments[key] = { x0: x, x1: x + count * step, count }
    x += count * step + gap
  }
  return { step, segments }
}

/**
 * Abscisa de la marca de un requisito: el centro de su celda.
 *
 * @param {{step: number, segments: object}} ruler - Lo que devuelve `layoutRuler`.
 * @param {string} framework - Clave del marco.
 * @param {number} index - Posición del requisito entre los evaluables de su marco.
 * @returns {number}
 */
export function tickX(ruler, framework, index) {
  return ruler.segments[framework].x0 + (index + 0.5) * ruler.step
}

/**
 * Arco entre dos marcas de la regla: media elipse aplastada que siempre sube sobre la regla, vaya
 * el arco de izquierda a derecha o al revés, y que se recorre del origen al destino (para que algo
 * pueda viajar por él en ese sentido).
 *
 * @param {number} fromX - Abscisa de la marca de origen.
 * @param {number} toX - Abscisa de la marca de destino.
 * @param {number} baseline - Ordenada de la regla.
 * @param {number} [flatten=0.5] - Altura del arco como fracción de su semianchura.
 * @returns {string} Atributo `d` de un trazo.
 */
export function arcBetween(fromX, toX, baseline, flatten = 0.5) {
  const half = Math.abs(toX - fromX) / 2
  // De izquierda a derecha, el sentido horario pasa por arriba; de derecha a izquierda, el antihorario.
  const sweep = toX > fromX ? 1 : 0
  return `M${round(fromX)} ${baseline} A${round(half)} ${round(half * flatten)} 0 0 ${sweep} ${round(toX)} ${baseline}`
}

/**
 * Los trazos de la regla, en tres: los tramos, las marcas y las marcas mayores (una cada `every`
 * requisitos, empezando por el primero de cada marco, como una regla graduada).
 *
 * @param {{step: number, segments: object}} ruler - Lo que devuelve `layoutRuler`.
 * @param {number} baseline - Ordenada de la regla.
 * @param {object} [options]
 * @param {number} [options.minorHeight=7] - Alto de una marca.
 * @param {number} [options.majorHeight=12] - Alto de una marca mayor.
 * @param {number} [options.every=10] - Cada cuántos requisitos hay una marca mayor.
 * @returns {{rules: string, minor: string, major: string}} Atributos `d`.
 */
export function rulerPaths(ruler, baseline, { minorHeight = 7, majorHeight = 12, every = 10 } = {}) {
  const rules = []
  const minor = []
  const major = []
  for (const { x0, x1, count } of Object.values(ruler.segments)) {
    rules.push(`M${round(x0)} ${baseline}H${round(x1)}`)
    for (let index = 0; index < count; index += 1) {
      const isMajor = index % every === 0
      const x = round(x0 + (index + 0.5) * ruler.step)
      ;(isMajor ? major : minor).push(`M${x} ${baseline}v${-(isMajor ? majorHeight : minorHeight)}`)
    }
  }
  return { rules: rules.join(' '), minor: minor.join(' '), major: major.join(' ') }
}

/**
 * Un arco por correspondencia, con las parciales delante en la lista para que las totales se
 * pinten encima, y cada grupo de izquierda a derecha.
 *
 * @param {{links: Array}} data - Datos de la lámina.
 * @param {{step: number, segments: object}} ruler - Lo que devuelve `layoutRuler`.
 * @param {number} baseline - Ordenada de la regla.
 * @param {number} [flatten=0.5] - Ver `arcBetween`.
 * @returns {Array<{path: string, isFull: boolean, footX: number}>} `footX` es la abscisa del pie
 *   izquierdo del arco, para escalonar su entrada.
 */
export function arcList({ links }, ruler, baseline, flatten = 0.5) {
  return links
    .map(([fromKey, fromIndex, toKey, toIndex, isFull]) => {
      const fromX = tickX(ruler, fromKey, fromIndex)
      const toX = tickX(ruler, toKey, toIndex)
      return { path: arcBetween(fromX, toX, baseline, flatten), isFull: Boolean(isFull), footX: Math.min(fromX, toX) }
    })
    .sort((a, b) => Number(a.isFull) - Number(b.isFull) || a.footX - b.footX)
}

/**
 * Los requisitos que corresponden con uno dado, leyendo los enlaces en los dos sentidos.
 *
 * @param {{order: string[], links: Array}} data - Datos de la lámina.
 * @param {{framework: string, index: number}} source - Requisito de partida.
 * @returns {Array<{framework: string, index: number}>} Uno por cada otro marco al que llega (el
 *   primero que dice el catálogo), en el orden de la regla; vacío si no corresponde con nada.
 */
export function fanOf({ order, links }, source) {
  const reached = new Map()
  for (const [fromKey, fromIndex, toKey, toIndex] of links) {
    let other = null
    if (fromKey === source.framework && fromIndex === source.index) other = { framework: toKey, index: toIndex }
    else if (toKey === source.framework && toIndex === source.index) other = { framework: fromKey, index: fromIndex }
    if (other && !reached.has(other.framework)) reached.set(other.framework, other)
  }
  return order.filter((key) => reached.has(key)).map((key) => reached.get(key))
}

/**
 * Requisitos de un marco desde los que una evidencia llega a todos los demás marcos, repartidos a
 * lo largo del marco para que los abanicos no salgan juntos.
 *
 * @param {{order: string[], frameworks: object, links: Array}} data - Datos de la lámina.
 * @param {string} framework - Marco del que parten (el que más cruces tiene, NIS2).
 * @param {number} count - Cuántos se quieren como máximo.
 * @returns {Array<{framework: string, index: number}>}
 */
export function fanSources(data, framework, count) {
  const needed = data.order.length - 1
  const candidates = Array.from({ length: data.frameworks[framework].count }, (_, index) => index)
    .filter((index) => fanOf(data, { framework, index }).length === needed)
  const taken = Math.min(count, candidates.length)
  return Array.from({ length: taken }, (_, position) => ({
    framework,
    index: candidates[Math.floor((position * candidates.length) / taken)],
  }))
}

/**
 * Un rombo, la misma forma que abre el rótulo de una sección (`SectionInscription`).
 *
 * @param {number} x - Abscisa del centro.
 * @param {number} y - Ordenada del centro.
 * @param {number} radius - Distancia del centro a cada vértice.
 * @returns {string} Atributo `d` de un trazo cerrado.
 */
export function diamondPath(x, y, radius) {
  const cx = round(x)
  const cy = round(y)
  return `M${cx} ${cy - radius}L${cx + radius} ${cy}L${cx} ${cy + radius}L${cx - radius} ${cy}Z`
}
