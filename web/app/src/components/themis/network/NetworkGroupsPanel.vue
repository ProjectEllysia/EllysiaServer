<template>
  <div class="network">
    <div class="engine-card" data-scope="network">
      <ScopeMotif scope="network" :active="creating || isRiskLoading" />
      <div class="engine-head">
        <div class="engine-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7.3 11 16.7 6M7.3 13l9.4 5"/></svg>
        </div>
        <div class="engine-title-wrap">
          <span class="engine-eyebrow">{{ t('lybra.scopeEyebrow.network') }}</span>
          <span class="engine-title">{{ t('lybra.network.title') }}</span>
          <span class="engine-sub">{{ t('lybra.network.subtitle') }}</span>
        </div>
      </div>

      <form class="group-form" @submit.prevent="submit">
        <div class="field">
          <label for="group-name">{{ t('lybra.network.name') }}</label>
          <input id="group-name" v-model="name" maxlength="100" :placeholder="t('lybra.network.namePlaceholder')" autocomplete="off" />
        </div>
        <div class="field">
          <label for="group-cidr">{{ t('lybra.network.range') }}</label>
          <input id="group-cidr" v-model="cidr" class="mono" placeholder="10.0.0.0/24" autocomplete="off" spellcheck="false" />
        </div>
        <button type="submit" class="btn-create" :class="{ loading: creating }" :disabled="creating || !canSubmit">
          <span class="btn-nodes" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7.3 11 16.7 6M7.3 13l9.4 5"/></svg></span>
          {{ t('lybra.network.create') }}
        </button>
      </form>
      <p v-if="cidr.trim() && !isRangeValid" class="field-error">{{ t('lybra.network.rangeInvalid') }}</p>
    </div>

    <p v-if="error" class="note error">{{ error }}</p>
    <p v-else-if="loading && !groups.length" class="note">{{ t('common.loading') }}</p>
    <div v-else-if="!groups.length" class="empty">
      <span>{{ t('lybra.network.empty') }}</span>
    </div>

    <TransitionGroup v-else tag="ul" name="group-item" class="groups">
      <li v-for="group in groups" :key="group.groupId" class="group" :class="{ open: openGroups.has(group.groupId) }">
        <div class="group-head">
          <button type="button" class="group-toggle" :aria-expanded="openGroups.has(group.groupId)" @click="toggle(group.groupId)">
            <span class="chevron" :class="{ rot: openGroups.has(group.groupId) }" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </span>
            <span class="group-name">{{ group.name }}</span>
            <span class="group-cidr mono">{{ group.cidr }}</span>
            <span v-if="riskOf(group.groupId) && !riskOf(group.groupId).loading && riskOf(group.groupId).hostCount >= 2"
              class="group-tally" :class="{ risky: riskOf(group.groupId).risks.length }">
              {{ t('lybra.network.riskCount', { count: riskOf(group.groupId).risks.length }, riskOf(group.groupId).risks.length) }}
            </span>
          </button>
          <button v-if="openGroups.has(group.groupId)" type="button" class="icon-btn" :title="t('themis.refresh')" :aria-label="t('themis.refresh')"
            @click="$emit('load-risk', group.groupId)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: riskOf(group.groupId)?.loading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </button>
          <button type="button" class="icon-btn danger" :title="t('common.delete')" :aria-label="t('lybra.network.deleteGroup', { name: group.name })"
            @click="$emit('delete', group.groupId)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6M9 6V4h6v2"/></svg>
          </button>
        </div>
        <Transition name="group-panel">
          <div v-if="openGroups.has(group.groupId)" class="group-body">
            <LateralRiskList :risks="riskOf(group.groupId)?.risks || []" :host-count="riskOf(group.groupId)?.hostCount || 0"
              :loading="!riskOf(group.groupId) || riskOf(group.groupId).loading" :error="riskOf(group.groupId)?.error || null" />
          </div>
        </Transition>
      </li>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { classifyTarget } from '../lybra/targetShapes'
import LateralRiskList from '../lybra/LateralRiskList.vue'
import ScopeMotif from '../lybra/ScopeMotif.vue'

const { t } = useI18n()

const props = defineProps({
  groups: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  creating: { type: Boolean, default: false },
  /** Riesgo lateral por ámbito (`group:<id>`), del store de red. */
  riskByScope: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['create', 'delete', 'load-risk'])

const name = ref('')
const cidr = ref('')

/** Un grupo se define por un rango: una dirección suelta no es una red. */
const isRangeValid = computed(() => classifyTarget(cidr.value) === 'network' && cidr.value.includes('/'))
const canSubmit = computed(() => !!name.value.trim() && isRangeValid.value)

/**
 * Pide crear el grupo. El padre llama de vuelta a `done` con el resultado, y
 * el formulario solo se vacía si se creó: un rechazo (nombre repetido) deja lo
 * escrito para corregirlo.
 */
function submit() {
  if (!canSubmit.value || props.creating) return
  emit('create', { name: name.value.trim(), cidr: cidr.value.trim() }, (isCreated) => {
    if (!isCreated) return
    name.value = ''
    cidr.value = ''
  })
}

/** Si algún grupo está calculando su riesgo lateral: el motor está trabajando. */
const isRiskLoading = computed(() => Object.values(props.riskByScope).some(risk => risk?.loading))

const openGroups = ref(new Set())

/** Riesgo calculado de un grupo, o `null` si aún no se ha pedido. */
function riskOf(groupId) { return props.riskByScope[`group:${groupId}`] || null }

function toggle(groupId) {
  const next = new Set(openGroups.value)
  if (next.has(groupId)) next.delete(groupId)
  else {
    next.add(groupId)
    if (!riskOf(groupId)) emit('load-risk', groupId)
  }
  openGroups.value = next
}
</script>

<style scoped>
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.network { display: flex; flex-direction: column; gap: 1rem; }

.engine-card {
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 220%);
  border: 1px solid var(--accent); border-radius: 12px; padding: 1.2rem 1.35rem;
  box-shadow: 0 0 0 1px var(--accent-dim), 0 12px 34px rgba(0,0,0,0.16);
  position: relative; isolation: isolate; overflow: hidden;
}
.engine-head { display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.7rem; }
.engine-mark {
  width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  color: var(--scope-tint); background: var(--scope-tint-dim); border: 1px solid var(--scope-tint);
}
.engine-mark svg { width: 21px; height: 21px; }
.engine-title-wrap { display: flex; flex-direction: column; min-width: 0; }
.engine-eyebrow { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-xs); font-weight: 600; letter-spacing: 0.24em; text-transform: uppercase; color: var(--scope-tint); }
.engine-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; color: color-mix(in srgb, var(--text) 86%, var(--scope-tint)); }
.engine-sub { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-style: italic; font-size: var(--fs-md); color: var(--text-muted); }

