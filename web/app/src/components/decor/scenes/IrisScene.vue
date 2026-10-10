<template>
  <div class="scene">
    <svg class="layer" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <defs>
        <!-- Bajo el arco primario el cielo es más claro: ahí cae la luz que las gotas devuelven -->
        <radialGradient :id="ids.glow" gradientUnits="userSpaceOnUse" :cx="CENTER.x" :cy="CENTER.y" :r="BOWS.primaryInner">
          <stop offset="0.72" class="glow-stop" stop-opacity="0" />
          <stop offset="1" class="glow-stop" stop-opacity="0.05" />
        </radialGradient>
      </defs>

      <circle class="sky-glow" :cx="CENTER.x" :cy="CENTER.y" :r="BOWS.primaryInner" :fill="`url(#${ids.glow})`" />

      <!-- ── El arcoíris: un trazo fino por color, a su radio real ── -->
      <g class="bow bow--secondary">
        <path v-for="(arc, index) in BOWS.secondary" :key="`secondary-${arc.nm}`" :d="arc.path" :stroke="arc.color" pathLength="1" :style="{ '--delay': `${1 + index * 0.025}s` }" />
      </g>
      <g class="bow bow--primary">
        <path v-for="(arc, index) in BOWS.primary" :key="`primary-${arc.nm}`" :d="arc.path" :stroke="arc.color" pathLength="1" :style="{ '--delay': `${0.3 + index * 0.02}s` }" />
      </g>
    </svg>

    <!-- Un brillo recorre el arco despacio. Va en su propia capa: al moverse repinta solo esa
         capa, no los arcos ni la lupa. La medida y la lupa van en otra por encima: el brillo pasa por debajo. -->
    <svg class="layer layer--moving" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <defs>
        <radialGradient :id="ids.glint">
          <stop offset="0" class="glow-stop" stop-opacity="0.6" />
          <stop offset="1" class="glow-stop" stop-opacity="0" />
        </radialGradient>
      </defs>
      <circle class="glint" r="16" :fill="`url(#${ids.glint})`" :style="{ offsetPath: `path('${BOWS.glint}')` }" />
    </svg>

    <svg class="layer" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <defs>
        <clipPath :id="ids.lens"><circle :cx="LOUPE.x" :cy="LOUPE.y" :r="LOUPE.radius" /></clipPath>
      </defs>

      <!-- ── La medida, a la izquierda: el ángulo de cada arco visto desde el punto opuesto al Sol ── -->
      <g class="reading">
        <path class="guide" :d="READING.guide" />
        <path v-for="tick in READING.ticks" :key="tick.label" class="tick" :d="tick.path" />
        <text v-for="tick in READING.ticks" :key="`label-${tick.label}`" class="angle-label" :x="tick.labelX" :y="tick.labelY">{{ tick.label }}</text>
        <text class="band-name" :x="READING.band.x" :y="READING.band.y">{{ READING.band.text }}</text>
      </g>

      <!-- ── La lupa, a la derecha: el mismo arco visto de cerca, con las líneas de Fraunhofer ── -->
      <g class="loupe">
        <g :clip-path="`url(#${ids.lens})`" class="loupe-view">
          <circle class="loupe-backdrop" :cx="LOUPE.x" :cy="LOUPE.y" :r="LOUPE.radius" />
          <g :transform="LOUPE.magnify">
            <path v-for="arc in LOUPE.arcs" :key="`near-${arc.nm}`" class="near-arc" :d="arc.path" :stroke="arc.color" />
            <path v-for="(line, index) in LOUPE.lines" :key="`dark-${line.letter}`" class="dark-line" :d="line.path" :stroke-width="line.width" :style="{ '--delay': `${3.6 + index * 0.12}s` }" />
          </g>
          <text v-for="(line, index) in LOUPE.lines" :key="`letter-${line.letter}`" class="line-letter" :x="line.labelX" :y="line.labelY" text-anchor="middle" :style="{ '--delay': `${3.7 + index * 0.12}s` }">{{ line.letter }}</text>
        </g>
        <circle class="loupe-rim" :cx="LOUPE.x" :cy="LOUPE.y" :r="LOUPE.radius" pathLength="1" />
        <circle class="loupe-rim loupe-rim--outer" :cx="LOUPE.x" :cy="LOUPE.y" :r="LOUPE.radius + 6" />
        <path v-for="(tick, index) in LOUPE.ticks" :key="`reticle-${index}`" class="reticle" :d="tick" />
        <text class="loupe-power" :x="LOUPE.powerLabel.x" :y="LOUPE.powerLabel.y" text-anchor="middle">{{ LOUPE.powerLabel.text }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup>
import { useId } from 'vue'
import { FRAUNHOFER_LINES, rainbowAngle, wavelengthToRgb } from '../spectrum'
import { polarPoint } from '../sceneGeometry'

/**
 * Escena de Iris: el arcoíris, su camino entre el cielo y la tierra, grabado con su
 * geometría real. Cada color es un trazo fino a su propio radio —el ángulo al que las
 * gotas de lluvia devuelven ese color, calculado con el índice de refracción del
 * agua—: el arco primario a unos 42° con el rojo fuera, y el secundario, más tenue, a
 * unos 51° con los colores al revés. A la izquierda, la medida de los dos ángulos y la
 * banda oscura de Alejandro entre ambos; a la derecha, una lupa sobre el arco que lo
 * enseña de cerca con las líneas de Fraunhofer, las que dejan en la luz del Sol los
 * elementos que la absorben. Es lo que hace Iris con un correo: mirarlo de cerca para
 * leer lo que no se ve a simple vista.
 *
 * Al aparecer, el arco se pinta de un extremo a otro y después el secundario; la lupa
 * se traza y sus líneas aparecen con sus letras. Luego un punto de luz recorre el arco
 * de vez en cuando: es lo único que se mueve sin parar, y va en su propia capa para no
 * obligar a repintar el grabado en cada fotograma.
 */

const uid = useId()
// Una página puede pintar la escena dos veces (cabecera y banda tenue): cada copia lleva sus propios ids.
const ids = { glow: `${uid}-glow`, glint: `${uid}-glint`, lens: `${uid}-lens` }

const round = (value) => Math.round(value * 10) / 10
const rgb = (nm) => `rgb(${wavelengthToRgb(nm).join(' ')})`

/** El punto opuesto al Sol, centro de los arcos: queda bajo el horizonte, fuera de la lámina. */
const CENTER = { x: 600, y: 990 }
const PIXELS_PER_DEGREE = 19
const radiusOf = (nm, reflections = 1) => rainbowAngle(nm, reflections) * PIXELS_PER_DEGREE

/** Arco de circunferencia alrededor del centro, entre dos ángulos medidos desde la vertical. */
function arcPath(radius, from = -72, to = 72) {
  const start = polarPoint(CENTER.x, CENTER.y, radius, from)
  const end = polarPoint(CENTER.x, CENTER.y, radius, to)
  return `M${start.x} ${start.y} A${round(radius)} ${round(radius)} 0 0 1 ${end.x} ${end.y}`
}

/** Longitudes de onda de los trazos de un arco, del rojo al violeta. */
const wavelengths = (from, to, step) => Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, index) => to - index * step)

