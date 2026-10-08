<template>
  <svg class="tool-glyph" :data-live="live" :style="{ width: `${size}px`, height: `${size}px` }" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
    <!-- El medallón: una moneda antigua con su orla de perlas. -->
    <circle class="coin-disc" cx="50" cy="50" r="47" />
    <circle class="coin-rim" cx="50" cy="50" r="47" />
    <circle class="coin-beads" cx="50" cy="50" r="41.5" />
    <circle class="coin-inner" cx="50" cy="50" r="35" />

    <g transform="translate(18 18)" class="engraving">
      <!-- Generador de contraseñas: una llave. -->
      <template v-if="toolId === 'passwordGenerator'">
        <circle class="draw" pathLength="1" cx="20" cy="32" r="10" />
        <circle cx="20" cy="32" r="3.4" class="fine" />
        <path class="draw" pathLength="1" d="M30 32 H56" />
        <path class="tooth a-tooth" style="--i: 0" d="M40 32 V38" />
        <path class="tooth a-tooth" style="--i: 1" d="M46 32 V43" />
        <path class="tooth a-tooth" style="--i: 2" d="M52 32 V39" />
        <path class="spark a-spark" style="--i: 0" d="M10 12 V18 M7 15 H13" />
        <path class="spark a-spark" style="--i: 1" d="M54 14 V19 M51.5 16.5 H56.5" />
        <path class="spark a-spark" style="--i: 2" d="M44 52 V56 M42 54 H46" />
      </template>

      <!-- Medidor de contraseñas: cinco barras que se levantan. -->
      <template v-else-if="toolId === 'passwordStrength'">
        <path class="draw" pathLength="1" d="M6 54 H58" />
        <rect v-for="(height, index) in [10, 17, 24, 31, 38]" :key="index" class="bar a-bar" :style="{ '--i': index }" :x="10 + index * 10" :y="52 - height" width="6.5" :height="height" rx="1.5" />
      </template>

      <!-- Consulta de CVE: una lupa que rastrea las líneas. -->
      <template v-else-if="toolId === 'cveLookup'">
        <path class="fine" d="M8 14 H30 M8 20 H24 M8 48 H26 M8 54 H20" />
        <g class="a-lens">
          <circle class="draw" pathLength="1" cx="28" cy="29" r="15" />
          <path class="draw" pathLength="1" d="M39 40 L55 56" />
          <path class="fine" d="M20 29 H36 M28 21 V37" />
          <circle class="dot a-dot" cx="28" cy="29" r="2.8" />
        </g>
      </template>

      <!-- Calculadora CVSS: un cuadrante con su aguja. -->
      <template v-else-if="toolId === 'cvssCalculator'">
        <path class="draw" pathLength="1" d="M8 46 A24 24 0 0 1 56 46" />
        <path class="fine" d="M17.3 37.5 L13.8 35.5 M23.5 31.3 L21.5 27.8 M32 29 V25 M40.5 31.3 L42.5 27.8 M46.7 37.5 L50.2 35.5" />
        <path class="needle a-needle" d="M32 46 L32 27" />
        <circle class="dot" cx="32" cy="46" r="3.4" />
        <path class="draw" pathLength="1" d="M10 54 H54" />
      </template>

      <!-- Quiz de phishing: el anzuelo y la carta. -->
      <template v-else-if="toolId === 'phishingQuiz'">
        <rect class="draw" pathLength="1" x="6" y="28" width="34" height="24" rx="3" />
        <path class="draw" pathLength="1" d="M6 28 L23 41 L40 28" />
        <g class="a-hook">
          <path class="draw" pathLength="1" d="M50 4 V30 C50 41 39 42 39 34" />
          <circle class="dot" cx="39" cy="33" r="2" />
        </g>
      </template>

      <!-- Calculadora de rangos de red: los bits, de red y de equipo. -->
      <template v-else-if="toolId === 'cidrCalculator'">
        <rect
          v-for="index in 8"
          :key="index"
          class="cell"
          :class="index <= 5 ? 'cell--net a-cell' : ''"
          :style="{ '--i': index }"
          :x="3 + (index - 1) * 7.4"
          y="22"
          width="5.4"
          height="12"
          rx="1.2"
        />
        <path class="draw" pathLength="1" d="M3 42 H40 M43 42 H60" />
        <path class="fine" d="M3 48 V42 M40 48 V42 M43 48 V42 M60 48 V42" />
      </template>

      <!-- Comprobador SPF, DKIM y DMARC: la carta con el escudo y su sello. -->
      <template v-else-if="toolId === 'mailAuthChecker'">
        <rect class="draw" pathLength="1" x="4" y="12" width="40" height="28" rx="3" />
        <path class="draw" pathLength="1" d="M4 12 L24 28 L44 12" />
        <path class="shield draw" pathLength="1" d="M46 30 L58 34 V44 C58 51 52 55 46 58 C40 55 34 51 34 44 V34 Z" />
        <path class="check a-check" pathLength="1" d="M40.5 44 L45 48.5 L52 40" />
      </template>

      <!-- Calculadora de consumo: el rayo. -->
      <template v-else-if="toolId === 'powerCost'">
        <circle class="fine a-ring" cx="32" cy="32" r="26" />
        <g class="a-bolt"><path class="bolt draw" pathLength="1" d="M37 5 L15 36 H30 L26 59 L50 25 H35 Z" /></g>
      </template>
    </g>
  </svg>
</template>

