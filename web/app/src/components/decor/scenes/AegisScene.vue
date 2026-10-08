<template>
  <svg class="scene" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
    <defs>
      <radialGradient id="aegis-gaze">
        <stop offset="0" stop-color="var(--accent-bright)" stop-opacity="0.9" />
        <stop offset="1" stop-color="var(--accent-bright)" stop-opacity="0" />
      </radialGradient>
    </defs>

    <!-- La égida: el escudo de Atenea, con la cabeza de la Gorgona en el centro. -->
    <g transform="translate(860 318) scale(1)">
      <circle class="rim" r="244" />
      <circle class="beads" r="198" />
      <circle class="rim rim--inner" r="168" />

      <!-- Las tachuelas del borde se encienden una tras otra, como una guardia que vela. -->
      <circle
        v-for="stud in STUDS"
        :key="`stud-${stud.index}`"
        class="stud"
        :cx="stud.x"
        :cy="stud.y"
        r="3.2"
        :style="{ '--delay': `${stud.index * 0.22}s` }"
      />

      <!-- Las serpientes que la Gorgona lleva por cabellera. -->
      <g v-for="snake in SNAKES" :key="`snake-${snake.index}`" :transform="`rotate(${snake.angle})`">
        <g class="snake" :style="{ '--delay': `${snake.delay}s`, '--duration': `${snake.duration}s` }">
          <g transform="translate(0 -52)">
            <path class="body" :d="SNAKE_BODY" />
            <circle class="head" cx="0" :cy="-SNAKE_LENGTH" r="4.2" />
          </g>
        </g>
      </g>

      <circle class="face" r="54" />
      <circle class="gaze" r="46" cy="-6" fill="url(#aegis-gaze)" />
      <!-- El gesto de la Gorgona: ceño fruncido, ojos desorbitados, boca abierta y la lengua fuera. -->
      <path class="brow" d="M-40 -26 L-8 -14 M40 -26 L8 -14" />
      <circle class="eye" cx="-21" cy="-6" r="9.5" />
      <circle class="eye" cx="21" cy="-6" r="9.5" />
      <circle class="pupil" cx="-21" cy="-6" r="3.4" />
      <circle class="pupil" cx="21" cy="-6" r="3.4" />
      <path class="brow" d="M0 4 L-4 16 H4 Z" />
      <path class="mouth" d="M-26 22 H26 L22 36 H-22 Z" />
      <path class="brow" d="M-13 22 V31 M0 22 V33 M13 22 V31" />
      <path class="tongue" d="M-7 36 C-7 52 7 52 7 36" />
    </g>

    <!-- Atenea también es la lechuza y el olivo: una rama con su lechuza, vigilando. -->
    <g transform="translate(150 548)">
      <path class="branch" d="M0 0 C70 -34 150 -52 250 -44" />
      <g v-for="(leaf, index) in LEAVES" :key="`leaf-${index}`" :transform="`translate(${leaf.x} ${leaf.y}) rotate(${leaf.rotation})`">
        <ellipse class="leaf" rx="15" ry="5" :style="{ '--delay': `${-index * 0.7}s` }" />
      </g>
      <g transform="translate(236 -46)">
        <g class="owl">
          <path class="owl-body" d="M-24 0 C-30 -30 -26 -56 -18 -64 L-24 -82 L-8 -70 Q0 -74 8 -70 L24 -82 L18 -64 C26 -56 30 -30 24 0 Z" />
          <path class="owl-feather" d="M-12 -22 q6 6 12 0 q6 6 12 0 M-10 -10 q5 5 10 0 q5 5 10 0" />
          <circle class="owl-eye" cx="-10" cy="-52" r="9" />
          <circle class="owl-eye" cx="10" cy="-52" r="9" />
          <circle class="owl-pupil" cx="-10" cy="-52" r="3.4" />
          <circle class="owl-pupil" cx="10" cy="-52" r="3.4" />
          <path class="owl-body" d="M-3 -44 L0 -37 L3 -44 Z" />
        </g>
      </g>
    </g>
  </svg>
</template>

<script setup>
import { polarPoint, snakePath } from '../sceneGeometry'

/**
 * Escena de Aegis: la égida, el escudo de Atenea con la cabeza de la Gorgona, cuyas
 * serpientes se retuercen sin parar y cuya mirada late; junto a ella, la rama de
 * olivo y la lechuza de la diosa. Es la protección de Aegis: una guardia que no
 * duerme y que avisa antes de que el golpe llegue.
 */

