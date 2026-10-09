<template>
  <div
    v-if="scene"
    ref="root"
    class="atmosphere"
    :data-module="moduleId"
    :data-strength="strength"
    :data-focus="focus"
    :data-fit="fit"
    :data-offscreen="isOffscreen"
    :data-compact="isCompact"
    :style="{ '--device-pixel': devicePixel }"
    aria-hidden="true"
  >
    <component :is="scene" />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { useDevicePixel } from '@/composables/useDevicePixel'

/**
 * Capa de ambiente de un módulo: la escena animada de su mitología, detrás del
 * contenido. Cada módulo tiene la suya en `scenes/<Módulo>Scene.vue`, grabada a partir
 * de fórmulas y de datos reales, no dibujada a mano:
 *
 * - Themis: lámina de atlas celeste con Libra, la balanza (`StarChart`).
 * - Aegis: lámina de atlas con el mito de Perseo: él con la cabeza de Medusa, donde Algol
 *   se eclipsa, y Andrómeda con su galaxia (`StarChart`).
 * - Iris: el arcoíris a sus ángulos reales, con una lupa que enseña las líneas de Fraunhofer.
 * - Acheron: carta grabada del río y la laguna Aquerusia, con la travesía de Caronte.
 * - Hygeia: lámina de atlas con el Serpentario, Asclepio, y la Serpiente (`StarChart`).
 *
 * Se carga bajo demanda, así que una página solo descarga la escena de su módulo.
 * Es decoración pura: no recibe el ratón y se esconde de los lectores de pantalla.
 * Con movimiento reducido las escenas se quedan quietas (`motion.css`).
 *
 * Cuida dos cosas por la escena:
 * - Nitidez: pasa en `--device-pixel` cuánto mide un píxel real en unidades del dibujo,
 *   para que ningún trazo fino baje de un píxel (ver `useDevicePixel`); y marca
 *   `data-compact` cuando la escena sale tan pequeña (en un móvil) que sus rótulos
 *   serían ilegibles, para esconderlos.
 * - Rendimiento: pausa sus animaciones cuando no se ve.
 */
const props = defineProps({
  /** Módulo cuya escena se pinta: `themis`, `aegis`, `iris`, `acheron` o `hygeia`. */
  moduleId: { type: String, required: true },
  /** `hero` para una cabecera, con la escena entera; `subtle` para una banda secundaria, más tenue. */
  strength: { type: String, default: 'hero', validator: (value) => ['hero', 'subtle'].includes(value) },
  /** `sides` apaga la escena detrás de la columna central, donde va el texto; `full` la deja entera. */
  focus: { type: String, default: 'sides', validator: (value) => ['sides', 'right', 'full'].includes(value) },
  /** `contain` enseña la escena entera, anclada abajo; `wide` la agranda para una cabecera baja y la centra, recortando por arriba y por abajo. */
  fit: { type: String, default: 'contain', validator: (value) => ['contain', 'wide'].includes(value) },
})

const loaders = import.meta.glob('./scenes/*Scene.vue')

// Una escena que no se ve no se anima: las páginas llevan dos y la de abajo gastaría CPU sin que nadie la mire.
const root = ref(null)
const isOffscreen = ref(false)
let watcher = null
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined' || !root.value) return
  watcher = new IntersectionObserver(([entry]) => { isOffscreen.value = !entry.isIntersecting })
  watcher.observe(root.value)
})
onBeforeUnmount(() => watcher?.disconnect())

/** Escala del dibujo de 1200 × 600: entero y ajustado a la caja, o a lo ancho con un mínimo de 1100 px. */
const SCENE_WIDTH = 1200
const SCENE_HEIGHT = 600
const { devicePixel, scale } = useDevicePixel(root, (box) => (
  props.fit === 'wide' ? Math.max(box.width, 1100) / SCENE_WIDTH : Math.min(box.width / SCENE_WIDTH, box.height / SCENE_HEIGHT)
))
/** Con el dibujo a menos del 60 % (una escena de menos de 720 px de ancho), sus rótulos medirían 6 px o menos: sobran. */
const isCompact = computed(() => scale.value > 0 && scale.value < 0.6)

const scene = computed(() => {
  const name = props.moduleId.charAt(0).toUpperCase() + props.moduleId.slice(1)
  const loader = loaders[`./scenes/${name}Scene.vue`]
  return loader ? defineAsyncComponent(loader) : null
})
</script>

<style scoped>
.atmosphere {
  --atmosphere-strength: 1;
  position: absolute;
  /* Se ancla a la primera pantalla: en un hero más alto que la ventana, la escena
     entera se ve sin tener que bajar. */
  inset: 0 0 auto 0;
  height: min(100%, calc(100vh - 72px));
  overflow: hidden;
  pointer-events: none;
  opacity: var(--atmosphere-strength);
  animation: atmosphere-in 2.2s ease both;
  /* La escena se funde con el fondo por arriba, para no competir con el título. */
  --fade-top: linear-gradient(to bottom, transparent 0%, #000 38%);
  -webkit-mask-image: var(--fade-top);
  mask-image: var(--fade-top);
}
/* Con el foco en los lados, la escena baja de intensidad detrás del texto central. */
.atmosphere[data-focus="sides"] {
  --fade-sides: linear-gradient(to right, #000 0%, rgba(0, 0, 0, 0.3) 26%, rgba(0, 0, 0, 0.16) 50%, rgba(0, 0, 0, 0.3) 74%, #000 100%);
  -webkit-mask-image: var(--fade-top), var(--fade-sides);
  mask-image: var(--fade-top), var(--fade-sides);
  -webkit-mask-composite: source-in;
  mask-composite: intersect;
}
.atmosphere[data-focus="right"] {
  --fade-sides: linear-gradient(to right, rgba(0, 0, 0, 0.1) 0%, rgba(0, 0, 0, 0.16) 46%, #000 80%);
  -webkit-mask-image: var(--fade-top), var(--fade-sides);
  mask-image: var(--fade-top), var(--fade-sides);
  -webkit-mask-composite: source-in;
  mask-composite: intersect;
}
.atmosphere[data-focus="full"] { -webkit-mask-image: none; mask-image: none; }
/* En una cabecera baja la escena se agranda para no quedar pequeña, y se centra. */
.atmosphere[data-fit="wide"] { display: flex; justify-content: center; align-items: center; }
.atmosphere[data-fit="wide"] :deep(.scene) { flex: none; width: max(100%, 1100px); height: auto; aspect-ratio: 2 / 1; }
.atmosphere[data-strength="subtle"] { --atmosphere-strength: 0.5; }
.atmosphere[data-offscreen="true"] :deep(*) { animation-play-state: paused !important; }
/* En una escena muy pequeña los rótulos medirían tres o cuatro píxeles: se quitan. */
.atmosphere[data-compact="true"] :deep(text) { display: none; }

@keyframes atmosphere-in { from { opacity: 0; } to { opacity: var(--atmosphere-strength); } }
</style>
