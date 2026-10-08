<template>
  <svg class="scene" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
    <!-- Libra: la constelación de la balanza, que la tradición liga a Themis y a Astrea. -->
    <g class="libra" transform="translate(70 0)">
      <path v-for="(edge, index) in EDGES" :key="`edge-${index}`" class="constellation" :d="edge.path" pathLength="1" :style="{ '--delay': `${edge.delay}s` }" />
      <g v-for="(star, index) in STARS" :key="`star-${index}`" :transform="`translate(${star.x} ${star.y})`">
        <circle class="star-halo" :r="star.radius * 3.2" :style="{ '--delay': `${star.delay}s` }" />
        <circle class="star" :r="star.radius" :style="{ '--delay': `${star.delay}s` }" />
      </g>
    </g>

    <!-- La balanza, con el cielo girando tras ella. -->
    <g transform="translate(860 322) scale(1.04)">
      <circle class="ring ring--ticks" r="262" />
      <circle class="ring ring--slow" r="226" />

      <path class="frame" d="M0 -120 V148 M-62 150 H62 M-42 150 C-34 128 34 128 42 150" />
      <circle class="frame" cx="0" cy="-130" r="7" />

      <!-- Los platillos suben y bajan al compás del astil: mismo tiempo y misma curva. -->
      <g class="pan pan--left">
        <path class="chain" d="M-170 -110 L-218 -8 M-170 -110 L-122 -8" />
        <path class="bowl" d="M-228 -8 C-228 22 -194 36 -170 36 C-146 36 -112 22 -112 -8 Z" />
        <circle class="mote" cx="-186" cy="-18" r="5" />
        <circle class="mote" cx="-160" cy="-14" r="4" />
      </g>
      <g class="pan pan--right">
        <path class="chain" d="M170 -110 L122 -8 M170 -110 L218 -8" />
        <path class="bowl" d="M112 -8 C112 22 146 36 170 36 C194 36 228 22 228 -8 Z" />
        <circle class="mote mote--bright" cx="170" cy="-18" r="7" />
      </g>

      <g class="beam">
        <path class="frame" d="M-176 -110 H176" />
        <circle class="frame" cx="-176" cy="-110" r="6" />
        <circle class="frame" cx="176" cy="-110" r="6" />
        <circle class="pivot" cx="0" cy="-110" r="10" />
      </g>
    </g>
  </svg>
</template>

<script setup>
/**
 * Escena de Themis: la balanza de la justicia, que pesa sin prisa, y la constelación
 * de Libra, que la tradición asocia con Themis y con su hija Astrea. Es el gesto de
 * Themis en el producto: pesar cada amenaza antes de decidir.
 */

/** Estrellas de Libra, con su posición y su brillo; el retraso escalona el centelleo. */
const STARS = [
  { x: 150, y: 190, radius: 3.4, delay: 0 },
  { x: 268, y: 120, radius: 4.2, delay: -1.3 },
  { x: 392, y: 168, radius: 3.6, delay: -2.7 },
  { x: 346, y: 280, radius: 3.2, delay: -0.6 },
  { x: 222, y: 268, radius: 3, delay: -3.4 },
  { x: 92, y: 306, radius: 2.6, delay: -2 },
  { x: 462, y: 98, radius: 2.8, delay: -4.1 },
]

/** Cada arista une dos estrellas por su índice; se dibujan una tras otra. */
const EDGES = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 0], [0, 5], [1, 6]].map(([from, to], index) => ({
  path: `M${STARS[from].x} ${STARS[from].y} L${STARS[to].x} ${STARS[to].y}`,
  delay: index * 0.45,
}))
</script>

<style scoped>
.scene { width: 100%; height: 100%; display: block; }

.frame, .chain, .bowl, .ring, .constellation { fill: none; stroke: var(--accent-bright); stroke-linecap: round; stroke-linejoin: round; }
.frame { stroke-width: 2; opacity: 0.6; }
.chain { stroke-width: 1.2; opacity: 0.45; }
.bowl { fill: var(--accent-dim); stroke-width: 1.8; opacity: 0.7; }
.pivot { fill: var(--accent-bright); opacity: 0.55; }

/* El cielo que gira detrás: una corona de marcas y un anillo discontinuo */
.ring { opacity: 0.22; transform-box: fill-box; transform-origin: center; }
.ring--ticks { stroke-width: 7; stroke-dasharray: 1.5 18; animation: turn 220s linear infinite; }
.ring--slow { stroke-width: 1; stroke-dasharray: 3 9; animation: turn 150s linear infinite reverse; }
@keyframes turn { to { transform: rotate(360deg); } }

/* Astil y platillos: el astil se inclina 7°, así que sus extremos suben o bajan unos 21 px */
.beam, .pan { animation-duration: 9s; animation-timing-function: ease-in-out; animation-iteration-count: infinite; animation-direction: alternate; }
.beam { transform-box: fill-box; transform-origin: center; animation-name: tilt; }
@keyframes tilt { from { transform: rotate(-7deg); } to { transform: rotate(7deg); } }
.pan--left { animation-name: pan-down-first; }
.pan--right { animation-name: pan-up-first; }
@keyframes pan-down-first { from { transform: translateY(21px); } to { transform: translateY(-21px); } }
@keyframes pan-up-first { from { transform: translateY(-21px); } to { transform: translateY(21px); } }
.mote { fill: var(--accent-bright); opacity: 0.8; animation: twinkle 4s ease-in-out infinite alternate; }
.mote--bright { opacity: 0.95; filter: drop-shadow(0 0 8px var(--accent-bright)); }

/* Libra: las aristas se dibujan, se quedan un rato y se apagan; las estrellas centellean */
.constellation { stroke-width: 1.1; stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; animation: draw-edge 16s ease-in-out var(--delay) infinite; }
@keyframes draw-edge {
  0%   { stroke-dashoffset: 1; opacity: 0; }
  6%   { opacity: 0.55; }
  22%  { stroke-dashoffset: 0; opacity: 0.55; }
  78%  { stroke-dashoffset: 0; opacity: 0.4; }
  100% { stroke-dashoffset: 0; opacity: 0; }
}
.star { fill: var(--accent-bright); animation: twinkle 3.6s ease-in-out var(--delay) infinite alternate; }
.star-halo { fill: var(--accent-bright); opacity: 0.12; animation: halo 3.6s ease-in-out var(--delay) infinite alternate; transform-box: fill-box; transform-origin: center; }
@keyframes twinkle { from { opacity: 0.35; } to { opacity: 1; } }
@keyframes halo { from { opacity: 0.04; transform: scale(0.7); } to { opacity: 0.2; transform: scale(1.15); } }
</style>
