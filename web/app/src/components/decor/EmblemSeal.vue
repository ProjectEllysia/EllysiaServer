<template>
  <div ref="root" class="emblem-seal" :data-module="moduleId" :style="{ '--seal-size': `${size}px`, '--device-pixel': devicePixel }" aria-hidden="true">
    <!-- Bisel y primera red: giran despacio en un sentido. -->
    <svg class="seal-layer seal-layer--forward" viewBox="0 0 300 300" focusable="false">
      <path class="tick" :d="TICKS.minor" />
      <path class="tick tick--major" :d="TICKS.major" />
      <circle class="rule" cx="150" cy="150" r="139" />
      <circle class="rule" cx="150" cy="150" r="114" />
      <path v-for="(curve, index) in pattern.outer" :key="`outer-${index}`" class="guilloche" :d="curve" pathLength="1" :style="{ '--delay': `${0.2 + index * 0.05}s` }" />
    </svg>

    <!-- Segunda red, que gira al revés sobre la primera: al cruzarse, el grabado tiembla como el de un billete. -->
    <svg class="seal-layer seal-layer--backward" viewBox="0 0 300 300" focusable="false">
      <path v-for="(curve, index) in pattern.cross" :key="`cross-${index}`" class="guilloche guilloche--cross" :d="curve" pathLength="1" :style="{ '--delay': `${0.5 + index * 0.05}s` }" />
      <circle class="rule" cx="150" cy="150" r="108" />
      <path v-for="(curve, index) in pattern.inner" :key="`inner-${index}`" class="guilloche guilloche--inner" :d="curve" pathLength="1" :style="{ '--delay': `${0.9 + index * 0.06}s` }" />
      <circle class="rule rule--strong" cx="150" cy="150" r="93" />
    </svg>

    <div class="seal-disc">
      <img :src="icon" alt="" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useDevicePixel } from '@/composables/useDevicePixel'
import { guillochePath, polarPoint } from './sceneGeometry'
import { SEAL_PATTERNS } from './sealPatterns'

/**
 * Sello de grabado alrededor del emblema de un módulo: dos redes de guilloché que
 * giran en sentidos opuestos, un bisel graduado y, en el centro, el emblema.
 *
 * El dibujo sale de fórmulas, no de trazos a mano: es la técnica de los billetes y de
 * las monedas, que tiene sentido en una plataforma de seguridad y queda nítida a
 * cualquier tamaño. Al aparecer, las curvas se graban una tras otra. Con movimiento
 * reducido se pinta entero y quieto.
 *
 * Para que se vea nítido en una pantalla normal, cada red lleva pocas curvas (con
 * más, a este tamaño, se funden en una mancha) y ningún trazo baja de un píxel real
 * (`--device-pixel`). El giro es de capas enteras, que mueve la tarjeta gráfica.
 */
const props = defineProps({
  /** Módulo del sello: `themis`, `aegis`, `iris`, `acheron` o `hygeia` (ver `sealPatterns.js`). */
  moduleId: { type: String, required: true },
  /** Emblema del módulo, una imagen sobre fondo transparente. */
  icon: { type: String, required: true },
  /** Lado del sello en píxeles. Por defecto `260`. */
  size: { type: Number, default: 260 },
})

const root = ref(null)
const { devicePixel } = useDevicePixel(root, (box) => box.width / 300)

/**
 * Marcas del bisel: una cada 5° y una mayor cada 30°, como las doce casas del zodiaco.
 * Van en dos trazos, menores y mayores, en vez de uno por marca.
 */
const TICKS = (() => {
  const marks = Array.from({ length: 72 }, (_, index) => {
    const angle = index * 5
    const isMajor = angle % 30 === 0
    const from = polarPoint(150, 150, isMajor ? 141 : 143, angle)
    const to = polarPoint(150, 150, 148, angle)
    return { isMajor, path: `M${from.x} ${from.y} L${to.x} ${to.y}` }
  })
  const join = (isMajor) => marks.filter((mark) => mark.isMajor === isMajor).map((mark) => mark.path).join(' ')
  return { minor: join(false), major: join(true) }
})()

/**
 * Curvas de una red: `count` curvas iguales con la fase repartida a lo largo de una
 * onda, para que se crucen a intervalos regulares.
 */
function weave(radius, amplitude, lobes, count) {
  return Array.from({ length: count }, (_, index) => guillochePath({
    centerX: 150, centerY: 150, radius, amplitude, lobes, phase: (index / count) * Math.PI * 2,
  }))
}

const pattern = computed(() => {
  const { outerLobes, crossLobes, innerLobes } = SEAL_PATTERNS[props.moduleId]
  return {
    outer: weave(126.5, 9, outerLobes, 6),
    cross: weave(126.5, 9, crossLobes, 4),
    inner: weave(100.5, 6, innerLobes, 4),
  }
})
</script>

<style scoped>
.emblem-seal {
  position: relative;
  width: min(var(--seal-size), 64vw);
  height: min(var(--seal-size), 64vw);
  display: grid;
  place-items: center;
}
.seal-layer {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  overflow: visible;
  will-change: transform;
}
/* El giro es de la capa entera, no de cada trazo: así lo compone la tarjeta gráfica
   sin volver a pintar las curvas. */
.seal-layer--forward { animation: seal-turn 240s linear infinite; }
.seal-layer--backward { animation: seal-turn 180s linear infinite reverse; }
@keyframes seal-turn { to { transform: rotate(360deg); } }

.rule, .tick, .guilloche { fill: none; stroke: var(--accent); }
.rule { stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.55; }
.rule--strong { stroke-width: 1.2; opacity: 0.9; }
.tick { stroke-width: max(0.8px, calc(var(--device-pixel, 0) * 1px)); opacity: 0.5; }
.tick--major { stroke-width: 1.2; opacity: 0.85; stroke: var(--accent-bright); }

/* Las curvas se graban al aparecer; su estado final es el de reposo, para que con
   movimiento reducido se vean enteras sin animar nada. */
.guilloche {
  stroke-width: max(0.6px, calc(var(--device-pixel, 0) * 1px));
  opacity: 0.6;
  stroke-dasharray: 1;
  stroke-dashoffset: 0;
  animation: seal-engrave 2.4s cubic-bezier(0.3, 0.1, 0.2, 1) var(--delay) backwards;
}
.guilloche--cross { opacity: 0.38; stroke: var(--accent-bright); }
.guilloche--inner { opacity: 0.7; }
@keyframes seal-engrave {
  from { stroke-dashoffset: 1; opacity: 0; }
  20% { opacity: 0.6; }
}

.seal-disc {
  position: relative;
  width: 62%; height: 62%;
  border-radius: 50%;
  display: grid; place-items: center;
  background: radial-gradient(circle at 50% 38%, color-mix(in srgb, var(--surface) 80%, var(--accent-dim)), var(--surface) 72%);
  box-shadow: inset 0 0 0 1px var(--accent-dim), 0 0 40px var(--accent-dim);
  animation: seal-disc-in 1.1s var(--ease-settle, ease-out) 0.1s backwards;
}
.seal-disc img { width: 60%; height: 60%; object-fit: contain; }
@keyframes seal-disc-in { from { opacity: 0; transform: scale(0.9); } }

@media (prefers-reduced-motion: reduce) {
  .seal-layer, .guilloche, .seal-disc { animation: none; }
}
</style>
