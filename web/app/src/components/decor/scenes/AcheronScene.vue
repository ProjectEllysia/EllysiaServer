<template>
  <div class="scene">
    <!-- Lo que se mueve sin parar va en su propia capa, para no repintar la carta entera en
         cada cambio: el oleaje, debajo de la carta, y el farol, encima. -->
    <svg class="layer layer--moving" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <!-- El mar: líneas de agua paralelas a la costa, cada vez más separadas y más tenues -->
      <path
        v-for="(line, index) in COAST.waterLines"
        :key="`water-${index}`"
        class="water-line"
        :d="line"
        :style="{ '--delay': `${1.1 + index * 0.16}s`, '--weight': 0.5 - index * 0.055, '--swell': `${index * 0.55}s` }"
      />
    </svg>

    <svg class="layer" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <defs>
        <path v-for="river in RIVERS" :id="`${uid}-${river.id}`" :key="river.id" :d="river.labelPath" />
      </defs>

      <!-- Retícula de grados y minutos, como en una carta impresa -->
      <g class="graticule">
        <line v-for="meridian in GRATICULE.meridians" :key="meridian.label" :x1="meridian.x" :x2="meridian.x" y1="0" y2="600" />
        <line v-for="parallel in GRATICULE.parallels" :key="parallel.label" x1="0" x2="1200" :y1="parallel.y" :y2="parallel.y" />
        <text v-for="meridian in GRATICULE.meridians" :key="`m-${meridian.label}`" class="degree" :x="meridian.x + 5" y="16">{{ meridian.label }}</text>
        <text v-for="parallel in GRATICULE.parallels" :key="`p-${parallel.label}`" class="degree" x="1192" :y="parallel.y - 5" text-anchor="end">{{ parallel.label }}</text>
      </g>

      <path class="coast" :d="COAST.path" pathLength="1" />

      <!-- Relieve: sierras sombreadas con trazos -->
      <g class="relief">
        <path v-for="(ridge, index) in RELIEF" :key="`relief-${index}`" :d="ridge" />
      </g>

      <!-- La laguna Aquerusia, con sus líneas de agua hacia dentro -->
      <path v-for="(line, index) in LAKE.waterLines" :key="`lake-${index}`" class="lake-line" :d="line" :style="{ '--delay': `${1.8 + index * 0.18}s`, '--weight': 0.42 - index * 0.08 }" />
      <path class="lake" :d="LAKE.shore" pathLength="1" />

      <!-- Los ríos se dibujan desde su nacimiento hasta el agua; los afluentes, más finos -->
      <path v-for="river in [...RIVERS, ...TRIBUTARIES]" :key="`draw-${river.id}`" class="river" :d="river.path" pathLength="1" :style="{ '--delay': `${river.delay}s`, '--river-width': river.width }" />

      <!-- La travesía de Caronte, marcada como una derrota en una carta náutica -->
      <path class="route" :d="ROUTE" />

      <!-- El oráculo de los muertos y las dos ciudades del valle -->
      <g v-for="site in SITES" :key="site.name" class="site">
        <circle :cx="site.x" :cy="site.y" :r="site.isMajor ? 6 : 4.5" class="site-ring" />
        <circle :cx="site.x" :cy="site.y" :r="site.isMajor ? 2.4 : 1.8" class="site-dot" />
      </g>

      <!-- Rosa de los vientos -->
      <g :transform="`translate(${ROSE.x} ${ROSE.y})`">
        <g class="rose">
          <circle r="62" class="rose-ring" />
          <circle r="56" class="rose-ring" />
          <path v-for="(tick, index) in ROSE.ticks" :key="`tick-${index}`" class="rose-tick" :d="tick" />
          <path v-for="(spoke, index) in ROSE.spokes" :key="`spoke-${index}`" class="rose-spoke" :d="spoke" />
          <path v-for="(half, index) in ROSE.minorHalves" :key="`minor-${index}`" :class="half.isShaded ? 'rose-fill' : 'rose-line'" :d="half.path" />
          <path v-for="(half, index) in ROSE.majorHalves" :key="`major-${index}`" :class="half.isShaded ? 'rose-fill' : 'rose-line'" :d="half.path" />
          <circle r="3" class="rose-fill" />
        </g>
        <text class="rose-north" x="0" y="-70" text-anchor="middle">{{ ROSE.north }}</text>
      </g>

      <!-- Escala en estadios -->
      <g class="scale-bar">
        <rect v-for="segment in SCALE.segments" :key="segment.x" :x="segment.x" :y="SCALE.y" :width="SCALE.step" height="4" :class="segment.isFilled ? 'scale-fill' : 'scale-empty'" />
        <text v-for="label in SCALE.labels" :key="label.value" class="degree" :x="label.x" :y="SCALE.y - 6" text-anchor="middle">{{ label.value }}</text>
        <text class="degree" :x="SCALE.labels.at(-1).x + 14" :y="SCALE.y + 4">{{ SCALE.unit }}</text>
      </g>

      <!-- Rótulos -->
      <g class="labels">
        <text class="sea-name" :transform="`translate(${SEA_LABEL.x} ${SEA_LABEL.y}) rotate(-90)`" text-anchor="middle">{{ SEA_LABEL.text }}</text>
        <text class="lake-name" :x="LAKE.label.x" :y="LAKE.label.y" text-anchor="middle">{{ LAKE.label.text }}</text>
        <text v-for="site in SITES" :key="`name-${site.name}`" class="site-name" :x="site.x + site.labelDx" :y="site.y + site.labelDy" :text-anchor="site.labelDx < 0 ? 'end' : 'start'">{{ site.name }}</text>
        <text v-for="river in RIVERS" :key="`name-${river.id}`" class="river-name">
          <textPath :href="`#${uid}-${river.id}`" :startOffset="river.labelAt">{{ river.name }}</textPath>
        </text>
      </g>
    </svg>

    <svg class="layer layer--moving" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
      <!-- El farol de Caronte recorre la derrota -->
      <circle class="lantern lantern--halo" r="8" :style="{ offsetPath: `path('${ROUTE}')` }" />
      <circle class="lantern" r="2.6" :style="{ offsetPath: `path('${ROUTE}')` }" />
    </svg>
  </div>
