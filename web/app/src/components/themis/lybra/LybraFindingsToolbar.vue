<template>
  <!-- Barra de orden y filtros del capítulo de hallazgos. No guarda estado: los
       criterios viven en LybraResults.vue, por escaneo, y aquí solo se pintan y
       se devuelven cambiados. Así dos tarjetas abiertas a la vez no comparten
       filtros. -->
  <div class="findings-toolbar" role="search" :aria-label="t('lybra.toolbar.label', { id: scanId })">
    <div class="toolbar-row">
      <label class="search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <span class="visually-hidden">{{ t('lybra.toolbar.search') }}</span>
        <input type="search" :value="modelValue.text" :placeholder="t('lybra.toolbar.searchPlaceholder')"
          @input="update({ text: $event.target.value })" />
      </label>

      <div class="sort">
        <label class="sort-label" :for="`lybra-sort-${scanId}`">{{ t('lybra.toolbar.sortBy') }}</label>
        <select :id="`lybra-sort-${scanId}`" :value="modelValue.sortKey" @change="update({ sortKey: $event.target.value, reversed: false })">
          <option v-for="option in SORT_OPTIONS" :key="option.value" :value="option.value">{{ t(`lybra.toolbar.sort.${option.value}`) }}</option>
        </select>
        <!-- El texto dice el orden que hay, no la acción: «Más grave primero»
             se entiende sin saber qué significa una flecha hacia abajo. -->
        <button type="button" class="direction" :aria-pressed="modelValue.reversed"
          :title="t('lybra.toolbar.invert', { direction: directionLabel(!modelValue.reversed) })"
          @click="update({ reversed: !modelValue.reversed })">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" :class="{ flipped: modelValue.reversed }">
            <path d="M7 4v16M3 16l4 4 4-4"/><path d="M14 6h7M14 11h5M14 16h3"/>
          </svg>
          {{ directionLabel(modelValue.reversed) }}
        </button>
      </div>
    </div>

    <!-- Pastillas de gravedad: ninguna encendida equivale a todas, que es como
         se abre el capítulo. El número es cuántos se verían con esa gravedad y
         el resto de filtros, esté encendida o no. -->
    <div class="facet">
      <span :id="`lybra-sev-label-${scanId}`" class="facet-label">{{ t('lybra.toolbar.severity') }}</span>
      <div class="severity-chips" role="group" :aria-labelledby="`lybra-sev-label-${scanId}`">
        <button v-for="level in LADDER" :key="level" type="button" class="sev-chip" :data-sev="level.toLowerCase()"
          :class="{ on: modelValue.priorities.includes(level), idle: !modelValue.priorities.length }"
          :aria-pressed="modelValue.priorities.includes(level)" :disabled="!priorityCounts[level] && !modelValue.priorities.includes(level)"
          @click="togglePriority(level)">
          {{ priorityLabel(level) }} <span class="chip-count">{{ priorityCounts[level] }}</span>
        </button>
      </div>
    </div>

    <div class="toolbar-row">
      <div class="facet">
        <span :id="`lybra-state-label-${scanId}`" class="facet-label">{{ t('lybra.toolbar.stateLabel') }}</span>
        <div class="segmented" role="radiogroup" :aria-labelledby="`lybra-state-label-${scanId}`">
          <label v-for="option in STATE_OPTIONS" :key="option.value" class="segment" :class="{ active: modelValue.state === option.value }">
            <input type="radio" :name="`lybra-state-${scanId}`" :value="option.value" :checked="modelValue.state === option.value"
              @change="update({ state: option.value })" />
            {{ t(`lybra.toolbar.state.${option.value}`) }}<span v-if="option.value !== 'all'" class="chip-count">{{ stateCounts[option.value] }}</span>
          </label>
        </div>
      </div>

      <div class="facet">
        <span :id="`lybra-certainty-label-${scanId}`" class="facet-label">{{ t('lybra.toolbar.certaintyLabel') }}</span>
        <div class="segmented" role="radiogroup" :aria-labelledby="`lybra-certainty-label-${scanId}`">
          <label v-for="option in CERTAINTY_OPTIONS" :key="option.value" class="segment" :class="{ active: modelValue.certainty === option.value }">
            <input type="radio" :name="`lybra-certainty-${scanId}`" :value="option.value" :checked="modelValue.certainty === option.value"
              @change="update({ certainty: option.value })" />
            {{ t(`lybra.toolbar.certainty.${option.value}`) }}
          </label>
        </div>
      </div>
    </div>

    <Transition name="tally">
      <p v-if="isFiltering(modelValue)" class="tally" aria-live="polite">
        <i18n-t keypath="lybra.toolbar.showing" :plural="total" tag="span">
          <template #visible><strong>{{ visibleTotal }}</strong></template>
          <template #count>{{ total }}</template>
        </i18n-t>
        <button type="button" class="reset" @click="$emit('reset')">{{ t('lybra.results.clearFilters') }}</button>
      </p>
    </Transition>
  </div>
