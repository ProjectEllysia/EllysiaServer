<template>
  <svg class="scene" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
    <defs>
      <radialGradient id="acheron-lantern">
        <stop offset="0" stop-color="var(--accent-bright)" stop-opacity="0.7" />
        <stop offset="1" stop-color="var(--accent-bright)" stop-opacity="0" />
      </radialGradient>
      <linearGradient id="acheron-water" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="var(--accent)" stop-opacity="0.16" />
        <stop offset="1" stop-color="var(--accent)" stop-opacity="0.02" />
      </linearGradient>
    </defs>

    <!-- La orilla lejana: cipreses, el árbol de los muertos. -->
    <g class="shore">
      <path d="M0 468 C120 456 260 462 400 468" class="line" opacity="0.35" fill="none" />
      <g v-for="(tree, index) in TREES" :key="`tree-${index}`" :transform="`translate(${tree.x} 464) scale(${tree.scale})`">
        <path class="tree" d="M0 0 C-11 -34 -9 -86 0 -128 C9 -86 11 -34 0 0 Z" :style="{ '--delay': `${tree.delay}s` }" />
      </g>
    </g>

    <!-- El río: corrientes que avanzan a distinta velocidad y en sentidos opuestos. -->
    <g v-for="(layer, index) in STREAMS" :key="`stream-${index}`" class="stream" :class="{ 'stream--right': layer.direction > 0 }" :style="{ '--duration': `${layer.duration}s` }">
      <path :d="`${layer.line} L2400 600 L0 600 Z`" fill="url(#acheron-water)" />
      <path :d="layer.line" class="line" fill="none" :opacity="layer.opacity" :stroke-width="layer.width" />
    </g>

    <!-- Las almas: luces que suben despacio de las aguas. -->
    <g v-for="(soul, index) in SOULS" :key="`soul-${index}`" :transform="`translate(${soul.x} ${soul.y})`">
      <path
        class="soul"
        d="M0 0 C7 -9 7 -21 0 -34 C-7 -21 -7 -9 0 0 Z"
        :style="{ '--rise': `${soul.rise}px`, '--duration': `${soul.duration}s`, '--delay': `${soul.delay}s` }"
      />
    </g>

    <!-- Los óbolos: la moneda con que se paga el paso. Caen al río y dejan un círculo en el agua. -->
    <g v-for="(coin, index) in COINS" :key="`coin-${index}`" :transform="`translate(${coin.x} ${coin.top})`" :style="{ '--duration': `${coin.duration}s`, '--delay': `${coin.delay}s`, '--fall': `${coin.fall}px` }">
      <g class="coin-lane">
        <g class="coin">
          <circle r="9" class="coin-face" />
          <circle r="5.2" class="line" fill="none" stroke-width="1" />
          <path d="M-2.6 0 H2.6 M0 -2.6 V2.6" class="line" stroke-width="1" />
        </g>
      </g>
      <ellipse class="splash" cx="0" :cy="coin.fall" rx="26" ry="5" />
    </g>

    <!-- Caronte y su barca. -->
    <g transform="translate(900 470)">
      <g class="drift">
        <g class="bob">
          <ellipse class="glow" cx="118" cy="-68" rx="70" ry="70" fill="url(#acheron-lantern)" />
          <path class="pole" d="M-72 -152 L96 38" />
          <path class="hull" d="M-120 -4 C-100 24 -50 38 10 38 C70 38 124 20 152 -40 C122 -12 70 6 10 6 C-44 6 -86 0 -120 -4 Z" />
          <path class="line" d="M152 -40 C162 -54 150 -66 140 -60" fill="none" />
          <path class="cloak" d="M-46 6 C-44 -30 -38 -70 -30 -90 C-24 -104 -4 -104 2 -90 C10 -70 16 -30 20 6 Z" />
          <circle class="eye" cx="-17" cy="-86" r="1.6" />
          <circle class="eye" cx="-7" cy="-86" r="1.6" />
          <path class="line" d="M128 -38 L128 -92 L110 -92" fill="none" />
          <rect class="lantern" x="102" y="-84" width="14" height="20" rx="3" />
        </g>
        <path class="reflection" d="M96 52 h44 M104 62 h28 M110 72 h16" />
      </g>
    </g>
  </svg>
</template>

<script setup>
import { seededRandom } from '@/composables/motionMath'
import { wavePath } from '../sceneGeometry'

/**
 * Escena de Acheron: Caronte cruza el río del inframundo en su barca, con un farol
 * por único guía. Las almas suben de las aguas, los cipreses marcan la orilla de
 * los muertos y las monedas que caen son el óbolo con que se paga el paso: lo que
 * se entrega a la custodia de Acheron no se pierde, cambia de orilla.
 */

const STREAM_WIDTH = 2400
const STREAMS = [
  { y: 478, amplitude: 9, wavelength: 600, duration: 70, direction: -1, opacity: 0.32, width: 1.3 },
  { y: 508, amplitude: 14, wavelength: 400, duration: 48, direction: 1, opacity: 0.26, width: 1.5 },
  { y: 544, amplitude: 19, wavelength: 600, duration: 34, direction: -1, opacity: 0.22, width: 1.7 },
  { y: 584, amplitude: 22, wavelength: 400, duration: 26, direction: 1, opacity: 0.18, width: 1.9 },
].map((stream) => ({ ...stream, line: wavePath(stream.y, stream.amplitude, stream.wavelength, STREAM_WIDTH) }))

