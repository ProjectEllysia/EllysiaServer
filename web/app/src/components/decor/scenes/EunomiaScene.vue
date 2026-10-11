<template>
  <div class="scene">
    <svg class="layer" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <!-- ── La regla: una marca por requisito evaluable de cada marco, una mayor cada diez ── -->
      <g class="ruler">
        <path class="rule" :d="PATHS.rules" />
        <path class="tick" :d="PATHS.minor" />
        <path class="tick tick--major" :d="PATHS.major" />
      </g>

      <!-- ── Las correspondencias: un arco por cada una, más firme si cumplir un requisito cubre al otro ── -->
      <g class="arcs">
        <path
          v-for="(arc, index) in ARCS"
          :key="index"
          class="arc"
          :class="arc.isFull ? 'arc--full' : 'arc--partial'"
          :d="arc.path"
          pathLength="1"
          :style="{ '--delay': `${arc.delay}s` }"
        />
      </g>

      <g class="labels">
        <text v-for="label in LABELS" :key="label.key" class="framework-name" :x="label.x" :y="NAME_Y" text-anchor="middle">{{ label.name }}</text>
        <text v-for="label in LABELS" :key="`count-${label.key}`" class="framework-count" :x="label.x" :y="COUNT_Y" text-anchor="middle">{{ label.count }}</text>
      </g>
    </svg>

    <!-- Una evidencia recorre las correspondencias de vez en cuando. Va en su propia capa: al
         moverse repinta solo esa capa, no los casi doscientos arcos del grabado. -->
    <svg class="layer layer--moving" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <g v-for="(fan, index) in FANS" :key="index" :style="{ '--fan-delay': `${fan.delay}s` }">
        <path class="mark mark--source" :d="fan.source" />
        <template v-for="target in fan.targets" :key="target.framework">
          <circle class="light light--halo" r="8" :style="{ offsetPath: `path('${target.path}')` }" />
          <circle class="light" r="2.4" :style="{ offsetPath: `path('${target.path}')` }" />
          <path class="mark mark--target" :d="target.mark" />
        </template>
      </g>
    </svg>
  </div>
</template>

<script setup>
import data from '../concordance.json'
import { arcBetween, arcList, diamondPath, fanOf, fanSources, layoutRuler, rulerPaths, tickX } from '../concordance'

/**
 * Escena de Eunomia: una lámina de concordancias. Una regla lleva una marca por cada
 * requisito evaluable de los cuatro marcos del catálogo (ISO 27001, NIS2, ENS y RGPD), y
 * sobre ella un arco por cada correspondencia entre requisitos de marcos distintos. Es lo
 * que hace Eunomia con una evidencia: una sola prueba cubre varios requisitos a la vez, y
 * lo que se cumple en un marco cuenta en los demás.
 *
 * Todo sale del catálogo (`concordance.json`, atado a él por un test de la API) y de la
 * geometría de `concordance.js`; nada está dibujado a mano. Los marcos van en el orden que
 * deja contiguos los dos cruces más cargados, con NIS2 de pivote.
 *
 * Al aparecer, la regla se asienta y los arcos se trazan de izquierda a derecha. Luego una
 * evidencia sale de un requisito de NIS2 y llega, por sus correspondencias reales, a un
 * requisito de cada otro marco, que se enciende un rato: es lo único que se mueve sin
 * parar, y va en su propia capa para no obligar a repintar el grabado en cada fotograma.
 */

const round = (value) => Math.round(value * 10) / 10

const BASELINE = 430
const FLATTEN = 0.5
/** Los rombos van bajo la regla, apuntando a su marca, fuera de la maraña de arcos. */
const MARK_Y = BASELINE + 10
const NAME_Y = BASELINE + 34
const COUNT_Y = BASELINE + 50

const RULER = layoutRuler(data)
const PATHS = rulerPaths(RULER, BASELINE)
const SPAN = { from: RULER.segments[data.order[0]].x0, to: RULER.segments[data.order.at(-1)].x1 }

/** Los arcos entran de izquierda a derecha: el retraso crece con la posición de su pie izquierdo. */
const ARCS = arcList(data, RULER, BASELINE, FLATTEN).map((arc) => ({
  ...arc,
  delay: round(0.7 + ((arc.footX - SPAN.from) / (SPAN.to - SPAN.from)) * 2.4),
}))