</template>

<script setup>
import {
  LADDER, SORT_OPTIONS, STATE_OPTIONS, CERTAINTY_OPTIONS, isFiltering,
} from './findingsArrangement'
import { priorityLabel } from '../labels'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  /** Escaneo al que pertenece la barra; da nombres únicos a sus controles. */
  scanId: { type: Number, required: true },
  /** Criterios actuales, con la forma de `defaultCriteria()`. */
  modelValue: { type: Object, required: true },
  /** Hallazgos que se verían con cada gravedad (recuento facetado). */
  priorityCounts: { type: Object, required: true },
  /** Hallazgos pendientes y resueltos con el resto de filtros aplicados. */
  stateCounts: { type: Object, required: true },
  /** Hallazgos visibles con los filtros actuales. */
  visibleTotal: { type: Number, required: true },
  /** Hallazgos del escaneo sin filtrar. */
  total: { type: Number, required: true },
})
const emit = defineEmits(['update:modelValue', 'reset'])


/**
 * Cómo se lee el sentido del orden para cada criterio: la rama de
 * `lybra.toolbar.direction` con su texto natural (`natural`) e invertido
 * (`reversed`).
 */
const DIRECTION_KEYS = {
  severity: 'severity',
  cvss: 'numeric',
  epss: 'numeric',
  title: 'alphabetic',
  product: 'alphabetic',
}

/**
 * Describe el sentido del orden con el criterio actual.
 *
 * @param {boolean} reversed - `true` para el sentido invertido.
 * @returns {string} P. ej. «Más grave primero» o «Z → A».
 */
function directionLabel(reversed) {
  const key = DIRECTION_KEYS[props.modelValue.sortKey] || DIRECTION_KEYS.severity
  return t(`lybra.toolbar.direction.${key}.${reversed ? 'reversed' : 'natural'}`)
}

/**
 * Emite los criterios con los cambios indicados encima.
 *
 * Se emite un objeto nuevo y no se toca el recibido: el padre decide cuándo
 * aplicarlo, y mutarlo aquí se lo saltaría.
 *
 * @param {object} changes - Campos de los criterios que cambian.
 */
function update(changes) {
  emit('update:modelValue', { ...props.modelValue, ...changes })
}

/**
 * Enciende o apaga una gravedad en el filtro.
 *
 * Las gravedades elegidas se guardan en el orden de `LADDER`, para que el
 * mismo filtro dé siempre los mismos criterios pulse el usuario en el orden
 * que pulse.
 *
 * @param {string} level - Nivel de `LADDER`.
 */
function togglePriority(level) {
  const chosen = new Set(props.modelValue.priorities)
  if (chosen.has(level)) chosen.delete(level)
  else chosen.add(level)
  update({ priorities: LADDER.filter(item => chosen.has(item)) })
}
</script>

<style scoped>
.findings-toolbar {
  display: flex; flex-direction: column; gap: 0.55rem;
  margin-bottom: 1.15rem; padding: 0.7rem 0.8rem;
  background: var(--surface); border: 1px solid var(--border-med); border-radius: 10px;
}
.toolbar-row { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem 0.9rem; }

