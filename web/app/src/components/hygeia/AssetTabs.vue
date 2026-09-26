<template>
  <!-- Teclado: las flechas mueven entre pestañas e Inicio/Fin saltan a los
       extremos, que es lo que un lector de pantalla anuncia y lo que espera
       quien navega sin ratón. Solo la pestaña activa entra en el orden de
       tabulación (tabindex -1 en las demás), como manda el patrón de tablist. -->
  <div class="tabs" role="tablist" :aria-label="t('hygeia.tabs.label')" @keydown="onKeydown">
    <button v-for="(tab, index) in tabs" :key="tab.id"
      ref="tabButtons"
      class="tab" :class="{ active: active === tab.id }"
      role="tab"
      :id="`tab-${tab.id}`"
      :aria-selected="active === tab.id"
      :aria-controls="`panel-${tab.id}`"
      :tabindex="active === tab.id ? 0 : -1"
      :title="t('hygeia.tabs.shortcut', { key: index + 1 })"
      @click="$emit('switch', tab.id)">
      {{ t(`hygeia.tabs.${tab.id}`) }}
      <span v-if="tab.id === 'anomalias' && anomalyCount" class="tab-badge">
        {{ anomalyCount }}
        <span class="sr-only">{{ t('hygeia.tabs.openAnomalies') }}</span>
      </span>
      <span
        v-else-if="tab.id === 'estadisticas' && statsWarning"
        class="tab-dot"
        role="img"
        :aria-label="t('hygeia.tabs.statsWarning')"
        :title="t('hygeia.tabs.statsWarning')"
      ></span>
    </button>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  active: { type: String, required: true },
  anomalyCount: { type: Number, default: 0 },
  statsWarning: { type: Boolean, default: false },
})
const emit = defineEmits(['switch'])

/** Pestañas en su orden; el rótulo está en `hygeia.tabs.<id>` y el atajo es su posición. */
const tabs = [{ id: 'graficas' }, { id: 'estadisticas' }, { id: 'inventario' }, { id: 'anomalias' }]

const tabButtons = ref([])

/** Mueve el foco y la selección a la pestaña de la posición dada. */
async function focusTab(index) {
  const destino = (index + tabs.length) % tabs.length
  emit('switch', tabs[destino].id)
  await nextTick()
  tabButtons.value[destino]?.focus()
}

function onKeydown(event) {
  const actual = tabs.findIndex((tab) => tab.id === props.active)
  const teclas = {
    ArrowRight: () => focusTab(actual + 1),
    ArrowLeft:  () => focusTab(actual - 1),
    Home:       () => focusTab(0),
    End:        () => focusTab(tabs.length - 1),
  }
  const accion = teclas[event.key]
  if (!accion) return
  event.preventDefault()
  accion()
}
</script>

<style scoped>
.tabs {
  display: flex; gap: 0.2rem;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.25rem;
}
.tab {
  flex: 1; padding: 0.5rem 0.85rem;
  background: none; border: none; border-radius: 6px;
  color: var(--text-muted); font-size: var(--fs-lg); font-weight: 500; cursor: pointer;
  display: flex; align-items: center; justify-content: center; gap: 0.4rem;
  transition: all 0.2s ease;
}
.tab:hover { color: var(--text-dim); }
.tab.active { background: var(--surface-2); color: var(--text); font-weight: 600; }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

.tab-badge {
  padding: 0.05rem 0.45rem; border-radius: 999px;
  background: var(--danger-dim); color: var(--danger);
  font-size: var(--fs-sm); font-weight: 700; letter-spacing: 0;
}

/* Aviso discreto (no es una anomalía registrada, solo una lectura puntual
   por encima del umbral) — por eso un punto en vez de una insignia roja. */
.tab-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--warn); flex-shrink: 0; }

/* El número solo no dice de qué: para quien escucha, "3" no es "3 anomalías". */
.sr-only {
  position: absolute; width: 1px; height: 1px;
  overflow: hidden; clip-path: inset(50%); white-space: nowrap;
}
</style>