const BOWS = {
  primary: wavelengths(400, 700, 7.5).map((nm) => ({ nm, color: rgb(nm), path: arcPath(radiusOf(nm)) })),
  secondary: wavelengths(400, 700, 10).map((nm) => ({ nm, color: rgb(nm), path: arcPath(radiusOf(nm, 2)) })),
  primaryInner: round(radiusOf(400)),
  glint: arcPath(radiusOf(550)),
}

/** Lectura de los ángulos sobre una guía que apunta al centro de los arcos. */
const READING = (() => {
  const angle = -32
  const point = (degrees) => polarPoint(CENTER.x, CENTER.y, degrees * PIXELS_PER_DEGREE, angle)
  const guideFrom = point(38.5)
  const guideTo = point(55.5)
  const tick = (degrees, label) => {
    const at = point(degrees)
    const across = polarPoint(at.x, at.y, 7, angle + 90)
    const opposite = polarPoint(at.x, at.y, 7, angle - 90)
    return { label, path: `M${opposite.x} ${opposite.y} L${across.x} ${across.y}`, labelX: round(across.x + 6), labelY: round(across.y + 4) }
  }
  const band = point(47)
  return {
    guide: `M${guideFrom.x} ${guideFrom.y} L${guideTo.x} ${guideTo.y}`,
    ticks: [tick(rainbowAngle(589), '42°'), tick(rainbowAngle(589, 2), '51°')],
    band: { text: 'Alexander', x: round(band.x + 12), y: round(band.y + 4) },
  }
})()

/**
 * La lupa: un círculo sobre el arco primario que lo amplía alrededor de su centro.
 * Dentro, los mismos trazos de color a su radio real, ampliados, y las líneas de
 * Fraunhofer como arcos oscuros a la longitud de onda de cada una. Las letras van en
 * una columna sobre sus líneas, como en un ocular graduado; cuando dos líneas caen casi
 * juntas (E y b, H y K), la segunda letra se aparta a un lado para no pisar la primera.
 */
