<template>
  <svg class="scene" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
    <defs>
      <radialGradient id="hygeia-glow">
        <stop offset="0" stop-color="var(--accent-bright)" stop-opacity="0.55" />
        <stop offset="1" stop-color="var(--accent-bright)" stop-opacity="0" />
      </radialGradient>
    </defs>

    <g transform="translate(860 214) scale(1.02)">
      <!-- La corona de laurel, que rodea la copa. -->
      <g class="wreath">
        <path class="stem" :d="ARC_LEFT" />
        <path class="stem" :d="ARC_RIGHT" />
        <g v-for="(leaf, index) in LEAVES" :key="`leaf-${index}`" :transform="`translate(${leaf.x} ${leaf.y}) rotate(${leaf.rotation})`">
          <ellipse class="leaf" rx="14" ry="5.2" :style="{ '--delay': `${-leaf.index * 0.55}s` }" />
        </g>
      </g>

      <!-- La luz que sube de la copa: la salud que Hygeia ofrece. -->
      <ellipse class="glow" cx="0" cy="-6" rx="150" ry="110" fill="url(#hygeia-glow)" />
      <circle
        v-for="(mote, index) in MOTES"
        :key="`mote-${index}`"
        class="mote"
        :cx="mote.x"
        cy="-10"
        :r="mote.radius"
        :style="{ '--rise': `${mote.rise}px`, '--duration': `${mote.duration}s`, '--delay': `${mote.delay}s`, '--sway': `${mote.sway}px` }"
      />

      <!-- La copa de Hygeia y la serpiente que bebe de ella. -->
      <path class="cup" d="M-92 0 C-92 70 -46 112 0 112 C46 112 92 70 92 0" />
      <ellipse class="cup" cx="0" cy="0" rx="92" ry="16" />
      <path class="cup" d="M-14 110 C-10 142 -12 164 -42 186 H42 C12 164 10 142 14 110" />
      <ellipse class="cup" cx="0" cy="188" rx="62" ry="9" />

      <path class="snake" :d="SNAKE" />
      <path class="scales" :d="SNAKE" />
      <g transform="translate(76 -60) rotate(-35)">
        <g class="head">
          <ellipse class="snake-head" rx="13" ry="7.5" />
          <circle class="snake-eye" cx="3" cy="-1.6" r="1.8" />
          <path class="tongue" d="M-13 0 L-24 0 M-24 0 L-30 -4 M-24 0 L-30 4" />
        </g>
      </g>
    </g>
  </svg>
</template>

<script setup>
import { seededRandom } from '@/composables/motionMath'
import { leavesAlongArc, polarPoint } from '../sceneGeometry'

/**
 * Escena de Hygeia: la copa de Hygeia con la serpiente que bebe de ella, símbolo de
 * la farmacia y de la salud, rodeada de la corona de laurel. De la copa sube una luz
 * tenue. Es el oficio de Hygeia en el producto: velar por el pulso de cada equipo.
 */

const WREATH = { centerX: 0, centerY: 96, radius: 186 }

/**
 * Trazado de un arco de circunferencia.
 *
 * @param {number} from - Ángulo en que empieza, en grados.
 * @param {number} to - Ángulo en que termina, en grados (mayor que `from`).
 * @returns {string} Trazado SVG (`d`) del arco, en sentido horario.
 */
function arc(from, to) {
  const start = polarPoint(WREATH.centerX, WREATH.centerY, WREATH.radius, from)
  const end = polarPoint(WREATH.centerX, WREATH.centerY, WREATH.radius, to)
  return `M${start.x} ${start.y} A${WREATH.radius} ${WREATH.radius} 0 ${to - from > 180 ? 1 : 0} 1 ${end.x} ${end.y}`
}

// Dos ramas que parten de abajo y suben por los lados sin cerrarse arriba.
const ARC_RIGHT = arc(28, 176)
const ARC_LEFT = arc(184, 332)
const LEAVES = [
  ...leavesAlongArc({ ...WREATH, from: 32, to: 168, pairs: 9, length: 28 }),
  ...leavesAlongArc({ ...WREATH, from: 192, to: 328, pairs: 9, length: 28 }),
]

// El cuerpo de la serpiente: sube enroscada al pie de la copa y asoma sobre el borde.
const SNAKE = 'M-60 186 C-8 200 50 192 42 164 C34 138 -34 142 -30 112 C-26 84 40 90 70 44 C98 4 98 -28 78 -52'

const random = seededRandom(909)
const rounded = (value, decimals = 1) => Math.round(value * 10 ** decimals) / 10 ** decimals
const MOTES = Array.from({ length: 14 }, () => ({
  x: Math.round((random() - 0.5) * 140),
  radius: rounded(1.3 + random() * 2.2),
  rise: -Math.round(150 + random() * 150),
  duration: rounded(8 + random() * 7),
  delay: -rounded(random() * 14),
  sway: Math.round((random() - 0.5) * 36),
}))
</script>

<style scoped>
.scene { width: 100%; height: 100%; display: block; }

.cup, .stem, .snake, .scales, .tongue { fill: none; stroke: var(--accent-bright); stroke-linecap: round; stroke-linejoin: round; }
.cup { stroke-width: 2.4; opacity: 0.6; }
.stem { stroke-width: 1.8; opacity: 0.35; }

/* Corona: las hojas respiran, cada par a su ritmo */
.leaf { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.2; opacity: 0.7; transform-box: fill-box; transform-origin: 0% 50%; animation: breathe 6s ease-in-out var(--delay) infinite alternate; }
@keyframes breathe { from { transform: scale(0.94) rotate(-4deg); } to { transform: scale(1.08) rotate(5deg); } }

/* Serpiente: el cuerpo es una cinta que ondula con las escamas corriendo por ella */
.snake { stroke-width: 10; opacity: 0.42; }
.scales { stroke-width: 10; stroke-dasharray: 1.5 13; opacity: 0.9; animation: slither 5s linear infinite; }
@keyframes slither { to { stroke-dashoffset: -110; } }
.head { animation: sip 6s ease-in-out infinite alternate; }
@keyframes sip { from { transform: translate(0, 0) rotate(0); } to { transform: translate(-6px, 5px) rotate(-7deg); } }
.snake-head { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 2; opacity: 0.85; }
.snake-eye { fill: var(--accent-bright); }
.tongue { stroke-width: 1.4; opacity: 0.7; transform-box: fill-box; transform-origin: 100% 50%; animation: flick 3.4s ease-in-out infinite; }
@keyframes flick { 0%, 62%, 100% { transform: scaleX(0.2); opacity: 0; } 70%, 80% { transform: scaleX(1); opacity: 0.8; } 88% { transform: scaleX(0.4); opacity: 0.3; } }

/* La luz de la copa */
.glow { opacity: 0.55; animation: pulse 6.4s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
@keyframes pulse { 0%, 100% { opacity: 0.3; transform: scale(0.94); } 50% { opacity: 0.75; transform: scale(1.06); } }
.mote { fill: var(--accent-bright); opacity: 0; animation: mote var(--duration) ease-out var(--delay) infinite; }
@keyframes mote {
  0%   { transform: translate(0, 0); opacity: 0; }
  14%  { opacity: 0.85; }
  100% { transform: translate(var(--sway), var(--rise)); opacity: 0; }
}
</style>