const LABELS = data.order.map((key) => {
  const { x0, x1 } = RULER.segments[key]
  return { key, name: data.frameworks[key].label, count: data.frameworks[key].count, x: round((x0 + x1) / 2) }
})

/**
 * Dos abanicos desfasados medio ciclo. Cada uno parte de un requisito de NIS2 (el marco con
 * más cruces) que llega de verdad a los otros tres, y sus luces siguen los mismos arcos que
 * el grabado ya trae.
 */
const FANS = fanSources(data, 'nis2', 2).map((source, index) => {
  const fromX = tickX(RULER, source.framework, source.index)
  return {
    delay: index * 7,
    source: diamondPath(fromX, MARK_Y, 5),
    targets: fanOf(data, source).map((target) => {
      const toX = tickX(RULER, target.framework, target.index)
      return {
        framework: target.framework,
        path: arcBetween(fromX, toX, BASELINE, FLATTEN),
        mark: diamondPath(toX, MARK_Y, 4),
      }
    }),
  }
})
</script>

<style scoped>
.scene { position: relative; width: 100%; height: 100%; }
/* Las capas se apilan con el mismo viewBox, así que coinciden punto a punto. */
.layer { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.layer--moving { will-change: transform; }

/* Los trazos finos nunca bajan de un píxel real de la pantalla (`--device-pixel`, ver
   `ModuleAtmosphere`): por debajo se ven grises y borrosos en una pantalla normal. */
.rule, .tick { fill: none; stroke: var(--accent); }
.rule { stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.6; }
.tick { stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.5; }
.tick--major { stroke: var(--accent-bright); stroke-width: max(0.9px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.8; }
.ruler { animation: fade 1.6s ease 0.2s backwards; }

/* ── Arcos: se trazan de izquierda a derecha, uno tras otro ── */
.arc { fill: none; stroke-linecap: round; animation: draw 1.7s cubic-bezier(0.3, 0.1, 0.2, 1) var(--delay) backwards; }
.arc--full { stroke: var(--accent-bright); stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.55; }
.arc--partial { stroke: var(--accent); stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.3; }

/* ── Rótulos: versalitas espaciadas para el marco, mono para su recuento ── */
.labels { animation: fade 1.8s ease 3s backwards; }
.framework-name { font-family: var(--font-epic); font-size: 0.72em; letter-spacing: 0.3em; fill: var(--accent-bright); opacity: 0.6; }
.framework-count { font-family: var(--font-mono); font-size: 0.66em; letter-spacing: 0.06em; fill: var(--accent); opacity: 0.5; }

/* ── Evidencia: la luz sale del requisito de origen y, al llegar, se encienden los destinos.
   El resplandor es un círculo tenue que viaja con ella, no un filtro: un filtro en movimiento
   se recalcula en cada fotograma. Todo nace invisible: con movimiento reducido no se ve. ── */
.light { fill: var(--accent-bright); offset-rotate: 0deg; opacity: 0; animation: travel 14s ease-in-out calc(5.2s + var(--fan-delay)) infinite; }
.light--halo { fill-opacity: 0.22; }
.mark { fill: var(--accent-bright); opacity: 0; }
.mark--source { animation: strike 14s ease calc(5.2s + var(--fan-delay)) infinite; }
.mark--target { animation: close 14s ease calc(5.2s + var(--fan-delay)) infinite; }

/* El guion solo dura lo que dura el trazado: en reposo el trazo queda liso y no se recalcula en cada repintado. */
@keyframes draw { from { stroke-dasharray: 1; stroke-dashoffset: 1; } to { stroke-dasharray: 1; stroke-dashoffset: 0; } }
@keyframes fade { from { opacity: 0; } }
@keyframes travel {
  0%, 5% { offset-distance: 0%; opacity: 0; }
  9% { opacity: 1; }
  40% { offset-distance: 100%; opacity: 1; }
  44%, 100% { offset-distance: 100%; opacity: 0; }
}
@keyframes strike { 0% { opacity: 0; } 4% { opacity: 1; } 30% { opacity: 0.7; } 44%, 100% { opacity: 0; } }
@keyframes close { 0%, 38% { opacity: 0; } 44% { opacity: 1; } 70% { opacity: 0.85; } 90%, 100% { opacity: 0; } }
</style>
