<template>
  <!-- Sin herramientas no hay sección: ni título, ni hueco, ni margen. -->
  <section v-if="tools.length" id="free-tools" class="bench" aria-labelledby="free-tools-title">
    <div class="bench-inner">
      <header class="bench-intro">
        <h2 id="free-tools-title" class="bench-title">{{ t('freeTools.title') }}</h2>
        <p class="bench-bajada">{{ t('freeTools.subtitle') }}</p>
      </header>

      <ul class="bench-grid">
        <li v-for="tool in tools" :key="tool.id">
          <router-link :to="tool.path" class="instrument">
            <span class="instrument-access" :data-access="tool.access">{{ t(`freeTools.access.${tool.access}`) }}</span>
            <h3 class="instrument-title">{{ t(`freeTools.items.${tool.id}.title`) }}</h3>
            <p class="instrument-desc">{{ t(`freeTools.items.${tool.id}.desc`) }}</p>
            <span class="instrument-go">
              {{ t('freeTools.open') }} <span aria-hidden="true">→</span>
            </span>
          </router-link>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useFreeTools } from '@/freeTools/useFreeTools'

/**
 * Sección «Herramientas gratuitas» de un hub de módulo.
 *
 * Se alimenta sola del catálogo (`freeTools/catalog.js`): el hub solo dice a qué
 * módulo pertenece. Si el módulo no tiene herramientas —o el servidor ha
 * cerrado las que tenía—, no pinta nada.
 */
const props = defineProps({
  /** Módulo del hub: `themis`, `aegis`, `iris`, `acheron` o `hygeia`. */
  moduleId: { type: String, required: true },
})

const { t } = useI18n()
const { tools } = useFreeTools(() => props.moduleId)
</script>

<style scoped>
/* Una banda a todo el ancho, para separar «lo que hace» de «lo que puedes usar
   ya». Las capacidades de arriba son texto con filete; aquí cada pieza es algo
   que se pulsa, y por eso lleva superficie y borde propios. */
.bench {
  position: relative; z-index: 1;
  background: color-mix(in srgb, var(--surface) 55%, transparent);
  border-top: 1px solid var(--border-med);
  border-bottom: 1px solid var(--border-med);
}
.bench-inner {
  max-width: 1060px;
  margin: 0 auto;
  padding: 3.6rem 2rem 4rem;
}
.bench-intro { text-align: center; margin-bottom: 2.4rem; }
.bench-title {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-xl); font-weight: 600;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent);
}
.bench-bajada {
  font-size: var(--fs-lg);
  color: var(--text-dim);
  margin-top: 0.5rem;
}

/* Flex centrado y no rejilla: con una o dos herramientas las tarjetas conservan
   su ancho y quedan bajo el título, en vez de estirarse a todo el ancho. */
.bench-grid {
  list-style: none;
  display: flex; flex-wrap: wrap; justify-content: center;
  gap: 1.1rem;
}
.bench-grid > li { flex: 0 1 330px; }

.instrument {
  height: 100%;
  display: flex; flex-direction: column; align-items: flex-start; gap: 0.55rem;
  padding: 1.35rem 1.5rem 1.2rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-radius: var(--radius);
  transition: all var(--transition);
}
.instrument:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: 0 10px 30px rgba(0,0,0,0.2), 0 0 0 1px var(--accent-dim);
}
.instrument:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }

/* Lo que cuesta usarla: el único dato que cambia de una herramienta a otra. */
.instrument-access {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.instrument-access::before {
  content: '';
  width: 0.5rem; height: 0.5rem;
  border-radius: 50%;
  border: 1px solid var(--accent);
}
/* Sin cuenta = punto lleno; con cuenta, vacío. Se lee sin leer la etiqueta. */
.instrument-access[data-access="public"]::before { background: var(--accent); }

.instrument-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-xl); font-weight: 600;
  line-height: 1.25;
  color: var(--text);
}
.instrument-desc {
  font-size: var(--fs-md);
  color: var(--text-dim);
  line-height: 1.6;
  flex: 1;
}
.instrument-go {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  color: var(--accent-bright);
  margin-top: 0.4rem;
}

@media (max-width: 640px) {
  .bench-inner { padding: 2.8rem 1.4rem 3rem; }
}
@media (prefers-reduced-motion: reduce) {
  .instrument:hover { transform: none !important; }
}
</style>
