<template>
  <svg class="scene" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
    <!-- El arco: Iris, la mensajera, tiende el puente entre los dioses y los hombres. -->
    <g class="rainbow">
      <circle
        v-for="band in BANDS"
        :key="`band-${band.index}`"
        class="band"
        cx="600"
        cy="650"
        :r="band.radius"
        :stroke="band.color"
        :style="{ '--delay': `${band.index * 0.42}s` }"
      />
    </g>

    <!-- Plumas de sus alas, que caen despacio. -->
    <g v-for="(feather, index) in FEATHERS" :key="`feather-${index}`" :transform="`translate(${feather.x} ${feather.y})`">
      <g class="fall" :style="{ '--duration': `${feather.duration}s`, '--delay': `${feather.delay}s`, '--drop': `${feather.drop}px`, '--drift': `${feather.drift}px` }">
        <g class="flutter" :style="{ '--duration': `${feather.flutter}s`, '--swing': `${feather.swing}deg` }">
          <g :transform="`scale(${feather.scale})`">
            <path class="feather" d="M0 0 C-9 -14 -9 -34 0 -54 C9 -34 9 -14 0 0 Z" />
            <path class="quill" d="M0 8 V-48 M0 -14 L-6 -22 M0 -14 L6 -22 M0 -28 L-5 -35 M0 -28 L5 -35" />
          </g>
        </g>
      </g>
    </g>

    <!-- Cartas con alas, que recorren el arco llevando mensajes. -->
    <g v-for="(letter, index) in LETTERS" :key="`letter-${index}`" class="orbit" :style="{ '--duration': `${letter.duration}s`, '--delay': `${letter.delay}s` }">
      <g :transform="`translate(600 ${650 - letter.radius})`">
        <g transform="translate(-13 0)"><g class="wing wing--left"><path d="M0 0 C-14 -14 -32 -14 -44 -6 C-32 -4 -22 0 -12 8 Z" /></g></g>
        <g transform="translate(13 0)"><g class="wing wing--right"><path d="M0 0 C14 -14 32 -14 44 -6 C32 -4 22 0 12 8 Z" /></g></g>
        <rect class="envelope" x="-14" y="-10" width="28" height="20" rx="3" />
        <path class="envelope" d="M-14 -10 L0 3 L14 -10" />
      </g>
    </g>
  </svg>
</template>

<script setup>
import { seededRandom } from '@/composables/motionMath'

/**
 * Escena de Iris: el arcoíris que la diosa tiende como puente, las plumas que caen
 * de sus alas doradas y las cartas con alas que la mensajera de los dioses lleva de
 * un lado al otro. Es el oficio de Iris en el producto: llevar un mensaje y decir
 * de quién es de verdad.
 */

/** Los siete arcos, de fuera adentro, con colores suaves para que no pesen. */
const RAINBOW = ['#e0574f', '#e8924f', '#e6c453', '#78c079', '#5aa8d6', '#6a78d6', '#a56bc9']
const BANDS = RAINBOW.map((color, index) => ({ index, color, radius: 560 - index * 24 }))

const random = seededRandom(303)
const rounded = (value, decimals = 1) => Math.round(value * 10 ** decimals) / 10 ** decimals

const FEATHERS = Array.from({ length: 11 }, (_, index) => ({
  x: Math.round(40 + (index / 10) * 1120 + (random() - 0.5) * 60),
  y: Math.round(-70 - random() * 40),
  scale: rounded(0.8 + random() * 0.7, 2),
  duration: rounded(20 + random() * 14),
  delay: -rounded(random() * 30),
  drop: Math.round(700 + random() * 80),
  drift: Math.round((random() - 0.5) * 140),
  flutter: rounded(3.2 + random() * 2.4),
  swing: Math.round(18 + random() * 20),
}))

const LETTERS = [
  { radius: 548, duration: 30, delay: -4 },
  { radius: 500, duration: 38, delay: -19 },
  { radius: 452, duration: 34, delay: -27 },
]
</script>

<style scoped>
.scene { width: 100%; height: 100%; display: block; }

/* Arcoíris: cada banda se ilumina un instante, de fuera adentro, como una ola de luz */
.band { fill: none; stroke-width: 20; opacity: 0.16; animation: shimmer 9s ease-in-out var(--delay) infinite; }
@keyframes shimmer { 0%, 100% { opacity: 0.12; } 12% { opacity: 0.62; } 30% { opacity: 0.16; } }

/* Plumas: caen, se mecen sobre su punta y se desvanecen */
.fall { animation: fall var(--duration) linear var(--delay) infinite; }
@keyframes fall {
  0%   { transform: translate(0, 0); opacity: 0; }
  8%   { opacity: 0.8; }
  85%  { opacity: 0.6; }
  100% { transform: translate(var(--drift), var(--drop)); opacity: 0; }
}
.flutter { animation: flutter var(--duration) ease-in-out infinite alternate; }
@keyframes flutter { from { transform: rotate(calc(var(--swing) * -1)); } to { transform: rotate(var(--swing)); } }
.feather { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.4; stroke-linejoin: round; }
.quill { fill: none; stroke: var(--accent-bright); stroke-width: 1; stroke-linecap: round; opacity: 0.7; }

/* Cartas con alas: giran en torno al centro del arco y las alas baten */
.orbit { transform-origin: 600px 650px; opacity: 0; animation: orbit var(--duration) linear var(--delay) infinite; }
@keyframes orbit {
  0%   { transform: rotate(-96deg); opacity: 0; }
  7%   { opacity: 0.95; }
  93%  { opacity: 0.95; }
  100% { transform: rotate(96deg); opacity: 0; }
}
.envelope { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.6; stroke-linejoin: round; stroke-linecap: round; }
path.envelope { fill: none; }
.wing path { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: 1.3; stroke-linejoin: round; }
.wing { animation: flap 0.9s ease-in-out infinite alternate; }
.wing--left { transform-origin: 0 0; }
.wing--right { transform-origin: 0 0; animation-name: flap-mirror; }
@keyframes flap { from { transform: rotate(10deg); } to { transform: rotate(-26deg); } }
@keyframes flap-mirror { from { transform: rotate(-10deg); } to { transform: rotate(26deg); } }
</style>
