<template>
  <svg class="scene scene--drift" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMax meet" focusable="false">
    <g>
      <!-- Retícula de ascensión recta y declinación, como en una lámina de atlas -->
      <path
        v-for="(line, index) in plate.grid"
        :key="`grid-${line.kind}-${line.value}`"
        class="grid"
        :class="{ 'grid--major': line.isMajor }"
        :d="line.path"
        pathLength="1"
        :style="{ '--delay': `${index * 0.05}s` }"
      />
      <text v-for="label in plate.gridLabels" :key="label.text" class="grid-label" :x="label.x" :y="label.y" :text-anchor="label.anchor">{{ label.text }}</text>

      <!-- La eclíptica, el camino aparente del Sol, si la lámina la cruza -->
      <path v-if="plate.ecliptic" class="ecliptic" :d="plate.ecliptic" pathLength="1" />

      <!-- Objetos difusos (galaxias, nebulosas), como los dibujaban los atlas: un óvalo punteado con su núcleo -->
      <g v-for="nebula in plate.nebulae" :key="nebula.label" class="nebula" :transform="`translate(${nebula.x} ${nebula.y}) rotate(${nebula.rotation})`">
        <ellipse class="nebula-halo" :rx="nebula.width / 2" :ry="nebula.length / 2" />
        <ellipse class="nebula-core" :rx="nebula.width / 5" :ry="nebula.length / 5" />
      </g>
      <text v-for="nebula in plate.nebulae" :key="`label-${nebula.label}`" class="annotation annotation--nebula" :x="nebula.x + nebula.width / 2 + 8" :y="nebula.y + 4">{{ nebula.label }}</text>

      <circle v-for="(star, index) in plate.field" :key="`field-${index}`" class="field-star" :class="{ 'field-star--twinkle': star.isTwinkling }" :cx="star.x" :cy="star.y" :r="star.radius" :style="{ '--delay': `${star.delay}s`, '--period': `${star.period}s` }" />

      <g v-for="constellation in plate.constellations" :key="constellation.name" :class="{ 'is-neighbour': constellation.isNeighbour }">
        <path v-for="(edge, index) in constellation.edges" :key="`edge-${index}`" class="figure" :d="edge" pathLength="1" :style="{ '--delay': `${constellation.edgeDelay + index * 0.2}s` }" />
        <g
          v-for="(star, index) in constellation.stars"
          :key="star.letter"
          class="star-mark"
          :style="{ '--delay': `${0.6 + star.magnitude * 0.35}s`, '--period': `${3.2 + (index % 4) * 0.9}s` }"
        >
          <circle v-if="star.magnitude < 3.4 && !constellation.isNeighbour" class="star-ring" :cx="star.x" :cy="star.y" :r="star.radius + 3" />
          <circle class="star" :class="{ 'star--eclipsing': star.isEclipsing, 'star--twinkle': !star.isEclipsing && !constellation.isNeighbour && star.magnitude < 3 }" :cx="star.x" :cy="star.y" :r="star.radius" />
          <text v-if="!constellation.isNeighbour && star.magnitude <= constellation.labelLimit" class="star-letter" :x="star.x + star.radius + 5" :y="star.y - star.radius - 2">{{ star.letter }}</text>
          <text
            v-if="star.name"
            class="star-name"
            :x="star.nameSide === 'left' ? star.x - star.radius - 6 : star.x + star.radius + 5"
            :y="star.y + star.radius + 13"
            :text-anchor="star.nameSide === 'left' ? 'end' : 'start'"
          >{{ star.name }}</text>
        </g>
        <text v-if="constellation.label" class="constellation-name" :x="constellation.label.x" :y="constellation.label.y" text-anchor="middle">{{ constellation.name }}</text>
      </g>

      <text v-for="note in plate.annotations" :key="note.text" class="annotation" :x="note.x" :y="note.y" text-anchor="middle">{{ note.text }}</text>
    </g>
  </svg>
</template>

<script setup>
import { computed } from 'vue'
import { constellationEdges, eclipticPath, formatDeclination, graticule, projectCatalog, starRadius, stereographic } from './celestial'
import { seededRandom } from '@/composables/motionMath'

/**
 * Lámina de atlas celeste: la escena de los módulos cuyo mito está en el cielo.
 *
 * Pinta estrellas reales —posición y brillo de catálogo— en proyección estereográfica,
 * con su retícula de horas y grados, la eclíptica si la lámina la cruza, estrellas
 * débiles de fondo y las figuras de las constelaciones. Cada escena solo aporta los
 * datos de su lámina.
 *
 * Al aparecer, la retícula se traza, las estrellas se encienden de la más brillante
 * a la más débil y las figuras se dibujan; después el cielo deriva muy despacio,
 * algunas estrellas centellean y una estrella marcada como eclipsante (Algol) se apaga
 * un momento cada ciclo, como hace de verdad cada casi tres días. Lo que se mueve sin
 * parar es barato: la deriva la hace la tarjeta gráfica y el centelleo cambia a saltos,
 * sin filtros, en unas pocas estrellas.
 */
