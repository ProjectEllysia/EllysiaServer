<template>
  <!-- Sin herramientas no hay sección: ni título, ni hueco, ni margen. -->
  <section v-if="tools.length" id="free-tools" class="bench" aria-labelledby="free-tools-title">
    <ModuleAtmosphere :module-id="moduleId" strength="subtle" focus="sides" />

    <div class="bench-inner">
      <header v-reveal class="bench-intro">
        <span class="bench-ornament" aria-hidden="true"></span>
        <h2 id="free-tools-title" class="bench-title">{{ t('freeTools.title') }}</h2>
        <p class="bench-bajada">{{ t('freeTools.subtitle') }}</p>
      </header>

      <ul class="bench-grid">
        <li v-for="(tool, index) in tools" :key="tool.id" v-reveal="staggerDelay(index, 130)">
          <router-link :to="tool.path" class="instrument glyph-host" @pointermove="followPointer" @pointerleave="releasePointer">
            <span class="instrument-glow" aria-hidden="true"></span>
            <ToolGlyph :tool-id="tool.id" :size="84" />
            <div class="instrument-body">
              <span class="instrument-access" :data-access="tool.access">{{ t(`freeTools.access.${tool.access}`) }}</span>
              <h3 class="instrument-title">{{ t(`freeTools.items.${tool.id}.title`) }}</h3>
              <p class="instrument-desc">{{ t(`freeTools.items.${tool.id}.desc`) }}</p>
              <span class="instrument-go">
                {{ t('freeTools.open') }} <span class="instrument-arrow" aria-hidden="true">→</span>
              </span>
            </div>
          </router-link>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import ModuleAtmosphere from '@/components/decor/ModuleAtmosphere.vue'
import ToolGlyph from '@/components/decor/ToolGlyph.vue'
import { staggerDelay } from '@/composables/motionMath'
import { vReveal } from '@/directives/reveal'
import { useFreeTools } from '@/freeTools/useFreeTools'

/**
 * Sección «Herramientas gratuitas» de un hub de módulo.
 *
 * Se alimenta sola del catálogo (`freeTools/catalog.js`): el hub solo dice a qué
 * módulo pertenece. Si el módulo no tiene herramientas —o el servidor ha
 * cerrado las que tenía—, no pinta nada. Cada tarjeta lleva el medallón de su
 * herramienta, que se traza al aparecer y se mueve al pasar el puntero.
 */
const props = defineProps({
  /** Módulo del hub: `themis`, `aegis`, `iris`, `acheron` o `hygeia`. */
  moduleId: { type: String, required: true },
})

const { t } = useI18n()
const { tools } = useFreeTools(() => props.moduleId)

/**
 * Coloca el brillo de la tarjeta bajo el puntero.
 *
 * @param {PointerEvent} event - Movimiento del puntero sobre la tarjeta.
 */
function followPointer(event) {
  const card = event.currentTarget
  const box = card.getBoundingClientRect()
  card.style.setProperty('--pointer-x', `${event.clientX - box.left}px`)
  card.style.setProperty('--pointer-y', `${event.clientY - box.top}px`)
}

/**
 * Retira el brillo cuando el puntero sale de la tarjeta.
 *
 * @param {PointerEvent} event - Salida del puntero.
 */
function releasePointer(event) {
  event.currentTarget.style.removeProperty('--pointer-x')
  event.currentTarget.style.removeProperty('--pointer-y')
}
</script>

<style scoped>
/* Una banda a todo el ancho, para separar «lo que hace» de «lo que puedes usar
   ya». Detrás, la escena del módulo en tenue: la misma de su cabecera. */
.bench {
  position: relative; z-index: 1;
  overflow: hidden;
  background: color-mix(in srgb, var(--surface) 55%, transparent);
  border-top: 1px solid var(--border-med);
  border-bottom: 1px solid var(--border-med);
}
.bench-inner {
  position: relative;
  max-width: 1060px;
  margin: 0 auto;
  padding: 3.8rem 2rem 4.2rem;
}
.bench-intro { text-align: center; margin-bottom: 2.6rem; }

