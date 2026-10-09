<template>
  <StarChart :chart="CHART" />
</template>

<script setup>
import StarChart from '../StarChart.vue'

/**
 * Escena de Aegis: el mito de Perseo entero en una lámina de atlas. A la izquierda,
 * Perseo con la cabeza de Medusa, la que Atenea llevó después en su égida; en ella
 * está Algol, «la cabeza del demonio», una estrella que se eclipsa de verdad cada casi
 * tres días y aquí se apaga un momento cada ciclo. A la derecha, Andrómeda, a la que
 * Perseo salvó del monstruo con esa cabeza, con su galaxia; arriba, su madre Casiopea,
 * y abajo, Pegaso, con quien comparte estrella.
 *
 * En el cielo real las tres figuras forman una diagonal, así que la lámina abarca lo
 * bastante para que Perseo quede a un lado y Andrómeda al otro sin forzar nada.
 * Posiciones J2000 en grados y magnitud visual de catálogo.
 */
const CHART = {
  projection: { ra: 22, dec: 43, scale: 900, x: 600, y: 320 },
  // La lámina cruza las 0h: la ascensión recta va de −45° (21h) a 95°.
  grid: { raRange: [-45, 95], decRange: [8, 78], raLabels: [-15, 0, 15, 30, 45, 60], raLabelDec: 62, decLabels: [20, 30, 40, 50], decLabelRa: -21 },
  ecliptic: null,
  fieldSeed: 4021,
  constellations: [
    {
      name: 'CASSIOPEIA',
      isNeighbour: true,
      label: { ra: -4, dec: 56.2 },
      stars: [
        { letter: 'β', ra: 2.29, dec: 59.15, magnitude: 2.28 },
        { letter: 'α', ra: 10.13, dec: 56.54, magnitude: 2.24 },
        { letter: 'γ', ra: 14.18, dec: 60.72, magnitude: 2.15 },
        { letter: 'δ', ra: 21.45, dec: 60.24, magnitude: 2.68 },
        { letter: 'ε', ra: 28.6, dec: 63.67, magnitude: 3.37 },
      ],
      pairs: [['β', 'α'], ['α', 'γ'], ['γ', 'δ'], ['δ', 'ε']],
    },
    {
      name: 'PEGASUS',
      isNeighbour: true,
      label: { ra: 350, dec: 21.5 },
      stars: [
        { letter: 'αAnd', ra: 2.1, dec: 29.09, magnitude: 2.06 },
        { letter: 'β', ra: 345.94, dec: 28.08, magnitude: 2.42, name: 'Scheat' },
        { letter: 'α', ra: 346.19, dec: 15.21, magnitude: 2.49 },
        { letter: 'γ', ra: 3.31, dec: 15.18, magnitude: 2.83 },
        { letter: 'η', ra: 340.75, dec: 30.22, magnitude: 2.94 },
        { letter: 'μ', ra: 342.5, dec: 24.6, magnitude: 3.48 },
      ],
      pairs: [['αAnd', 'β'], ['β', 'α'], ['α', 'γ'], ['γ', 'αAnd'], ['β', 'η'], ['β', 'μ']],
    },
    {
      name: 'TRIANGULUM',
      isNeighbour: true,
      label: null,
      stars: [
        { letter: 'α', ra: 28.27, dec: 29.58, magnitude: 3.42 },
        { letter: 'β', ra: 32.39, dec: 34.99, magnitude: 3 },
        { letter: 'γ', ra: 34.33, dec: 33.85, magnitude: 4.01 },
      ],
      pairs: [['α', 'β'], ['β', 'γ'], ['γ', 'α']],
    },
    {
      name: 'PERSEUS',
      label: { ra: 66, dec: 43 },
      labelLimit: 4.2,
      stars: [
        { letter: 'α', ra: 51.08, dec: 49.86, magnitude: 1.79, name: 'Mirfak' },
        { letter: 'β', ra: 47.04, dec: 40.96, magnitude: 2.12, name: 'Algol', nameSide: 'left', isEclipsing: true },
        { letter: 'γ', ra: 46.2, dec: 53.51, magnitude: 2.91 },
        { letter: 'δ', ra: 55.73, dec: 47.79, magnitude: 3.01 },
        { letter: 'ε', ra: 59.46, dec: 40.01, magnitude: 2.89 },
        { letter: 'ζ', ra: 58.53, dec: 31.88, magnitude: 2.85 },
        { letter: 'η', ra: 42.67, dec: 55.9, magnitude: 3.76 },
        { letter: 'ξ', ra: 59.74, dec: 35.79, magnitude: 4.04 },
        { letter: 'ο', ra: 56.08, dec: 32.29, magnitude: 3.83 },
        { letter: 'ρ', ra: 46.29, dec: 38.84, magnitude: 3.39 },
        { letter: 'ω', ra: 48.11, dec: 39.61, magnitude: 4.63 },
        { letter: 'π', ra: 44.69, dec: 39.66, magnitude: 4.7 },
        { letter: 'ν', ra: 56.3, dec: 42.58, magnitude: 3.77 },
        { letter: 'κ', ra: 47.37, dec: 44.86, magnitude: 3.8 },
        { letter: 'τ', ra: 43.56, dec: 52.76, magnitude: 3.95 },
        { letter: 'ι', ra: 47.27, dec: 49.61, magnitude: 4.05 },
        { letter: 'θ', ra: 41.05, dec: 49.23, magnitude: 4.12 },
        { letter: 'μ', ra: 63.72, dec: 48.41, magnitude: 4.14 },
      ],
      pairs: [
        ['η', 'τ'], ['τ', 'γ'], ['γ', 'α'], ['α', 'δ'], ['δ', 'ν'], ['ν', 'ε'], ['ε', 'ξ'], ['ξ', 'ζ'], ['ζ', 'ο'],
        ['δ', 'μ'], ['α', 'ι'], ['ι', 'θ'], ['ι', 'κ'], ['κ', 'β'], ['β', 'ρ'], ['β', 'ω'], ['β', 'π'],
      ],
    },
    {
      name: 'ANDROMEDA',
      label: { ra: 2, dec: 37.2 },
      labelLimit: 3.9,
      stars: [
        { letter: 'α', ra: 2.1, dec: 29.09, magnitude: 2.06, name: 'Alpheratz' },
        { letter: 'β', ra: 17.43, dec: 35.62, magnitude: 2.05, name: 'Mirach' },
        { letter: 'γ', ra: 30.97, dec: 42.33, magnitude: 2.1, name: 'Almach' },
        { letter: 'δ', ra: 9.83, dec: 30.86, magnitude: 3.27 },
        { letter: 'μ', ra: 14.19, dec: 38.5, magnitude: 3.86 },
        { letter: 'ν', ra: 12.45, dec: 41.08, magnitude: 4.53 },
        { letter: 'π', ra: 9.22, dec: 33.72, magnitude: 4.34 },
        { letter: 'ε', ra: 9.64, dec: 29.31, magnitude: 4.37 },
        { letter: 'ζ', ra: 11.83, dec: 24.27, magnitude: 4.06 },
        { letter: 'η', ra: 14.3, dec: 23.42, magnitude: 4.4 },
        { letter: 'ο', ra: 345.48, dec: 42.33, magnitude: 3.62 },
        { letter: 'λ', ra: 354.39, dec: 46.46, magnitude: 3.82 },
        { letter: 'κ', ra: 355.1, dec: 44.33, magnitude: 4.14 },
        { letter: 'ι', ra: 354.53, dec: 43.27, magnitude: 4.29 },
        { letter: 'θ', ra: 4.27, dec: 38.68, magnitude: 4.61 },
      ],
      pairs: [
        ['α', 'δ'], ['δ', 'β'], ['β', 'γ'], ['β', 'μ'], ['μ', 'ν'], ['δ', 'π'], ['π', 'θ'], ['θ', 'ι'],
        ['ι', 'κ'], ['κ', 'λ'], ['ι', 'ο'], ['δ', 'ε'], ['ε', 'ζ'], ['ζ', 'η'],
      ],
    },
  ],
  annotations: [{ text: 'Caput Medusae', ra: 45.2, dec: 36.4 }],
  nebulae: [{ label: 'M31', ra: 10.68, dec: 41.27, length: 3.2, width: 1, positionAngle: 35 }],
}
</script>