const TREES = [
  { x: 30, scale: 0.8, delay: 0 }, { x: 78, scale: 1.1, delay: -1.4 }, { x: 128, scale: 0.9, delay: -2.6 },
  { x: 188, scale: 1.25, delay: -0.8 }, { x: 252, scale: 0.85, delay: -3.2 }, { x: 318, scale: 1, delay: -2 },
]

const random = seededRandom(404)
const rounded = (value, decimals = 1) => Math.round(value * 10 ** decimals) / 10 ** decimals
const SOULS = Array.from({ length: 9 }, () => ({
  x: Math.round(420 + random() * 700),
  y: Math.round(500 + random() * 80),
  rise: -Math.round(150 + random() * 170),
  duration: rounded(11 + random() * 9),
  delay: -rounded(random() * 18),
}))
const COINS = [
  { x: 210, top: 60, fall: 410, duration: 15, delay: -3 },
  { x: 470, top: 20, fall: 450, duration: 19, delay: -11 },
  { x: 1010, top: 90, fall: 380, duration: 17, delay: -7 },
]
</script>

<style scoped>
.scene { width: 100%; height: 100%; display: block; }

.line, .hull, .cloak, .lantern, .tree, .coin-face, .pole { stroke: var(--accent-bright); fill: none; stroke-linecap: round; stroke-linejoin: round; }

/* Cipreses */
.tree { fill: var(--accent-dim); stroke-width: 1.2; opacity: 0.55; transform-box: fill-box; transform-origin: 50% 100%; animation: sway 7s ease-in-out var(--delay) infinite alternate; }
@keyframes sway { from { transform: rotate(-1.2deg); } to { transform: rotate(1.2deg); } }

/* Corrientes */
.stream { animation: stream-left var(--duration) linear infinite; }
.stream--right { animation-name: stream-right; }
@keyframes stream-left  { from { transform: translateX(0); }       to { transform: translateX(-1200px); } }
@keyframes stream-right { from { transform: translateX(-1200px); } to { transform: translateX(0); } }

/* Almas */
.soul { fill: var(--accent-bright); opacity: 0; transform-box: fill-box; animation: soul-rise var(--duration) ease-out var(--delay) infinite; }
@keyframes soul-rise {
  0%   { transform: translate(0, 0) scaleY(0.6); opacity: 0; }
  14%  { opacity: 0.6; transform: translate(0, calc(var(--rise) * 0.1)) scaleY(1); }
  60%  { opacity: 0.35; transform: translate(10px, calc(var(--rise) * 0.6)) scaleY(1.1); }
  100% { transform: translate(-6px, var(--rise)) scaleY(1.2); opacity: 0; }
}

/* Óbolos: caen, giran sobre su canto y se hunden dejando un círculo en el agua */
.coin-lane { animation: coin-fade var(--duration) linear var(--delay) infinite; }
@keyframes coin-fade {
  0%        { opacity: 0; }
  6%, 88%   { opacity: 1; }
  92%, 100% { opacity: 0; }
}
.coin { animation: coin-drop var(--duration) cubic-bezier(0.45, 0, 0.9, 0.6) var(--delay) infinite; }
@keyframes coin-drop {
  0%   { transform: translateY(0) scaleX(1); }
  88%  { transform: translateY(var(--fall)) scaleX(-1); }
  100% { transform: translateY(var(--fall)) scaleX(-1); }
}
.coin-face { fill: var(--mote); stroke-width: 1.4; }
.splash { fill: none; stroke: var(--accent-bright); stroke-width: 1.2; opacity: 0; transform-box: fill-box; transform-origin: center; animation: splash var(--duration) ease-out var(--delay) infinite; }
@keyframes splash {
  0%, 86% { opacity: 0; transform: scale(0.1); }
  88%     { opacity: 0.7; transform: scale(0.2); }
  100%    { opacity: 0; transform: scale(1); }
}

/* Barca */
.drift { animation: drift 42s ease-in-out infinite alternate; }
@keyframes drift { from { transform: translateX(-70px); } to { transform: translateX(40px); } }
.bob { transform-origin: 0 20px; animation: bob 5.2s ease-in-out infinite alternate; }
@keyframes bob { from { transform: translateY(0) rotate(-1deg); } to { transform: translateY(5px) rotate(1.2deg); } }
.hull { fill: var(--accent-dim); stroke-width: 1.7; }
.cloak { fill: var(--bg); stroke-width: 1.5; }
.lantern { fill: var(--accent-dim); stroke-width: 1.4; }
.eye { fill: var(--accent-bright); animation: gaze 6s ease-in-out infinite; }
@keyframes gaze { 0%, 90%, 100% { opacity: 0.9; } 94% { opacity: 0.1; } }
.glow { animation: flicker 3.4s ease-in-out infinite; }
@keyframes flicker { 0%, 100% { opacity: 0.55; } 30% { opacity: 0.9; } 55% { opacity: 0.65; } 80% { opacity: 0.95; } }
.pole { stroke-width: 2.4; transform-origin: 4px -66px; animation: punt 7s ease-in-out infinite alternate; }
@keyframes punt { from { transform: rotate(-4deg); } to { transform: rotate(5deg); } }
.reflection { fill: none; stroke: var(--accent-bright); stroke-width: 1.4; stroke-linecap: round; animation: shimmer 3.2s ease-in-out infinite; }
@keyframes shimmer { 0%, 100% { opacity: 0.15; } 50% { opacity: 0.6; } }
</style>