.toolbar-row > .facet { flex: 0 1 auto; }
.facet { display: flex; align-items: center; flex-wrap: wrap; gap: 0.35rem 0.6rem; }
.facet-label { min-width: 4.6rem; font-size: var(--fs-md); color: var(--text-muted); }
.search { position: relative; flex: 1 1 16rem; min-width: 0; display: flex; }
.search svg { position: absolute; left: 0.6rem; top: 50%; width: 14px; height: 14px; transform: translateY(-50%); color: var(--text-muted); pointer-events: none; }
.search input { width: 100%; padding: 0.4rem 0.6rem 0.4rem 1.9rem; font-size: var(--fs-md); }

.sort { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }
.sort-label { font-size: var(--fs-md); color: var(--text-muted); white-space: nowrap; }
.sort select { padding: 0.35rem 0.55rem; font-size: var(--fs-md); }
.direction {
  display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.6rem;
  background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 6px;
  color: var(--text-dim); font-size: var(--fs-md); cursor: pointer; white-space: nowrap;
  transition: border-color 0.15s, color 0.15s;
}
.direction:hover { border-color: var(--accent); color: var(--text); }
.direction svg { width: 14px; height: 14px; transition: transform 0.25s ease; }
.direction svg.flipped { transform: scaleY(-1); }

.severity-chips { display: flex; flex-wrap: wrap; gap: 0.3rem; }
/* Apagadas en reposo cuando hay alguna encendida; con ninguna encendida todas
   se ven a medio tono, porque ninguna es «todas». */
.sev-chip {
  display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.55rem;
  font-size: var(--fs-md); font-weight: 600; border-radius: 999px; cursor: pointer;
  color: var(--text-muted); background: none; border: 1px solid var(--border-solid);
  transition: color 0.15s, background 0.15s, border-color 0.15s, opacity 0.15s;
}
.sev-chip.idle { color: var(--sev); border-color: color-mix(in srgb, var(--sev) 45%, transparent); }
.sev-chip.on { color: var(--sev); background: color-mix(in srgb, var(--sev) 16%, transparent); border-color: var(--sev); }
.sev-chip:hover:not(:disabled) { border-color: var(--sev); color: var(--sev); }
.sev-chip:disabled { opacity: 0.4; cursor: default; }
.sev-chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
[data-sev="critical"] { --sev: var(--danger); }
[data-sev="high"]     { --sev: var(--warn); }
[data-sev="medium"]   { --sev: var(--info); }
[data-sev="low"]      { --sev: var(--success); }
[data-sev="info"]     { --sev: var(--text-muted); }
.chip-count { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); opacity: 0.85; }

/* Mismo control segmentado que LogsView.vue, en tamaño de barra. */
.segmented { display: flex; gap: 0.25rem; }
.segment {
  position: relative; display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.25rem 0.6rem;
  border: 1px solid var(--border-med); border-radius: 7px; color: var(--text-dim);
  cursor: pointer; font-size: var(--fs-md); white-space: nowrap; transition: all 0.2s ease;
}
.segment input { position: absolute; opacity: 0; pointer-events: none; }
.segment:hover { border-color: var(--accent); }
.segment.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.segment:focus-within { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

.tally { margin: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; font-size: var(--fs-md); color: var(--text-muted); }
.tally strong { color: var(--text); font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.reset { padding: 0; background: none; border: none; color: var(--accent-bright); font-size: var(--fs-md); cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.reset:hover { color: var(--accent); }
.tally-enter-active, .tally-leave-active { transition: opacity 0.18s ease; }
.tally-enter-from, .tally-leave-to { opacity: 0; }

.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

@media (max-width: 700px) {
  .segmented { flex-wrap: wrap; }
  .sort { width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .direction svg, .sev-chip, .segment, .tally-enter-active, .tally-leave-active { transition: none !important; }
}
</style>