</template>

<script setup>
import { useId } from 'vue'
import { hachures, lakePoints, meanderPoints, offsetPoints, smoothPath } from '../cartography'
import { polarPoint } from '../sceneGeometry'
import { seededRandom } from '@/composables/motionMath'

/**
 * Escena de Acheron: una carta grabada a la antigua del bajo Aqueronte, en el Epiro,
 * donde los griegos situaban la entrada al Hades. El río baja de la sierra, cruza la
 * laguna Aquerusia —junto a la que estaba el oráculo de los muertos— y sale al mar
 * Jónico; el Cocito llega a la laguna por el sur. Junto al río, Éfira y Pandosia, dos
 * ciudades antiguas del valle. La travesía de Caronte se marca como la derrota de un
 * barco, con un farol que la recorre.
 *
 * La geometría es la de una carta, no la del terreno exacto: la costa, los ríos y la
 * laguna salen de funciones con semilla (`cartography.js`), así que son siempre iguales.
 * Al aparecer, la costa y la laguna se trazan, el agua se llena de líneas, los ríos
 * corren hacia el mar y la rosa de los vientos se asienta.
 */

const uid = useId()
const random = seededRandom(1957)
const round = (value) => Math.round(value * 10) / 10

/** Costa de norte a sur: suave, con la bahía donde desemboca el río. */
const coastX = (y) => 286 + 30 * Math.sin(y / 92 + 0.6) + 12 * Math.sin(y / 37 + 2) + 6 * Math.sin(y / 17) + 46 * Math.exp(-(((y - 398) / 64) ** 2))
const COAST = (() => {
  const points = Array.from({ length: 34 }, (_, index) => {
    const y = -30 + index * 20
    return { x: coastX(y), y }
  })
  // Hacia el mar, que queda a la derecha de una costa recorrida de norte a sur.
  const distances = [6, 12, 19, 27, 36, 46, 57, 69]
  return { path: smoothPath(points), waterLines: distances.map((distance) => smoothPath(offsetPoints(points, -distance))) }
})()

