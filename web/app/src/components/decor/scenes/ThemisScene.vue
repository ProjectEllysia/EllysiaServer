<template>
  <StarChart :chart="CHART" />
</template>

<script setup>
import StarChart from '../StarChart.vue'

/**
 * Escena de Themis: una lámina de atlas con Libra, la balanza que la tradición pone
 * en manos de Themis y de su hija Astrea, y al lado Escorpio: Libra fueron sus pinzas
 * antes de ser balanza. Posiciones J2000 en grados y magnitud visual de catálogo.
 */
const CHART = {
  // Libra queda a la derecha, donde el texto de la cabecera no la tapa.
  projection: { ra: 229, dec: -19, scale: 1250, x: 930, y: 300 },
  grid: { raRange: [210, 285], decRange: [-50, 5], raLabels: [225, 240, 255, 270], raLabelDec: -5.6, decLabels: [-10, -20, -30], decLabelRa: 216.5 },
  ecliptic: [190, 290],
  fieldSeed: 1311,
  constellations: [
    {
      name: 'LIBRA',
      label: { ra: 231.5, dec: -33.5 },
      stars: [
        { letter: 'α', ra: 222.72, dec: -16.04, magnitude: 2.75, name: 'Zubenelgenubi' },
        { letter: 'β', ra: 229.25, dec: -9.38, magnitude: 2.61, name: 'Zubeneschamali' },
        { letter: 'γ', ra: 233.88, dec: -14.79, magnitude: 3.91 },
        { letter: 'σ', ra: 226.02, dec: -25.28, magnitude: 3.29 },
        { letter: 'υ', ra: 234.26, dec: -28.14, magnitude: 3.58 },
        { letter: 'τ', ra: 234.66, dec: -29.78, magnitude: 3.66 },
        { letter: 'θ', ra: 238.46, dec: -16.73, magnitude: 4.15 },
        { letter: 'ι', ra: 228.05, dec: -19.79, magnitude: 4.54 },
      ],
      pairs: [['α', 'β'], ['β', 'γ'], ['γ', 'α'], ['α', 'σ'], ['γ', 'υ'], ['υ', 'τ'], ['γ', 'θ']],
    },
    {
      name: 'SCORPIUS',
      isNeighbour: true,
      label: { ra: 250, dec: -17.5 },
      stars: [
        { letter: 'β', ra: 241.36, dec: -19.81, magnitude: 2.62 },
        { letter: 'δ', ra: 240.08, dec: -22.62, magnitude: 2.29 },
        { letter: 'π', ra: 239.71, dec: -26.11, magnitude: 2.89 },
        { letter: 'ρ', ra: 239.22, dec: -29.21, magnitude: 3.87 },
        { letter: 'σ', ra: 245.3, dec: -25.59, magnitude: 2.89 },
        { letter: 'α', ra: 247.35, dec: -26.43, magnitude: 1.06, name: 'Antares' },
        { letter: 'τ', ra: 248.97, dec: -28.22, magnitude: 2.82 },
        { letter: 'ε', ra: 252.54, dec: -34.29, magnitude: 2.29 },
      ],
      pairs: [['β', 'δ'], ['δ', 'π'], ['π', 'ρ'], ['δ', 'σ'], ['σ', 'α'], ['α', 'τ'], ['τ', 'ε']],
    },
  ],
}
</script>
