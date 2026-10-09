<template>
  <StarChart :chart="CHART" />
</template>

<script setup>
import StarChart from '../StarChart.vue'

/**
 * Escena de Hygeia: una lámina de atlas con el Serpentario, que es Asclepio, padre
 * de Hygeia, sosteniendo la Serpiente; la única constelación partida en dos, cabeza
 * a un lado y cola al otro. Posiciones J2000 en grados y magnitud visual de catálogo.
 */
const CHART = {
  projection: { ra: 255, dec: -3, scale: 680, x: 830, y: 300 },
  grid: { raRange: [225, 295], decRange: [-35, 30], raLabels: [240, 255, 270, 285], raLabelDec: 21.5, decLabels: [-20, -10, 0, 10], decLabelRa: 232 },
  ecliptic: [230, 300],
  fieldSeed: 7310,
  constellations: [
    {
      name: 'OPHIUCHUS',
      label: { ra: 262, dec: -30 },
      labelLimit: 3.9,
      stars: [
        { letter: 'α', ra: 263.73, dec: 12.56, magnitude: 2.08, name: 'Rasalhague' },
        { letter: 'β', ra: 265.87, dec: 4.57, magnitude: 2.76 },
        { letter: 'η', ra: 257.59, dec: -15.72, magnitude: 2.43, name: 'Sabik' },
        { letter: 'ζ', ra: 249.29, dec: -10.57, magnitude: 2.56 },
        { letter: 'δ', ra: 243.59, dec: -3.69, magnitude: 2.73 },
        { letter: 'ε', ra: 244.58, dec: -4.69, magnitude: 3.23 },
        { letter: 'κ', ra: 254.42, dec: 9.38, magnitude: 3.19 },
        { letter: 'λ', ra: 247.73, dec: 1.98, magnitude: 3.82 },
        { letter: 'γ', ra: 266.97, dec: 2.71, magnitude: 3.75 },
        { letter: 'ν', ra: 269.76, dec: -9.77, magnitude: 3.32 },
        { letter: 'θ', ra: 260.5, dec: -24.99, magnitude: 3.27 },
        { letter: 'ι', ra: 253.5, dec: 10.17, magnitude: 4.38 },
      ],
      pairs: [['α', 'κ'], ['κ', 'λ'], ['λ', 'δ'], ['δ', 'ε'], ['ε', 'ζ'], ['ζ', 'η'], ['η', 'θ'], ['η', 'ν'], ['ν', 'γ'], ['γ', 'β'], ['β', 'α'], ['κ', 'ι']],
    },
    {
      name: 'SERPENS',
      label: { ra: 236, dec: 23 },
      labelLimit: 3.9,
      stars: [
        // Cabeza, al oeste del Serpentario
        { letter: 'κ', ra: 237.18, dec: 18.14, magnitude: 4.09 },
        { letter: 'γ', ra: 239.11, dec: 15.66, magnitude: 3.85 },
        { letter: 'β', ra: 236.55, dec: 15.42, magnitude: 3.65 },
        { letter: 'δ', ra: 233.7, dec: 10.54, magnitude: 3.8 },
        { letter: 'α', ra: 236.07, dec: 6.43, magnitude: 2.63, name: 'Unukalhai' },
        { letter: 'ε', ra: 237.7, dec: 4.48, magnitude: 3.71 },
        { letter: 'μ', ra: 237.4, dec: -3.43, magnitude: 3.54 },
        // Cola, al este
        { letter: 'ν', ra: 260.21, dec: -12.85, magnitude: 4.32 },
        { letter: 'ξ', ra: 264.4, dec: -15.4, magnitude: 3.54 },
        { letter: 'ο', ra: 265.35, dec: -12.88, magnitude: 4.26 },
        { letter: 'ζ', ra: 268.38, dec: -3.69, magnitude: 4.62 },
        { letter: 'η', ra: 275.33, dec: -2.9, magnitude: 3.23 },
        { letter: 'θ', ra: 284.06, dec: 4.2, magnitude: 4.62, name: 'Alya' },
      ],
      pairs: [
        ['κ', 'γ'], ['γ', 'β'], ['β', 'κ'], ['β', 'δ'], ['δ', 'α'], ['α', 'ε'], ['ε', 'μ'],
        ['ν', 'ξ'], ['ξ', 'ο'], ['ο', 'ζ'], ['ζ', 'η'], ['η', 'θ'],
      ],
    },
  ],
}
</script>