const LAKE = (() => {
  const shape = { centerX: 846, centerY: 300, radius: 66, stretch: 1.7, harmonics: [[2, 8, 0.7], [3, 6, 2.1], [5, 3, 0.4]] }
  return {
    shape,
    points: lakePoints(shape),
    shore: smoothPath(lakePoints(shape), true),
    waterLines: [6, 12, 19].map((inset) => smoothPath(lakePoints({ ...shape, inset }), true)),
    label: { text: 'ACHERUSIA PALUS', x: 846, y: 304 },
  }
})()

/** Punto de la orilla de la laguna en una dirección (en grados, 0 al este y en sentido horario). */
function shorePoint(angle) {
  return LAKE.points[Math.round(((angle % 360) + 360) % 360 / 10) % LAKE.points.length]
}

const mouth = { x: coastX(398), y: 398 }

/**
 * Traza un cauce y la guía de su rótulo. La guía sigue el curso general del río sin
 * sus curvas cerradas (un punto de cada ocho) y queda un poco por encima del agua, y
 * va siempre de izquierda a derecha aunque el río corra al revés: si no, el nombre se
 * retorcería en los meandros o se leería boca abajo.
 */
function course({ start, end, amplitude, bends, samples = 40 }) {
  const points = meanderPoints(start, end, { amplitude, bends, random, samples })
  const guide = points.filter((_, index) => index % 8 === 0 || index === points.length - 1)
  const rightward = start.x > end.x ? [...guide].reverse() : guide
  return { points, path: smoothPath(points), labelPath: smoothPath(offsetPoints(rightward, 9)) }
}

const RIVERS = [
  { id: 'acheron-upper', name: 'Acheron fl.', start: { x: 1210, y: 186 }, end: shorePoint(320), amplitude: 22, bends: 6, width: 1.3, delay: 1.4, labelAt: '30%' },
  { id: 'cocytus', name: 'Cocytus fl.', start: { x: 1150, y: 612 }, end: shorePoint(60), amplitude: 20, bends: 5, width: 1.1, delay: 1.7, labelAt: '14%' },
  { id: 'acheron-lower', name: 'Acheron fl.', start: shorePoint(180), end: mouth, amplitude: 30, bends: 7, width: 2, delay: 2.6, labelAt: '44%' },
].map((river) => ({ ...river, ...course(river) }))

/** Afluentes: arroyos que bajan de las sierras a los ríos principales. */
const TRIBUTARIES = [
  { id: 'brook-north', start: { x: 1010, y: -10 }, end: RIVERS[0].points[22], amplitude: 12, bends: 4, width: 0.7, delay: 2.2 },
  { id: 'brook-souli', start: { x: 920, y: 612 }, end: RIVERS[1].points[26], amplitude: 12, bends: 3, width: 0.7, delay: 2.4 },
  { id: 'brook-west', start: { x: 590, y: 612 }, end: RIVERS[2].points[18], amplitude: 14, bends: 4, width: 0.7, delay: 3 },
].map((brook) => ({ ...brook, ...course({ ...brook, samples: 22 }) }))

/** El oráculo de los muertos, junto a la laguna, y dos ciudades antiguas del valle. */
const SITES = [
  { name: 'Necyomanteion', ...shorePoint(200), isMajor: true, offsetY: -22, labelDx: -10, labelDy: -10 },
  { name: 'Ephyra', ...RIVERS[2].points[12], isMajor: false, offsetY: -20, labelDx: 9, labelDy: -6 },
  { name: 'Pandosia', ...RIVERS[0].points[14], isMajor: false, offsetY: 18, labelDx: 9, labelDy: 14 },
].map((site) => ({ ...site, x: round(site.x), y: round(site.y + site.offsetY) }))

/** Derrota de Caronte por la laguna, de la orilla de los vivos (este) a la del oráculo (oeste). */
const ROUTE = smoothPath([
  { x: shorePoint(10).x - 10, y: shorePoint(10).y },
  { x: 846, y: 326 },
  { x: shorePoint(195).x + 12, y: shorePoint(195).y },
])

/**
 * Sierras sombreadas. Cada una es un solo trazo con todos sus rayados: cientos de
 * elementos sueltos costarían memoria y tiempo de pintado sin verse distintos.
 */
