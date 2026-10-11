<template>
  <ToolShell tool-id="crosswalkMap" more-to="/eunomia/marcos">
    <p v-if="status === 'loading'" class="cm-state" aria-live="polite">{{ t('freeTools.items.crosswalkMap.loading') }}</p>
    <p v-else-if="status === 'error'" class="cm-state cm-state--error" role="alert">{{ errorMessage }}</p>

    <div v-else class="cm">
      <div class="cm-field">
        <label class="cm-label" for="cm-reference">{{ t('freeTools.items.crosswalkMap.referenceLabel') }}</label>
        <select id="cm-reference" v-model="referenceKey" class="cm-input">
          <option v-for="framework in frameworks" :key="framework.key" :value="framework.key">{{ framework.shortName }}</option>
        </select>
        <p class="cm-hint">{{ t('freeTools.items.crosswalkMap.linkedCount', { linked: linkedCount, total: assessableCount }) }}</p>
      </div>

      <div class="cm-board">
        <ul class="cm-list" :aria-label="reference.name">
          <li v-for="control in reference.controls" :key="control.identifier" class="cm-row" :style="{ '--depth': control.depth }">
            <!-- Un control con correspondencias se puede señalar, enfocar y fijar (en táctil no hay hover). -->
            <button
              v-if="hasLinks(control)"
              type="button"
              class="cm-control cm-control--linked"
              :class="{ 'is-active': control.identifier === activeId }"
              :aria-pressed="control.identifier === pinnedId"
              @mouseenter="hoveredId = control.identifier"
              @mouseleave="hoveredId = null"
              @focus="hoveredId = control.identifier"
              @blur="hoveredId = null"
              @click="pinnedId = pinnedId === control.identifier ? null : control.identifier"
            >
              <span class="cm-id">{{ control.identifier }}</span>
              <span>{{ control.title }}</span>
            </button>
            <p v-else class="cm-control" :class="{ 'cm-control--group': !control.isAssessable }">
              <span class="cm-id">{{ control.identifier }}</span>
              <span>{{ control.title }}</span>
            </p>
          </li>
        </ul>

        <aside class="cm-panel" aria-live="polite">
          <template v-if="activeControl">
            <h2 class="cm-panel-title"><span class="cm-id">{{ activeControl.identifier }}</span> {{ activeControl.title }}</h2>
            <section v-for="group in matches" :key="group.framework" class="cm-group">
              <h3 class="cm-group-title">{{ group.name }}</h3>
              <ul class="cm-matches">
                <li v-for="item in group.items" :key="item.identifier" class="cm-match">
                  <span class="cm-id">{{ item.identifier }}</span>
                  <span>{{ item.title }}</span>
                  <span class="cm-coverage" :data-coverage="item.coverage">{{ t(`freeTools.items.crosswalkMap.coverage.${item.coverage}`) }}</span>
                </li>
              </ul>
            </section>
          </template>
          <p v-else class="cm-hint">{{ t('freeTools.items.crosswalkMap.empty') }}</p>
          <p v-if="unlinked.length" class="cm-hint cm-unlinked">{{ t('freeTools.items.crosswalkMap.unlinked', { names: unlinked.join(', ') }) }}</p>
        </aside>
      </div>

      <p class="cm-note">{{ t('freeTools.items.crosswalkMap.note') }}</p>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { apiError, useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/authStore'
import {
  controlKey,
  correspondencesOf,
  indexLinks,
  unlinkedFrameworks,
} from '@/components/freeTools/crosswalkMap'

/**
 * Mapa de correspondencias de Eunomia, herramienta gratuita con cuenta.
 *
 * Lee de una vez `GET /eunomia/crosswalks` (los marcos vigentes con sus controles y los enlaces
 * entre ellos). El marco de referencia sale a la izquierda con todos sus controles; al señalar uno
 * con correspondencias, a la derecha salen los controles de los demás marcos que lo cubren. Los
 * marcos y los cruces son los del catálogo: nada de aquí nombra uno en concreto.
 */
const { t } = useI18n()
const { apiFetch } = useApi()
const auth = useAuthStore()

const status = ref('loading') // loading | ready | error
const errorMessage = ref('')
const frameworks = ref([])
const links = ref([])
const referenceKey = ref('')
const hoveredId = ref(null)
const pinnedId = ref(null)

const order = computed(() => frameworks.value.map((framework) => framework.key))
const index = computed(() => indexLinks(links.value))
const reference = computed(() => frameworks.value.find((framework) => framework.key === referenceKey.value)
  ?? { name: '', controls: [] })

const hasLinks = (control) => index.value.has(controlKey(referenceKey.value, control.identifier))
const assessableCount = computed(() => reference.value.controls.filter((control) => control.isAssessable).length)
const linkedCount = computed(() => reference.value.controls.filter((control) => control.isAssessable && hasLinks(control)).length)

/** El control que se enseña a la derecha: el que se señala y, si no hay, el que se fijó con un clic. */
const activeId = computed(() => hoveredId.value ?? pinnedId.value)
const activeControl = computed(() => reference.value.controls.find((control) => control.identifier === activeId.value) ?? null)

/** Los controles de todos los marcos por su clave, para poner título a lo que corresponde. */
const controlsByKey = computed(() => new Map(frameworks.value.flatMap(
  (framework) => framework.controls.map((control) => [controlKey(framework.key, control.identifier), control]),
)))
const nameOf = (key) => frameworks.value.find((framework) => framework.key === key)?.shortName ?? key

const matches = computed(() => {
  if (!activeControl.value) return []
  return correspondencesOf(index.value, referenceKey.value, activeControl.value.identifier, order.value)
    .map((group) => ({
      framework: group.framework,
      name: nameOf(group.framework),
      items: group.items.map((item) => ({
        ...item,
        title: controlsByKey.value.get(controlKey(group.framework, item.identifier))?.title ?? '',
      })),
    }))
})

const unlinked = computed(() => unlinkedFrameworks(links.value, referenceKey.value, order.value).map(nameOf))

watch(referenceKey, () => {
  hoveredId.value = null
  pinnedId.value = null
})

/** Pide el mapa y deja el primer marco del catálogo como referencia. */
async function load() {
  status.value = 'loading'
  try {
    const response = await apiFetch('/eunomia/crosswalks')
    if (!response?.ok) {
      errorMessage.value = await apiError(response, t('freeTools.items.crosswalkMap.failed'))
      status.value = 'error'
      return
    }
    const body = await response.json()
    frameworks.value = body.frameworks
    links.value = body.links
    referenceKey.value = body.frameworks[0]?.key ?? ''
    status.value = 'ready'
  } catch {
    errorMessage.value = t('freeTools.items.crosswalkMap.failed')
    status.value = 'error'
  }
}

// Sin sesión la herramienta enseña la invitación a entrar (`ToolShell`); pedir el mapa llevaría al login.
onMounted(() => { if (auth.isAuthenticated) load() })
</script>

<style scoped>
.cm { display: flex; flex-direction: column; gap: 1.4rem; }
.cm-state { color: var(--text-dim); line-height: 1.6; }
.cm-state--error { color: var(--danger); }

.cm-label {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.cm-hint { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.cm-field { display: flex; flex-direction: column; gap: 0.45rem; min-width: 0; }
.cm-input {
  font-size: var(--fs-md);
  padding: 0.65rem 0.8rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  max-width: min(100%, 22rem);
}
.cm-input:focus-visible, .cm-control--linked:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }

/* ── Izquierda: el marco de referencia; derecha: lo que corresponde al control señalado ── */
.cm-board { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.4rem; align-items: start; }

.cm-list {
  list-style: none; margin: 0; padding: 0;
  max-height: min(70vh, 640px); overflow-y: auto;
  border: 1px solid var(--border-med); border-radius: var(--radius-sm);
  background: var(--bg);
}
.cm-row { padding-left: calc(var(--depth, 0) * 1rem); }
.cm-control {
  display: flex; gap: 0.7rem;
  width: 100%; margin: 0; padding: 0.5rem 0.8rem;
  font-size: var(--fs-md); line-height: 1.4; text-align: left;
  color: var(--text-muted);
  background: none; border: 0; border-left: 3px solid transparent;
}
.cm-control--group { color: var(--text-dim); font-weight: 600; }
.cm-control--linked { color: var(--text); cursor: pointer; border-left-color: var(--accent); }
.cm-control--linked:hover, .cm-control--linked.is-active { background: var(--accent-dim); }

.cm-id {
  flex: none;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  color: var(--text-muted);
}

.cm-panel {
  position: sticky; top: 1rem;
  border: 1px solid var(--border-med); border-left: 4px solid var(--accent-bright);
  border-radius: var(--radius-sm);
  padding: 1.2rem 1.4rem;
  background: var(--surface);
  display: flex; flex-direction: column; gap: 1rem;
}
.cm-panel-title { font-size: var(--fs-md); font-weight: 600; color: var(--text); line-height: 1.45; }
.cm-group-title {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm); font-weight: 400;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--accent-bright);
  margin-bottom: 0.5rem;
}
.cm-matches { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.cm-match { display: flex; flex-wrap: wrap; gap: 0.2rem 0.7rem; color: var(--text-dim); line-height: 1.45; }
.cm-coverage { flex-basis: 100%; font-size: var(--fs-sm); color: var(--text-muted); }
.cm-coverage[data-coverage="full"] { color: var(--accent-bright); }
.cm-unlinked { border-top: 1px solid var(--border-med); padding-top: 0.8rem; }

.cm-note { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

/* En una columna, lo que corresponde va encima de la lista para verlo sin desplazarse. */
@media (max-width: 720px) {
  .cm-board { grid-template-columns: 1fr; }
  .cm-panel { order: -1; position: static; }
  .cm-list { max-height: 50vh; }
}
</style>
