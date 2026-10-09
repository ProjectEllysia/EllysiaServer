/**
 * Óptica sin Vue para la escena de Iris (`scenes/IrisScene.vue`): el color de cada
 * longitud de onda, las líneas oscuras del espectro del Sol y el ángulo al que cada
 * color forma el arcoíris. Se prueba con `node` a secas. Las longitudes de onda van
 * en nanómetros.
 */

/**
 * Líneas de Fraunhofer: los huecos oscuros del espectro del Sol, que Fraunhofer
 * rotuló con letras en 1814. Cada una es la huella de un elemento que absorbe esa luz.
 * `depth` es cuánto oscurece la curva (de 0 a 1) y `width`, su anchura en el dibujo.
 */
export const FRAUNHOFER_LINES = Object.freeze([
  { letter: 'A', nm: 759.37, element: 'O₂', depth: 0.55, width: 2.2 },
  { letter: 'B', nm: 686.72, element: 'O₂', depth: 0.45, width: 1.8 },
  { letter: 'C', nm: 656.28, element: 'Hα', depth: 0.6, width: 1.6 },
  { letter: 'D', nm: 589.3, element: 'Na', depth: 0.75, width: 2.6 },
  { letter: 'E', nm: 527.04, element: 'Fe', depth: 0.5, width: 1.3 },
  { letter: 'b', nm: 518.36, element: 'Mg', depth: 0.55, width: 1.6 },
  { letter: 'F', nm: 486.13, element: 'Hβ', depth: 0.6, width: 1.6 },
  { letter: 'G', nm: 430.79, element: 'Fe', depth: 0.5, width: 1.6 },
  { letter: 'h', nm: 410.17, element: 'Hδ', depth: 0.4, width: 1.2 },
  { letter: 'H', nm: 396.85, element: 'Ca⁺', depth: 0.85, width: 2.6 },
  { letter: 'K', nm: 393.37, element: 'Ca⁺', depth: 0.85, width: 2.6 },
])

/**
 * Color visible de una longitud de onda, por tramos lineales entre los colores puros
 * del espectro y con el brillo apagándose en los dos bordes, donde el ojo ve poco.
 *
 * @param {number} nm - Longitud de onda, en nanómetros.
 * @returns {[number, number, number]} Rojo, verde y azul en [0, 255]. Fuera de
 *   [380, 780] es negro.
 */
export function wavelengthToRgb(nm) {
  let red = 0
  let green = 0
  let blue = 0
  if (nm >= 380 && nm < 440) { red = (440 - nm) / 60; blue = 1 }
  else if (nm >= 440 && nm < 490) { green = (nm - 440) / 50; blue = 1 }
  else if (nm >= 490 && nm < 510) { green = 1; blue = (510 - nm) / 20 }
  else if (nm >= 510 && nm < 580) { red = (nm - 510) / 70; green = 1 }
  else if (nm >= 580 && nm < 645) { red = 1; green = (645 - nm) / 65 }
  else if (nm >= 645 && nm <= 780) { red = 1 }

  let intensity = 0
  if (nm >= 380 && nm < 420) intensity = 0.3 + (0.7 * (nm - 380)) / 40
  else if (nm >= 420 && nm <= 700) intensity = 1
  else if (nm > 700 && nm <= 780) intensity = 0.3 + (0.7 * (780 - nm)) / 80

  const channel = (value) => (value === 0 ? 0 : Math.round(255 * (value * intensity) ** 0.8))
  return [channel(red), channel(green), channel(blue)]
}

/**
 * Índice de refracción del agua según la longitud de onda (ecuación de Cauchy ajustada
 * al agua a 20 °C): 1,3433 en el violeta, 1,3330 en la línea D del sodio y 1,3304 en
 * el rojo. Esa pequeña diferencia es la que separa los colores del arcoíris.
 *
 * @param {number} nm - Longitud de onda, en nanómetros.
 * @returns {number} El índice de refracción.
 */
export function waterIndex(nm) {
  const microns = nm / 1000
  return 1.3242 + 0.00306 / microns ** 2
}

/**
 * Radio angular del arcoíris para un color, medido desde el punto opuesto al Sol: el
 * ángulo de desviación mínima de un rayo que entra en una gota esférica, se refleja
 * dentro `reflections` veces y sale (la explicación de Descartes, 1637). Ahí se
 * acumula la luz, y por eso el arco se ve a ese ángulo y no a otro.
 *
 * @param {number} nm - Longitud de onda, en nanómetros.
 * @param {number} [reflections=1] - Reflexiones dentro de la gota: `1` para el arco
 *   primario (unos 42°, con el rojo fuera) y `2` para el secundario (unos 51°, con los
 *   colores invertidos).
 * @returns {number} El radio angular del arco, en grados.
 */
export function rainbowAngle(nm, reflections = 1) {
  const index = waterIndex(nm)
  const incidence = Math.acos(Math.sqrt((index ** 2 - 1) / (reflections * (reflections + 2))))
  const refraction = Math.asin(Math.sin(incidence) / index)
  const deviation = 2 * (incidence - refraction) + reflections * (Math.PI - 2 * refraction)
  const fromAntisolar = Math.abs((deviation % (2 * Math.PI)) - Math.PI)
  return (fromAntisolar * 180) / Math.PI
}