const props = defineProps({
  /**
   * Definición de la lámina:
   *
   * - `projection`: `{ ra, dec, scale, x, y }`, ver `stereographic`.
   * - `grid`: `{ raRange, decRange, raLabels, raLabelDec, decLabels, decLabelRa }`: lo que
   *   cubre la retícula, qué meridianos y círculos se rotulan y a qué altura.
   * - `ecliptic`: `[desde, hasta]` en longitud eclíptica, o `null` si no pasa por la lámina.
   * - `fieldSeed`: semilla de las estrellas de fondo.
   * - `constellations`: lista de `{ name, label: {ra, dec} | null, stars, pairs,
   *   isNeighbour?, labelLimit? }`. Cada estrella es `{ letter, ra, dec, magnitude,
   *   name?, nameSide?, isEclipsing? }` (`nameSide: 'left'` pone el nombre a su
   *   izquierda, para cuando a la derecha hay trazos); `labelLimit` (por defecto `4.6`) es la magnitud más débil
   *   que lleva su letra rotulada. Una vecina se pinta más tenue y sin letras.
   * - `annotations`: rótulos sueltos `{ text, ra, dec }`, opcional.
   * - `nebulae`: objetos difusos `{ label, ra, dec, length, width, positionAngle }`, opcional:
   *   tamaño aparente en grados (eje mayor y menor) y ángulo de posición del eje mayor,
   *   en grados desde el norte hacia el este, como en los catálogos.
   */
  chart: { type: Object, required: true },
})

const plate = computed(() => {
  const { projection, grid, ecliptic, fieldSeed, constellations, annotations = [], nebulae = [] } = props.chart
  const project = stereographic(projection)
  const pixelsPerDegree = (projection.scale * Math.PI) / 180

  const gridLabels = [
    // La ascensión recta puede venir en negativo para una lámina que cruza las 0h.
    ...grid.raLabels.map((ra) => ({ text: `${(((ra % 360) + 360) % 360) / 15}h`, anchor: 'middle', ...project(ra, grid.raLabelDec) })),
    ...grid.decLabels.map((dec) => {
      const point = project(grid.decLabelRa, dec)
      return point ? { text: formatDeclination(dec), anchor: 'end', x: point.x, y: point.y - 5 } : {}
    }),
  ]

  const random = seededRandom(fieldSeed)
  const field = Array.from({ length: 90 }, () => ({
    x: Math.round(random() * 1200),
    y: Math.round(random() * 600),
    radius: starRadius(4.7 + random() * 1.5),
    delay: 0.4 + random() * 2.4,
    period: 4 + random() * 5,
  })).map((star, index) => ({ ...star, isTwinkling: index % 6 === 0 }))

  let mainEdges = 0
  const placed = constellations.map((constellation) => {
    const stars = projectCatalog(project, constellation.stars)
    const edges = constellationEdges(stars, constellation.pairs)
    // Las figuras principales se dibujan una tras otra; las vecinas, después.
    const edgeDelay = constellation.isNeighbour ? 2.8 : 1.8 + mainEdges * 0.2
    if (!constellation.isNeighbour) mainEdges += edges.length
    return {
      name: constellation.name,
      isNeighbour: Boolean(constellation.isNeighbour),
      labelLimit: constellation.labelLimit ?? 4.6,
      stars,
      edges,
      edgeDelay,
      label: constellation.label ? project(constellation.label.ra, constellation.label.dec) : null,
    }
  })

  return {
    grid: graticule(project, grid),
    gridLabels: gridLabels.filter((label) => label.x !== undefined),
    ecliptic: ecliptic ? eclipticPath(project, ecliptic) : null,
    field,
    constellations: placed,
    annotations: annotations.map((note) => ({ text: note.text, ...project(note.ra, note.dec) })),
    // Con el norte arriba y el este a la izquierda, un ángulo de posición gira el eje hacia la izquierda.
    nebulae: nebulae.map((nebula) => ({
      label: nebula.label,
      ...project(nebula.ra, nebula.dec),
      length: nebula.length * pixelsPerDegree,
      width: nebula.width * pixelsPerDegree,
      rotation: -nebula.positionAngle,
    })),
  }
})
</script>

<style scoped>
.scene { width: 100%; height: 100%; display: block; }

/* El cielo deriva muy despacio, como en una noche larga. */
/* Se mueve la lámina entera como una capa: la desplaza la tarjeta gráfica sin volver a
   pintar el dibujo. Mover un grupo de dentro del SVG obligaría a repintarlo todo en cada
   fotograma. */
.scene--drift { overflow: visible; animation: sky-drift 110s ease-in-out infinite alternate; }
/* Se desplaza a un lado y a otro del centro, y la retícula sigue más allá del borde
   (overflow visible), así que nunca asoma un hueco en los lados. */
