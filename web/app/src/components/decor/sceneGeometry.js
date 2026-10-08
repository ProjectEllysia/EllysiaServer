/**
 * Geometría sin Vue de las escenas mitológicas de cada módulo
 * (`components/decor/scenes/`), para poder probarla con `node` a secas. Los ángulos
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
 * Hojas repartidas a lo largo de un arco, como las de una corona de laurel.
 *
 * @param {object} options - Opciones.
 * @param {number} options.centerX - Abscisa del centro del arco.
 * @param {number} options.centerY - Ordenada del centro del arco.
 * @param {number} options.radius - Radio del arco por el que corre el tallo.
 * @param {number} options.from - Ángulo en que empieza el arco, en grados.
 * @param {number} options.to - Ángulo en que termina el arco, en grados (mayor que `from`).
 * @param {number} options.pairs - Cuántos pares de hojas lleva (uno a cada lado del tallo); al menos 2.
 * @param {number} [options.length=26] - Largo de cada hoja.
 * @returns {Array<{x: number, y: number, rotation: number, side: 'in'|'out', index: number}>}
 *   Dos hojas por par. `x` e `y` son el centro de la hoja, que cae a medio largo del
 *   tallo hacia fuera (`out`) o hacia dentro (`in`) del círculo; `rotation` es el giro
 *   en grados de una hoja dibujada en horizontal, para que siga el tallo y se abra
 *   unos 38° hacia su lado; `index` es el número de par, para escalonar su balanceo.
 */
export function leavesAlongArc({ centerX, centerY, radius, from, to, pairs, length = 26 }) {
  const leaves = []
  for (let index = 0; index < pairs; index += 1) {
    const angle = from + ((to - from) * index) / (pairs - 1)
    for (const side of ['in', 'out']) {
      const offset = side === 'out' ? length * 0.5 : -length * 0.5
      const center = polarPoint(centerX, centerY, radius + offset, angle + 3)
      leaves.push({ ...center, rotation: Math.round(angle + (side === 'out' ? -38 : 38)), side, index })
    }
  }
  return leaves
}

/**
 * Trazado de una onda continua hecha con curvas cuadráticas.
 *
 * @param {number} y - Altura de la línea media.
 * @param {number} amplitude - Altura de cada cresta y de cada seno.
 * @param {number} wavelength - Longitud de onda.
 * @param {number} width - Ancho que cubre; conviene que sea múltiplo de `wavelength / 2`.
 * @returns {string} El trazado SVG (`d`) de la línea, de izquierda a derecha.
 */
export function wavePath(y, amplitude, wavelength, width) {
  let path = `M0 ${y} Q${wavelength / 4} ${y - amplitude} ${wavelength / 2} ${y}`
  for (let x = wavelength; x <= width; x += wavelength / 2) path += ` T${x} ${y}`
  return path
}

/**
 * Trazado de una serpiente que ondula a lo largo de una línea recta.
 *
 * @param {number} length - Largo de la serpiente.
 * @param {number} sway - Cuánto se aparta del eje en cada ondulación.
 * @param {number} [bends=3] - Cuántas ondulaciones lleva (al menos 1).
 * @returns {string} El trazado SVG (`d`), que va del origen hacia arriba (y negativa).
 */
export function snakePath(length, sway, bends = 3) {
  const step = length / bends
  let path = 'M0 0'
  for (let bend = 0; bend < bends; bend += 1) {
    const direction = bend % 2 === 0 ? 1 : -1
    path += ` C${direction * sway} ${-bend * step - step * 0.35} ${direction * sway} ${-bend * step - step * 0.65} 0 ${-(bend + 1) * step}`
  }
  return path
}