<script setup>
/**
 * Grabado de una herramienta gratuita sobre un medallón, como una moneda antigua.
 *
 * Una pieza para todas las herramientas: el medallón es común y el grabado cambia
 * según `toolId`. Se usa en las tarjetas del hub y en la cabecera de cada página de
 * herramienta, así que quien ve la tarjeta reconoce la herramienta al abrirla.
 *
 * Se mueve de dos formas: al dibujarse (los trazos con clase `draw` se trazan al
 * aparecer, ver `motion.css`) y en vivo, cuando el medallón está dentro de algo con
 * la clase `glyph-host` que recibe el ratón o el foco, o cuando se le pasa `live`.
 * En reposo el grabado está quieto y completo.
 */
defineProps({
  /** Herramienta cuyo grabado se pinta (`id` del catálogo en `freeTools/catalog.js`). */
  toolId: { type: String, required: true },
  /** Lado del medallón en píxeles. */
  size: { type: Number, default: 64 },
  /** Si el grabado se mueve siempre, sin esperar al ratón ni al foco. */
  live: { type: Boolean, default: false },
})
</script>

<style scoped>
.tool-glyph { display: block; overflow: visible; color: var(--accent-bright); }

/* ── Medallón ── */
.coin-disc { fill: var(--surface); }
.coin-rim { fill: none; stroke: var(--accent); stroke-width: 1.6; opacity: 0.9; }
.coin-beads { fill: none; stroke: var(--accent); stroke-width: 2.2; stroke-linecap: round; stroke-dasharray: 0.1 5.1; opacity: 0.55; transform-box: fill-box; transform-origin: center; animation: coin-turn 40s linear infinite paused; }
.coin-inner { fill: var(--accent-dim); stroke: var(--accent); stroke-width: 0.6; opacity: 0.8; }
@keyframes coin-turn { to { transform: rotate(360deg); } }

/* ── Grabado ── */
.engraving :is(path, circle, rect) { fill: none; stroke: var(--accent-bright); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.engraving .fine { stroke-width: 1.3; opacity: 0.55; }
.engraving .dot { fill: var(--accent-bright); stroke: none; }
.engraving .bar, .engraving .cell--net, .engraving .bolt, .engraving .shield { fill: var(--accent-dim); }
.engraving .cell { stroke-width: 1.4; }
.engraving .cell--net { fill: var(--accent); fill-opacity: 0.6; }
.engraving .spark, .engraving .tooth { stroke-width: 1.8; }
.engraving .needle { stroke-width: 2.4; }
.engraving .check { stroke-width: 2.4; }

/* ── Movimiento en vivo: las animaciones esperan en su primer fotograma, que es el reposo ── */
/* El trazado inicial (.draw) no espera: solo lo hacen los movimientos en vivo. */
.engraving *:not(.draw) { animation-play-state: paused; }
.tool-glyph[data-live="true"] *,
:global(.glyph-host:hover) .tool-glyph *,
:global(.glyph-host:focus-within) .tool-glyph * { animation-play-state: running; }

.a-tooth { transform-box: fill-box; transform-origin: 50% 0; animation: tooth 1.6s ease-in-out calc(var(--i) * 0.25s) infinite; }
@keyframes tooth { 0%, 100% { transform: scaleY(1); } 45% { transform: scaleY(0.5); } }
.a-spark { transform-box: fill-box; transform-origin: center; animation: spark 1.8s ease-in-out calc(var(--i) * 0.4s) infinite; }
@keyframes spark { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(0.4); opacity: 0.3; } }

.a-bar { transform-box: fill-box; transform-origin: 50% 100%; animation: bar 2s ease-in-out calc(var(--i) * 0.14s) infinite; }
@keyframes bar { 0%, 100% { transform: scaleY(1); } 40% { transform: scaleY(0.3); } }

.a-lens { animation: scan 3.2s ease-in-out infinite; }
@keyframes scan { 0%, 100% { transform: translate(0, 0); } 25% { transform: translate(5px, -3px); } 55% { transform: translate(-3px, 4px); } 80% { transform: translate(4px, 3px); } }
.a-dot { transform-box: fill-box; transform-origin: center; animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.7); } }

.a-needle { transform-origin: 32px 46px; transform: rotate(-52deg); animation: needle 3s ease-in-out infinite; }
@keyframes needle { 0%, 100% { transform: rotate(-52deg); } 45% { transform: rotate(58deg); } 70% { transform: rotate(22deg); } }

.a-hook { transform-origin: 50px 4px; animation: pendulum 2.6s ease-in-out infinite; }
@keyframes pendulum { 0%, 100% { transform: rotate(-8deg); } 50% { transform: rotate(9deg); } }

.a-cell { animation: bit 1.8s ease-in-out calc(var(--i) * 0.12s) infinite; }
@keyframes bit { 0%, 100% { fill-opacity: 0.6; } 40% { fill-opacity: 0.12; } }

.a-check { stroke-dasharray: 1; stroke-dashoffset: 0; animation: stamp 2.4s ease-in-out infinite; }
@keyframes stamp { 0%, 100% { stroke-dashoffset: 0; } 30% { stroke-dashoffset: 1; } 55% { stroke-dashoffset: 0; } }

.a-bolt { animation: zap 1.4s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
@keyframes zap { 0%, 100% { transform: scale(1); filter: drop-shadow(0 0 0 transparent); } 50% { transform: scale(1.07); filter: drop-shadow(0 0 5px var(--accent-bright)); } }
.a-ring { transform-box: fill-box; transform-origin: center; animation: ripple 1.8s ease-out infinite; }
@keyframes ripple { 0% { transform: scale(0.8); opacity: 0.6; } 100% { transform: scale(1.18); opacity: 0; } }
</style>