/* Adorno: un filete que se abre desde un rombo central cuando la cabecera aparece */
.bench-ornament { display: block; position: relative; height: 12px; width: 240px; max-width: 70%; margin: 0 auto 1.1rem; }
.bench-ornament::before, .bench-ornament::after {
  content: '';
  position: absolute; top: 50%; height: 1px;
  background: linear-gradient(to var(--direction), var(--accent), transparent);
  width: 0;
  transition: width 1.4s var(--ease-settle) 0.3s;
}
.bench-ornament::before { --direction: left; right: calc(50% + 10px); }
.bench-ornament::after { --direction: right; left: calc(50% + 10px); }
.bench-intro.is-in .bench-ornament::before, .bench-intro.is-in .bench-ornament::after { width: calc(50% - 10px); }
.bench-ornament { background: linear-gradient(var(--accent), var(--accent)) center / 7px 7px no-repeat; }
.bench-title {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-xl); font-weight: 600;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent);
}
.bench-bajada { font-size: var(--fs-lg); color: var(--text-dim); margin-top: 0.5rem; }

/* Flex centrado y no rejilla: con una o dos herramientas las tarjetas conservan
   su ancho y quedan bajo el título, en vez de estirarse a todo el ancho. */
.bench-grid { list-style: none; display: flex; flex-wrap: wrap; justify-content: center; gap: 1.2rem; }
.bench-grid > li { flex: 0 1 330px; }

/* ── Tarjeta ── */
.instrument {
  position: relative;
  height: 100%;
  overflow: hidden;
  display: flex; flex-direction: column; align-items: flex-start; gap: 0.9rem;
  padding: 1.4rem 1.5rem 1.3rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-radius: var(--radius);
  transition: transform 0.35s var(--ease-settle), border-color var(--transition), box-shadow 0.35s ease;
}
.instrument:hover, .instrument:focus-visible {
  border-color: var(--accent);
  transform: translateY(-5px);
  box-shadow: 0 16px 38px rgba(0, 0, 0, 0.26), 0 0 0 1px var(--accent-dim);
}
.instrument:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }

/* Un brillo del color del módulo que sigue al puntero por la superficie de la tarjeta */
.instrument-glow {
  position: absolute; inset: 0;
  opacity: 0;
  background: radial-gradient(260px circle at var(--pointer-x, 50%) var(--pointer-y, 30%), var(--accent-dim), transparent 70%);
  transition: opacity 0.4s ease;
  pointer-events: none;
}
.instrument:hover .instrument-glow { opacity: 1; }
.instrument > * { position: relative; }
.instrument > .instrument-glow { position: absolute; }
.instrument-body { display: flex; flex-direction: column; align-items: flex-start; gap: 0.45rem; flex: 1; }

/* Lo que cuesta usarla: el único dato que cambia de una herramienta a otra. */
.instrument-access {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.instrument-access::before { content: ''; width: 0.5rem; height: 0.5rem; border-radius: 50%; border: 1px solid var(--accent); }
/* Sin cuenta = punto lleno; con cuenta, vacío. Se lee sin leer la etiqueta. */
.instrument-access[data-access="public"]::before { background: var(--accent); }

.instrument-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; line-height: 1.25; color: var(--text); }
.instrument-desc { font-size: var(--fs-md); color: var(--text-dim); line-height: 1.6; flex: 1; }
.instrument-go { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-md); color: var(--accent-bright); margin-top: 0.4rem; }
.instrument-arrow { display: inline-block; transition: transform 0.35s var(--ease-settle); }
.instrument:hover .instrument-arrow { transform: translateX(6px); }

@media (max-width: 640px) {
  .bench-inner { padding: 2.8rem 1.4rem 3rem; }
}
@media (prefers-reduced-motion: reduce) {
  .instrument:hover, .instrument:focus-visible { transform: none; }
  .instrument:hover .instrument-arrow { transform: none; }
  .bench-ornament::before, .bench-ornament::after { transition: none; width: calc(50% - 10px); }
}
</style>