@keyframes sky-drift { from { transform: translate(-16px, -3px); } to { transform: translate(16px, 3px); } }

/* ── Retícula: trazo fino de grabado; las líneas mayores, algo más marcadas ── */
.grid, .ecliptic, .figure { fill: none; stroke-linecap: round; }
/* Los trazos finos nunca bajan de un píxel real de la pantalla (`--device-pixel`, ver
   `ModuleAtmosphere`): por debajo se ven grises y borrosos en una pantalla normal. */
.grid { stroke: var(--accent); stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.14; stroke-dasharray: 1; animation: draw 2.8s cubic-bezier(0.3, 0.1, 0.2, 1) var(--delay) backwards; }
.grid--major { opacity: 0.26; stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); }
.ecliptic { stroke: var(--accent-bright); stroke-width: max(0.9px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.35; stroke-dasharray: 0.006 0.006; animation: fade 2s ease 2.4s backwards; }

/* ── Estrellas: disco del tamaño de su brillo y, las más brillantes, un anillo ── */
/* Solo una de cada seis estrellas de fondo centellea, y a saltos: unas pocas veces por
   segundo bastan para un cambio tan lento, y cada salto repinta solo esa estrella. */
.field-star { fill: var(--accent-bright); opacity: 0.4; animation: fade 1.2s ease var(--delay) backwards; }
.field-star--twinkle { animation: fade 1.2s ease var(--delay) backwards, field-twinkle var(--period) steps(5) var(--delay) infinite alternate; }
.star { fill: var(--accent-bright); }
.star-ring { fill: none; stroke: var(--accent-bright); stroke-width: max(0.7px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.45; }
.star-mark { animation: kindle 1.2s cubic-bezier(0.2, 0.8, 0.2, 1) var(--delay) backwards; transform-box: fill-box; transform-origin: center; }
/* Las estrellas que centellean no llevan filtro: un resplandor animado se recalcula en
   cada cambio, y el anillo ya las distingue. */
.star--twinkle { animation: twinkle var(--period, 4s) steps(6) var(--delay) infinite alternate; }
/* Algol: brillo estable casi todo el ciclo y un eclipse breve, como su curva de luz. */
.star--eclipsing { animation: eclipse 12s steps(48) 4s infinite; }

/* ── Figuras: se dibujan tramo a tramo, sin tocar las estrellas ── */
.figure { stroke: var(--accent-bright); stroke-width: 1.1; opacity: 0.6; stroke-dasharray: 1; animation: draw 1.4s cubic-bezier(0.3, 0.1, 0.2, 1) var(--delay) backwards; }
.is-neighbour .figure { stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.28; }
.is-neighbour .star { opacity: 0.55; }

/* ── Rótulos: letra de Bayer en cursiva, nombres propios y constelación en versalitas.
   En em: dentro del dibujo, el texto escala con la lámina como un rótulo grabado. ── */
.grid-label, .star-letter, .star-name, .constellation-name, .annotation { fill: var(--accent-bright); animation: fade 1.6s ease 3.2s backwards; }
.grid-label { font-family: var(--font-mono); font-size: 0.7em; letter-spacing: 0.08em; fill: var(--accent); opacity: 0.5; animation-delay: 2.2s; }
.star-letter { font-family: var(--font-display); font-style: italic; font-size: 0.95em; opacity: 0.75; }
.star-name { font-family: var(--font-display); font-style: italic; font-size: 0.76em; letter-spacing: 0.04em; opacity: 0.5; }
.is-neighbour .star-name { opacity: 0.32; }
.constellation-name { font-family: var(--font-epic); font-size: 0.95em; font-weight: 600; letter-spacing: 0.6em; opacity: 0.6; }
.is-neighbour .constellation-name { opacity: 0.25; font-size: 0.82em; }
.annotation { font-family: var(--font-display); font-style: italic; font-size: 0.85em; letter-spacing: 0.08em; opacity: 0.55; }
.annotation--nebula { font-family: var(--font-mono); font-style: normal; font-size: 0.66em; opacity: 0.45; }
.nebula { animation: fade 2.4s ease 2.6s backwards; }
.nebula-halo { fill: var(--accent-dim); stroke: var(--accent-bright); stroke-width: max(0.7px, calc(var(--device-pixel, 0) * 1px)); stroke-dasharray: 1.5 2.5; opacity: 0.6; }
.nebula-core { fill: var(--accent-bright); opacity: 0.35; filter: blur(1.5px); }

@keyframes draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes fade { from { opacity: 0; } }
@keyframes kindle { from { opacity: 0; transform: scale(0.2); } }
@keyframes twinkle { from { opacity: 0.55; } to { opacity: 1; } }
@keyframes field-twinkle { from { opacity: 0.18; } to { opacity: 0.5; } }
@keyframes eclipse { 0%, 70%, 100% { opacity: 1; } 80% { opacity: 0.25; } 84% { opacity: 0.25; } }
</style>