const RELIEF = [
  [{ x: 930, y: 112 }, { x: 990, y: 86 }, { x: 1052, y: 104 }, { x: 1110, y: 92 }],
  [{ x: 1128, y: 100 }, { x: 1168, y: 74 }, { x: 1214, y: 90 }],
  [{ x: 1020, y: 548 }, { x: 1076, y: 528 }, { x: 1134, y: 546 }],
  [{ x: 560, y: 120 }, { x: 612, y: 100 }, { x: 668, y: 116 }],
  [{ x: 640, y: 520 }, { x: 700, y: 496 }, { x: 772, y: 512 }, { x: 840, y: 500 }],
  [{ x: 420, y: 70 }, { x: 470, y: 52 }, { x: 520, y: 66 }],
].map((ridge) => hachures(ridge, { spacing: 3.2, length: 22, random }).join(' '))

/** Rosa de los vientos de ocho puntas, con las cuatro mayores sombreadas a medias, como se grababan. */
const ROSE = (() => {
  const point = (radius, angle) => polarPoint(0, 0, radius, angle)
  const half = (tipRadius, sideRadius, angle, side) => {
    const tip = point(tipRadius, angle)
    const flank = point(sideRadius, angle + side * 45)
    return `M0 0 L${tip.x} ${tip.y} L${flank.x} ${flank.y} Z`
  }
  const halves = (angles, tipRadius, sideRadius) => angles.flatMap((angle) => [
    { path: half(tipRadius, sideRadius, angle, -1), isShaded: true },
    { path: half(tipRadius, sideRadius, angle, 1), isShaded: false },
  ])
  return {
    x: 150,
    y: 476,
    north: 'N',
    majorHalves: halves([0, 90, 180, 270], 54, 9),
    minorHalves: halves([45, 135, 225, 315], 36, 7),
    spokes: Array.from({ length: 16 }, (_, index) => {
      const tip = point(index % 2 ? 46 : 0, index * 22.5)
      return index % 2 ? `M0 0 L${tip.x} ${tip.y}` : ''
    }).filter(Boolean),
    ticks: Array.from({ length: 64 }, (_, index) => {
      const angle = index * 5.625
      const from = point(index % 8 === 0 ? 52 : 56, angle)
      const to = point(62, angle)
      return `M${from.x} ${from.y} L${to.x} ${to.y}`
    }),
  }
})()

const SCALE = (() => {
  const x = 62
  const step = 44
  return {
    y: 575,
    step,
    unit: 'STADIA',
    segments: [0, 1, 2, 3].map((index) => ({ x: x + index * step, isFilled: index % 2 === 0 })),
    labels: [0, 10, 20, 30, 40].map((value, index) => ({ value, x: x + index * step })),
  }
})()

const SEA_LABEL = { text: 'MARE IONIUM', x: 96, y: 210 }

/** Meridianos y paralelos cada diez minutos de arco, con sus valores del Epiro. */
const GRATICULE = {
  meridians: [150, 450, 750, 1050].map((x, index) => ({ x, label: `20°${20 + index * 10}′` })),
  parallels: [150, 450].map((y, index) => ({ y, label: `39°${20 - index * 10}′` })),
}
</script>