const SNAKE_LENGTH = 92
const SNAKE_BODY = snakePath(SNAKE_LENGTH, 11, 3)

const SNAKES = Array.from({ length: 16 }, (_, index) => ({
  index,
  angle: index * (360 / 16),
  delay: -((index * 0.83) % 5),
  duration: 4.2 + (index % 4) * 0.6,
}))

const STUDS = Array.from({ length: 28 }, (_, index) => ({ index, ...polarPoint(0, 0, 226, index * (360 / 28)) }))

// Hojas del olivo: una rama que se curva y lleva hojas alternas a los dos lados.
const LEAVES = Array.from({ length: 9 }, (_, index) => {
  const t = (index + 0.6) / 9.6
  return {
    x: Math.round(t * 236),
    y: Math.round(-t * 36 - Math.sin(t * Math.PI) * 10),
    rotation: -18 + (index % 2 === 0 ? -48 : 48),
  }
})
</script>

<style scoped>
.scene { width: 100%; height: 100%; display: block; }

.rim, .brow, .branch, .body, .owl-feather { fill: none; stroke: var(--accent-bright); stroke-linecap: round; stroke-linejoin: round; }
.rim { stroke-width: 2.2; opacity: 0.5; }
.rim--inner { stroke-width: 1.2; opacity: 0.35; }
.beads { fill: none; stroke: var(--accent-bright); stroke-width: 18; stroke-dasharray: 5 9; opacity: 0.16; transform-box: fill-box; transform-origin: center; animation: turn 140s linear infinite; }
@keyframes turn { to { transform: rotate(360deg); } }

.stud { fill: var(--accent-bright); opacity: 0.2; animation: guard 6.2s ease-in-out var(--delay) infinite; }
@keyframes guard { 0%, 100% { opacity: 0.18; } 6% { opacity: 1; } 16% { opacity: 0.18; } }

/* Serpientes: cada una se retuerce en torno al centro con su propio compás */
.snake { animation: writhe var(--duration) ease-in-out var(--delay) infinite alternate; }
@keyframes writhe { from { transform: rotate(-7deg); } to { transform: rotate(7deg); } }
.body { stroke-width: 3; opacity: 0.55; }
.head { fill: var(--accent-bright); opacity: 0.8; }

/* Rostro y mirada */
.face { fill: var(--bg); stroke: var(--accent-bright); stroke-width: 2.2; opacity: 0.92; }
.brow { stroke-width: 2.2; opacity: 0.7; }
.mouth { fill: var(--bg); stroke: var(--accent-bright); stroke-width: 2; stroke-linejoin: round; opacity: 0.8; }
.tongue { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 2; stroke-linecap: round; opacity: 0.8; transform-box: fill-box; transform-origin: 50% 0%; animation: loll 3.6s ease-in-out infinite alternate; }
@keyframes loll { from { transform: scaleY(0.8); } to { transform: scaleY(1.12); } }
.eye { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.6; }
.pupil { fill: var(--accent-bright); animation: stare 5s ease-in-out infinite; }
.gaze { opacity: 0.4; animation: gaze 5s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
@keyframes stare { 0%, 100% { transform: translateX(0); } 40% { transform: translateX(1.6px); } 70% { transform: translateX(-1.6px); } }
@keyframes gaze { 0%, 100% { opacity: 0.2; transform: scale(0.9); } 50% { opacity: 0.55; transform: scale(1.1); } }

/* Olivo y lechuza */
.branch { stroke-width: 2.4; opacity: 0.5; }
.leaf { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.2; opacity: 0.7; transform-box: fill-box; transform-origin: 0% 50%; animation: leaf 5.5s ease-in-out var(--delay) infinite alternate; }
@keyframes leaf { from { transform: rotate(-5deg); } to { transform: rotate(6deg); } }
.owl { transform-box: fill-box; transform-origin: 50% 100%; animation: owl-turn 9s ease-in-out infinite; }
@keyframes owl-turn { 0%, 70%, 100% { transform: rotate(0); } 78%, 90% { transform: rotate(-6deg); } }
.owl-body { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.8; stroke-linejoin: round; opacity: 0.8; }
.owl-feather { stroke-width: 1.2; opacity: 0.5; }
.owl-eye { fill: var(--bg); stroke: var(--accent-bright); stroke-width: 1.6; }
.owl-pupil { fill: var(--accent-bright); transform-box: fill-box; transform-origin: center; animation: blink 7s ease-in-out infinite; }
@keyframes blink { 0%, 93%, 100% { transform: scaleY(1); } 96% { transform: scaleY(0.08); } }
</style>
