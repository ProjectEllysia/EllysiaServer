<template>
  <svg class="scope-motif" :class="[`is-${scope}`, { active }]" viewBox="0 0 220 100" aria-hidden="true" focusable="false">
    <!-- Equipos: retícula de puertos; al trabajar, una columna de luz la barre. -->
    <template v-if="scope === 'hosts'">
      <defs>
        <linearGradient id="motif-sweep" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stop-color="currentColor" stop-opacity="0" />
          <stop offset="1" stop-color="currentColor" stop-opacity="0.55" />
        </linearGradient>
      </defs>
      <g class="lattice">
        <template v-for="row in 4" :key="row">
          <circle v-for="col in 9" :key="col" :cx="14 + (col - 1) * 24" :cy="16 + (row - 1) * 22" r="1.7" />
        </template>
      </g>
      <rect class="sweep" x="-30" y="4" width="30" height="92" fill="url(#motif-sweep)" />
    </template>

    <!-- Nube: estratos ondulados que se desplazan y se elevan al trabajar. -->
    <template v-else-if="scope === 'cloud'">
      <g class="strata">
        <path class="stratum s1" d="M-80 30 q20 -14 40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0" />
        <path class="stratum s2" d="M-80 55 q20 -14 40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0" />
        <path class="stratum s3" d="M-80 80 q20 -14 40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0" />
      </g>
    </template>

    <!-- Red: nodos unidos por enlaces; al trabajar, pulsos recorren los enlaces. -->
    <template v-else>
      <g class="links">
        <path class="link l1" d="M40 30 L100 55" />
        <path class="link l2" d="M100 55 L170 22" />
        <path class="link l3" d="M100 55 L150 84" />
        <path class="link l4" d="M170 22 L205 60" />
        <path class="link l5" d="M150 84 L205 60" />
      </g>
      <g class="nodes">
        <circle cx="40" cy="30" r="3.4" />
        <circle cx="100" cy="55" r="4.2" />
        <circle cx="170" cy="22" r="3.4" />
        <circle cx="150" cy="84" r="3.4" />
        <circle cx="205" cy="60" r="3.4" />
      </g>
    </template>
  </svg>
</template>

<script setup>
/**
 * Dibujo decorativo de una lente de Lybra (equipos, nube o red).
 *
 * Se coloca como primer hijo de la tarjeta de motor, que debe ser
 * `position: relative; isolation: isolate; overflow: hidden`: el dibujo queda
 * detrás del contenido (z-index -1) y se difumina hacia la izquierda para no
 * competir con el texto. Es solo adorno: no recibe foco ni lo lee un lector de
 * pantalla.
 *
 * Args (props):
 *   scope: 'hosts' | 'cloud' | 'network'. Qué dibujo y qué gesto se usan.
 *   active: Si el motor está trabajando en esa lente; anima el dibujo. Por
 *     defecto `false` (el dibujo se queda quieto).
 */
defineProps({
  scope: { type: String, required: true, validator: value => ['hosts', 'cloud', 'network'].includes(value) },
  active: { type: Boolean, default: false },
})
</script>

<style scoped>
.scope-motif {
  position: absolute; top: 0; right: 0; z-index: -1; width: 27rem; height: 12.3rem; pointer-events: none;
  color: var(--scope-tint); opacity: var(--scope-motif-opacity, 0.34);
  -webkit-mask-image: linear-gradient(to left, #000 30%, transparent);
  mask-image: linear-gradient(to left, #000 30%, transparent);
  transition: opacity 0.4s ease;
}
.scope-motif.active { opacity: calc(var(--scope-motif-opacity, 0.32) + 0.2); }

.lattice circle { fill: currentColor; opacity: 0.55; }
.sweep { opacity: 0; }
.active .sweep { opacity: 1; animation: motif-sweep 2.4s ease-in-out infinite; }
@keyframes motif-sweep { from { transform: translateX(0); } to { transform: translateX(260px); } }

.stratum { fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round; }
.s1 { opacity: 0.9; } .s2 { opacity: 0.6; } .s3 { opacity: 0.35; }
.strata { transition: transform 0.6s ease; }
.active .strata { transform: translateY(-6px); }
.active .s1 { animation: motif-drift 9s linear infinite; }
.active .s2 { animation: motif-drift 14s linear infinite reverse; }
.active .s3 { animation: motif-drift 20s linear infinite; }
@keyframes motif-drift { to { transform: translateX(80px); } }

.link { fill: none; stroke: currentColor; stroke-width: 1.2; opacity: 0.4; }
.nodes circle { fill: currentColor; opacity: 0.85; }
.active .link { stroke-dasharray: 5 26; opacity: 0.9; animation: motif-pulse 1.8s linear infinite; }
.active .l2, .active .l3 { animation-delay: 0.45s; }
.active .l4, .active .l5 { animation-delay: 0.9s; }
@keyframes motif-pulse { to { stroke-dashoffset: -62; } }

@media (max-width: 640px) { .scope-motif { width: 17rem; height: 7.7rem; } }
@media (prefers-reduced-motion: reduce) {
  .scope-motif, .strata { transition: none; }
  .active .sweep, .active .s1, .active .s2, .active .s3, .active .link { animation: none; }
  .active .sweep { opacity: 0; }
  .active .link { stroke-dasharray: none; opacity: 0.4; }
}
</style>