<style scoped>
.scene { position: relative; width: 100%; height: 100%; }
/* Las capas se apilan con el mismo viewBox, así que coinciden punto a punto. */
.layer { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.layer--moving { will-change: transform; }

/* Los trazos finos nunca bajan de un píxel real de la pantalla (`--device-pixel`, ver
   `ModuleAtmosphere`): por debajo se ven grises y borrosos en una pantalla normal. */
.graticule line { stroke: var(--accent); stroke-width: max(0.5px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.12; }
.degree { font-family: var(--font-mono); font-size: 0.66em; letter-spacing: 0.06em; fill: var(--accent); opacity: 0.5; }
.graticule { animation: fade 1.6s ease 0.2s backwards; }

/* ── Agua ── */
.coast, .lake, .river, .route { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.coast { stroke: var(--accent-bright); stroke-width: 1.3; opacity: 0.75; animation: draw 2.4s cubic-bezier(0.3, 0.1, 0.2, 1) 0.3s backwards; }
.water-line, .lake-line { fill: none; stroke: var(--accent); stroke-width: max(0.7px, calc(var(--device-pixel, 0) * 1px)); opacity: var(--weight); }
/* El oleaje cambia a saltos, un par de veces por segundo: para un cambio tan lento
   basta, y cada salto repinta solo esa línea en vez de hacerlo en cada fotograma. */
.water-line { animation: fade 1.2s ease var(--delay) backwards, swell 7s steps(7) calc(var(--delay) + var(--swell)) infinite; }
.lake-line { animation: fade 1.2s ease var(--delay) backwards; }
.lake { stroke: var(--accent-bright); stroke-width: 1.2; opacity: 0.8; animation: draw 2s cubic-bezier(0.3, 0.1, 0.2, 1) 0.9s backwards; }
.river { stroke: var(--accent-bright); stroke-width: var(--river-width); opacity: 0.75; animation: draw 1.8s cubic-bezier(0.4, 0.1, 0.3, 1) var(--delay) backwards; }

/* ── Tierra ── */
.relief path { stroke: var(--accent); stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.38; }
.relief { animation: fade 2s ease 1.2s backwards; }
.site-ring { fill: none; stroke: var(--accent-bright); stroke-width: max(0.9px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.8; }
.site-dot { fill: var(--accent-bright); }
.site { animation: fade 1s ease 3s backwards; }

/* ── Travesía ── */
.route { stroke: var(--accent-bright); stroke-width: max(0.9px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.55; stroke-dasharray: 3 5; animation: fade 1.2s ease 3.6s backwards; }
/* El resplandor del farol es un círculo tenue que viaja con él, no un filtro: un filtro
   en movimiento se recalcula en cada fotograma. */
.lantern { fill: var(--accent-bright); offset-rotate: 0deg; animation: cross 16s ease-in-out 4.2s infinite backwards; }
.lantern--halo { fill-opacity: 0.22; }

/* ── Rosa de los vientos: entra girada y se asienta, como una aguja ── */
.rose { transform-box: fill-box; transform-origin: center; animation: settle 2.6s cubic-bezier(0.25, 1.35, 0.4, 1) 0.8s backwards; }
.rose-ring { fill: none; stroke: var(--accent); stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.6; }
.rose-tick, .rose-spoke { stroke: var(--accent); stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.55; }
.rose-fill { fill: var(--accent-bright); opacity: 0.75; }
.rose-line { fill: var(--bg); stroke: var(--accent-bright); stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.85; }
.rose-north { font-family: var(--font-epic); font-size: 0.95em; font-weight: 600; fill: var(--accent-bright); animation: fade 1s ease 2.4s backwards; }

.scale-fill { fill: var(--accent); opacity: 0.7; }
.scale-empty { fill: none; stroke: var(--accent); stroke-width: max(0.7px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.7; }
.scale-bar { animation: fade 1.2s ease 2.6s backwards; }

/* ── Rótulos: versalitas espaciadas para el agua, cursiva para ríos y lugares ── */
.labels { animation: fade 1.8s ease 3.2s backwards; }
.sea-name { font-family: var(--font-display); font-style: italic; font-size: 1.15em; letter-spacing: 0.7em; fill: var(--accent); opacity: 0.55; }
.lake-name { font-family: var(--font-epic); font-size: 0.72em; letter-spacing: 0.4em; fill: var(--accent-bright); opacity: 0.6; }
.site-name, .river-name { font-family: var(--font-display); font-style: italic; font-size: 0.85em; letter-spacing: 0.05em; fill: var(--accent-bright); opacity: 0.65; }

/* El guion solo dura lo que dura el trazado: en reposo el trazo queda liso y no se recalcula en cada repintado. */
@keyframes draw { from { stroke-dasharray: 1; stroke-dashoffset: 1; } to { stroke-dasharray: 1; stroke-dashoffset: 0; } }
@keyframes fade { from { opacity: 0; } }
@keyframes swell { 0%, 100% { opacity: var(--weight); } 50% { opacity: calc(var(--weight) * 1.9); } }
@keyframes settle { from { transform: rotate(-50deg); opacity: 0; } 30% { opacity: 1; } }
@keyframes cross { 0% { offset-distance: 0%; opacity: 0; } 8% { opacity: 1; } 60% { offset-distance: 100%; opacity: 1; } 66%, 100% { offset-distance: 100%; opacity: 0; } }
</style>