.group-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 12rem) auto; gap: 0.6rem; align-items: end; }
.field { display: flex; flex-direction: column; gap: 0.35rem; }
.field label { font-size: var(--fs-label); color: var(--text-dim); }
.field input {
  width: 100%; box-sizing: border-box; padding: 0.5rem 0.7rem; background: var(--surface-2);
  border: 1px solid var(--border-solid); border-radius: 7px; color: var(--text); font-size: var(--fs-input); outline: none;
}
.field input:focus { border-color: var(--accent); }
.field-error { margin: 0.4rem 0 0; font-size: var(--fs-sm); color: var(--danger); }
.btn-create {
  padding: 0.55rem 1.1rem; background: var(--accent); border: 1px solid var(--accent); border-radius: 7px;
  color: var(--on-accent); font-size: var(--fs-btn); font-weight: 600; cursor: pointer; white-space: nowrap;
}
.btn-create { display: inline-flex; align-items: center; justify-content: center; gap: 0.45rem; }
.btn-create:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-create.loading:disabled { opacity: 0.85; cursor: progress; }
.btn-nodes { display: grid; place-items: center; }
.btn-nodes svg { width: 15px; height: 15px; }
/* Los tres nodos del icono se encienden por turnos al pasar por encima y mientras se crea. */
.btn-nodes circle { transform-box: fill-box; transform-origin: center; }
.btn-create:hover:not(:disabled) .btn-nodes circle, .btn-create.loading .btn-nodes circle { animation: node-blink 1.2s ease-in-out infinite; }
.btn-create:hover:not(:disabled) .btn-nodes circle:nth-child(2), .btn-create.loading .btn-nodes circle:nth-child(2) { animation-delay: 0.2s; }
.btn-create:hover:not(:disabled) .btn-nodes circle:nth-child(3), .btn-create.loading .btn-nodes circle:nth-child(3) { animation-delay: 0.4s; }
@keyframes node-blink { 0%, 60%, 100% { transform: scale(1); opacity: 1; } 30% { transform: scale(1.35); opacity: 0.55; } }
.btn-create:focus-visible, .group-toggle:focus-visible, .icon-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.note { margin: 0; font-size: var(--fs-body); color: var(--text-muted); }
.note.error { color: var(--danger); }
.empty { padding: 1.6rem 1rem; text-align: center; font-size: var(--fs-body); color: var(--text-muted); background: var(--surface); border: 1px dashed var(--border-solid); border-radius: 12px; line-height: 1.5; }

.groups { position: relative; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.group { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; transition: border-color 0.2s ease; }
.group.open { border-color: var(--accent); }
.group-head { display: flex; align-items: center; gap: 0.3rem; padding: 0.25rem 0.4rem 0.25rem 0.2rem; }
.group-toggle {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;
  padding: 0.55rem 0.5rem; background: none; border: none; color: inherit; font: inherit; text-align: left; cursor: pointer;
}
.chevron { display: grid; place-items: center; color: var(--text-muted); transition: transform 0.2s ease; }
.chevron svg { width: 13px; height: 13px; }
.chevron.rot { transform: rotate(90deg); }
.group-name { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.group-cidr { font-size: var(--fs-body); color: var(--text-dim); }
.group-tally { margin-left: auto; font-size: var(--fs-sm); color: var(--success); }
.group-tally.risky { color: var(--warn); font-weight: 600; }
.icon-btn { width: 30px; height: 30px; display: grid; place-items: center; flex: none; background: none; border: 1px solid transparent; border-radius: 7px; color: var(--text-muted); cursor: pointer; }
.icon-btn svg { width: 14px; height: 14px; }
.icon-btn:hover { border-color: var(--border); color: var(--text); }
.icon-btn.danger:hover { border-color: var(--danger); color: var(--danger); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.group-body { padding: 0.2rem 1rem 1rem; }

.group-item-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.group-item-enter-from { opacity: 0; transform: translateY(-4px); }
.group-item-leave-active { transition: opacity 0.15s ease; position: absolute; inset-inline: 0; }
.group-item-leave-to { opacity: 0; }
.group-panel-enter-active, .group-panel-leave-active { transition: opacity 0.2s ease; }
.group-panel-enter-from, .group-panel-leave-to { opacity: 0; }

@media (max-width: 640px) {
  .engine-card { padding: 1rem; }
  .group-form { grid-template-columns: minmax(0, 1fr); }
  .btn-create { width: 100%; }
  .group-tally { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .spin, .btn-nodes circle { animation: none !important; }
  .group, .chevron, .group-item-enter-active, .group-item-leave-active, .group-panel-enter-active, .group-panel-leave-active { transition: none; }
}
</style>