const LOUPE = (() => {
  const angle = 37
  const power = 3.5
  const radius = 80
  const nearFrom = 395
  const nearTo = 765
  const middle = (radiusOf(nearFrom) + radiusOf(nearTo)) / 2
  const center = polarPoint(CENTER.x, CENTER.y, middle, angle)
  const outward = polarPoint(0, 0, 1, angle)
  const along = polarPoint(0, 0, 1, angle + 90)
  // La lente solo enseña unos grados del arco: se trazan esos, con margen, y no el arco entero que el recorte esconde.
  const span = ((1.5 * radius) / power / middle) * (180 / Math.PI)
  const nearArc = (nm) => arcPath(radiusOf(nm), angle - span, angle + span)

  const column = -30
  const lines = FRAUNHOFER_LINES.reduce((placed, line) => {
    const offset = power * (radiusOf(line.nm) - middle)
    const previous = placed.at(-1)
    const isCrowded = previous && Math.abs(previous.offset - offset) < 10 && !previous.isCrowded
    const lateral = column + (isCrowded ? 16 : 0)
    return [...placed, {
      letter: line.letter,
      offset,
      isCrowded,
      path: nearArc(line.nm),
      width: round(line.width * 0.4),
      labelX: round(center.x + outward.x * offset + along.x * lateral),
      labelY: round(center.y + outward.y * offset + along.y * lateral + 4),
    }]
  }, [])

  const ticks = Array.from({ length: 36 }, (_, index) => {
    const from = polarPoint(center.x, center.y, radius + 6, index * 10)
    const to = polarPoint(center.x, center.y, radius + (index % 9 === 0 ? 15 : 10), index * 10)
    return `M${from.x} ${from.y} L${to.x} ${to.y}`
  })

  const powerAt = polarPoint(center.x, center.y, radius + 26, 180 + angle)
  return {
    x: center.x,
    y: center.y,
    radius,
    magnify: `translate(${center.x} ${center.y}) scale(${power}) translate(${-center.x} ${-center.y})`,
    arcs: wavelengths(nearFrom, nearTo, 5).map((nm) => ({ nm, color: rgb(nm), path: nearArc(nm) })),
    lines,
    ticks,
    powerLabel: { text: `×${String(power).replace('.', ',')}`, x: powerAt.x, y: powerAt.y + 4 },
  }
})()
</script>

<style scoped>
.scene { position: relative; width: 100%; height: 100%; }
/* Las capas se apilan con el mismo viewBox, así que coinciden punto a punto. */
.layer { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.layer--moving { will-change: transform; }

.glow-stop { stop-color: var(--text); }
.sky-glow { animation: fade 3s ease 1.6s backwards; }

/* ── Arcos: se pintan de izquierda a derecha, color a color ── */
.bow path { fill: none; stroke-linecap: round; animation: draw 2.8s cubic-bezier(0.35, 0.1, 0.25, 1) var(--delay) backwards; }
.bow--primary path { stroke-width: 1.25; opacity: 0.42; }
.bow--secondary path { stroke-width: 1.3; opacity: 0.18; }

.glint { offset-rotate: 0deg; opacity: 0; animation: glide 11s ease-in-out 5s infinite; }

/* ── Lectura ── */
.reading { animation: fade 1.6s ease 2.8s backwards; }
/* Los trazos finos nunca bajan de un píxel real de la pantalla (`--device-pixel`). */
.guide { stroke: var(--accent); stroke-width: max(0.7px, calc(var(--device-pixel, 0) * 1px)); stroke-dasharray: 2 4; opacity: 0.6; }
.tick { stroke: var(--accent-bright); stroke-width: 1; opacity: 0.85; }
.angle-label { font-family: var(--font-mono); font-size: 0.72em; letter-spacing: 0.04em; fill: var(--accent-bright); opacity: 0.8; }
.band-name { font-family: var(--font-display); font-style: italic; font-size: 0.82em; letter-spacing: 0.06em; fill: var(--accent); opacity: 0.6; }

/* ── Lupa ── */
.loupe-view { animation: fade 1.4s ease 3.2s backwards; }
.loupe-backdrop { fill: var(--bg); opacity: 0.94; }
/* Ampliados, los trazos siguen siendo finos: se ve el rayado del grabado, no una mancha. */
.near-arc { fill: none; stroke-width: 0.6; opacity: 0.55; }
.dark-line { fill: none; stroke: #07080c; opacity: 0.85; animation: fade 0.8s ease var(--delay) backwards; }
.line-letter { font-family: var(--font-display); font-size: 0.78em; font-weight: 600; fill: var(--text); opacity: 0.9; paint-order: stroke; stroke: var(--bg); stroke-width: 3px; animation: fade 0.8s ease var(--delay) backwards; }
.loupe-rim { fill: none; stroke: var(--accent-bright); stroke-width: 1.2; opacity: 0.85; animation: draw 1.4s cubic-bezier(0.3, 0.1, 0.2, 1) 2.9s backwards; }
.loupe-rim--outer { stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.5; animation: fade 1s ease 3.4s backwards; }
.reticle { stroke: var(--accent); stroke-width: max(0.7px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.6; animation: fade 1s ease 3.4s backwards; }
.loupe-power { font-family: var(--font-mono); font-size: 0.66em; letter-spacing: 0.06em; fill: var(--accent-bright); opacity: 0.7; animation: fade 1s ease 3.6s backwards; }

/* El guion solo dura lo que dura el trazado: en reposo el trazo queda liso y no se recalcula en cada repintado. */
@keyframes draw { from { stroke-dasharray: 1; stroke-dashoffset: 1; } to { stroke-dasharray: 1; stroke-dashoffset: 0; } }
@keyframes fade { from { opacity: 0; } }
@keyframes glide {
  0% { offset-distance: 0%; opacity: 0; }
  10% { opacity: 1; }
  55% { offset-distance: 100%; opacity: 1; }
  62%, 100% { offset-distance: 100%; opacity: 0; }
}
</style>
